from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import asyncpg


logger = logging.getLogger("insights.counterfactual_sync")


@dataclass(frozen=True)
class ProxyScenarioConfig:
    """用途：描述一组代理回放参数档位配置。

    参数：
        profile_name：参数档位名称。
        display_name：前端展示名称。
        positive_factor：对正向 TPSL 贡献的保留倍数。
        negative_factor：对负向 TPSL 影响的保留倍数。
        trigger_factor：对触发次数的缩放倍数。
        hold_gap_factor：相对于当前实际持有时长，向原始路径靠拢的比例。
        drawdown_gap_factor：对实际与原始路径回撤差值的插值倍数。
        note：该档位的业务说明。
    返回值：
        便于批量生成代理实验结果的不可变配置对象。
    异常/边界：
        系数均为相对值，不代表真实生产参数本身。
    """

    profile_name: str
    display_name: str
    positive_factor: float
    negative_factor: float
    trigger_factor: float
    hold_gap_factor: float
    drawdown_gap_factor: float
    note: str


PROXY_METHOD = "proxy_heuristic_v1"
PROXY_SCENARIOS: tuple[ProxyScenarioConfig, ...] = (
    ProxyScenarioConfig(
        profile_name="balanced_guard",
        display_name="平衡档位",
        positive_factor=0.9,
        negative_factor=0.85,
        trigger_factor=0.92,
        hold_gap_factor=0.2,
        drawdown_gap_factor=0.25,
        note="在当前实盘参数附近做小步微调，适合作为现网参数的近邻对照组。",
    ),
    ProxyScenarioConfig(
        profile_name="loose_guard",
        display_name="放宽档位",
        positive_factor=0.68,
        negative_factor=0.42,
        trigger_factor=0.76,
        hold_gap_factor=0.55,
        drawdown_gap_factor=0.62,
        note="更偏趋势跟随，减少过早止损止盈，适合排查风控是否偏敏感。",
    ),
    ProxyScenarioConfig(
        profile_name="tight_guard",
        display_name="收紧档位",
        positive_factor=1.18,
        negative_factor=1.28,
        trigger_factor=1.2,
        hold_gap_factor=-0.12,
        drawdown_gap_factor=-0.18,
        note="更偏防守，适合验证是否还能进一步压低回撤，但可能牺牲部分趋势收益。",
    ),
)


def _to_float(value: Any) -> float | None:
    """用途：把数据库返回值安全转换为浮点数。

    参数：
        value：任意数据库字段值。
    返回值：
        成功转换后的浮点数，或 `None`。
    异常/边界：
        当值为空时直接返回 `None`，避免把缺失值误转为 0。
    """

    if value is None:
        return None
    return float(value)


def _to_int(value: Any) -> int:
    """用途：把数据库返回值安全转换为整数。

    参数：
        value：任意数据库字段值。
    返回值：
        成功转换后的整数，空值回退为 0。
    异常/边界：
        仅用于聚合结果兜底，不应用于区分真实空值与真实 0 的业务判断。
    """

    if value is None:
        return 0
    return int(value)


def _calculate_max_drawdown(cumulative_values: list[float]) -> float | None:
    """用途：根据累计收益序列估算最大回撤。

    参数：
        cumulative_values：按时间顺序排列的累计收益序列。
    返回值：
        最大回撤数值，非负；若样本不足则返回 `None`。
    异常/边界：
        当前以累计收益差值近似回撤，不依赖净值归一化，因此更适合内部相对比较。
    """

    if not cumulative_values:
        return None

    peak = cumulative_values[0]
    max_drawdown = 0.0
    for value in cumulative_values:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)
    return round(max_drawdown, 6)


def _calculate_win_rate(values: list[float]) -> float | None:
    """用途：根据单笔收益列表计算胜率。

    参数：
        values：单笔收益数值列表。
    返回值：
        0 到 1 之间的胜率；样本为空时返回 `None`。
    异常/边界：
        收益等于 0 的样本视为非胜利样本，以避免夸大胜率。
    """

    if not values:
        return None
    win_count = sum(1 for value in values if value > 0)
    return round(win_count / len(values), 6)


async def sync_proxy_counterfactual_facts(pool: asyncpg.Pool) -> dict[str, int]:
    """用途：生成首版代理回放实验结果并写入 `fact_tpsl_counterfactual`。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        包含策略实例数、实验组数与写入行数的统计字典。
    异常/边界：
        这是基于现有真实收益和 TPSL 贡献拆解生成的代理实验，不等同于完整分钟级历史回放；
        结果会在 `result_payload.method` 中明确标注为 `proxy_heuristic_v1`。
    """

    summary_query = """
        WITH lifecycle_stats AS (
            SELECT
                strategy_name,
                portfolio_id,
                ROUND(AVG(holding_minutes_actual)::numeric, 2)::float8 AS avg_hold_minutes_actual,
                ROUND(AVG(holding_minutes_raw)::numeric, 2)::float8 AS avg_hold_minutes_raw,
                COUNT(*)::int AS lifecycle_count
            FROM insights.fact_position_lifecycle
            WHERE strategy_name IS NOT NULL
            GROUP BY strategy_name, portfolio_id
        ),
        intervention_stats AS (
            SELECT
                strategy_name,
                portfolio_id,
                COUNT(*)::int AS tpsl_trigger_count,
                ROUND(SUM(COALESCE(protected_pnl, 0))::numeric, 6)::float8 AS protected_sum,
                ROUND(SUM(COALESCE(missed_pnl, 0))::numeric, 6)::float8 AS missed_sum,
                COUNT(*) FILTER (WHERE classification = 'PRE_REBALANCE_EXIT_STILL_IN_TARGET')::int AS still_in_target_count,
                COUNT(*) FILTER (WHERE classification = 'PRE_REBALANCE_EXIT_REMOVED_FROM_TARGET')::int AS removed_from_target_count
            FROM insights.fact_tpsl_intervention
            GROUP BY strategy_name, portfolio_id
        ),
        daily_span AS (
            SELECT
                strategy_name,
                portfolio_id,
                MIN(trade_date) AS date_from,
                MAX(trade_date) AS date_to
            FROM insights.fact_strategy_daily
            GROUP BY strategy_name, portfolio_id
        )
        SELECT
            ds.strategy_name,
            ds.portfolio_id,
            ds.tactic_id,
            daily_span.date_from,
            daily_span.date_to,
            lifecycle_stats.avg_hold_minutes_actual,
            lifecycle_stats.avg_hold_minutes_raw,
            lifecycle_stats.lifecycle_count,
            intervention_stats.tpsl_trigger_count,
            intervention_stats.protected_sum,
            intervention_stats.missed_sum,
            intervention_stats.still_in_target_count,
            intervention_stats.removed_from_target_count
        FROM daily_span
        JOIN insights.dim_strategy ds
            ON ds.strategy_name = daily_span.strategy_name
           AND ds.portfolio_id = daily_span.portfolio_id
        LEFT JOIN lifecycle_stats
            ON lifecycle_stats.strategy_name = daily_span.strategy_name
           AND lifecycle_stats.portfolio_id = daily_span.portfolio_id
        LEFT JOIN intervention_stats
            ON intervention_stats.strategy_name = daily_span.strategy_name
           AND intervention_stats.portfolio_id = daily_span.portfolio_id
        ORDER BY ds.strategy_name ASC, ds.portfolio_id ASC
    """

    daily_query = """
        SELECT
            trade_date,
            COALESCE(realized_pnl_actual_cum::float8, 0) AS realized_pnl_actual_cum,
            COALESCE(realized_pnl_raw_cum::float8, 0) AS realized_pnl_raw_cum
        FROM insights.fact_strategy_daily
        WHERE strategy_name = $1
          AND portfolio_id = $2
        ORDER BY trade_date ASC
    """

    lifecycle_pnl_query = """
        SELECT
            pnl_actual::float8 AS pnl_actual,
            pnl_raw::float8 AS pnl_raw
        FROM insights.fact_position_lifecycle
        WHERE strategy_name = $1
          AND portfolio_id = $2
          AND actual_path_status = 'CLOSED'
    """

    insert_query = """
        INSERT INTO insights.fact_tpsl_counterfactual (
            experiment_id,
            strategy_name,
            portfolio_id,
            tactic_id,
            param_profile,
            date_from,
            date_to,
            cum_return,
            max_drawdown,
            sharpe,
            win_rate,
            trade_count,
            tpsl_trigger_count,
            avg_hold_minutes,
            net_delta_vs_baseline,
            result_payload,
            updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, $10, $11, $12, $13, $14, $15, $16::jsonb, NOW()
        )
        ON CONFLICT (experiment_id, strategy_name, portfolio_id, param_profile)
        DO UPDATE SET
            tactic_id = EXCLUDED.tactic_id,
            date_from = EXCLUDED.date_from,
            date_to = EXCLUDED.date_to,
            cum_return = EXCLUDED.cum_return,
            max_drawdown = EXCLUDED.max_drawdown,
            sharpe = EXCLUDED.sharpe,
            win_rate = EXCLUDED.win_rate,
            trade_count = EXCLUDED.trade_count,
            tpsl_trigger_count = EXCLUDED.tpsl_trigger_count,
            avg_hold_minutes = EXCLUDED.avg_hold_minutes,
            net_delta_vs_baseline = EXCLUDED.net_delta_vs_baseline,
            result_payload = EXCLUDED.result_payload,
            updated_at = NOW()
    """

    async with pool.acquire() as conn:
        summary_rows = await conn.fetch(summary_query)
        if not summary_rows:
            logger.warning("⚠️ 没有可用于生成代理回放实验的策略样本")
            return {"strategy_count": 0, "scenario_count": 0, "rows_upserted": 0}

        lifecycle_value_map: dict[tuple[str, str], dict[str, list[float]]] = {}
        daily_value_map: dict[tuple[str, str], list[asyncpg.Record]] = {}

        for row in summary_rows:
            strategy_name = str(row["strategy_name"])
            portfolio_id = str(row["portfolio_id"])
            daily_rows = await conn.fetch(daily_query, strategy_name, portfolio_id)
            lifecycle_rows = await conn.fetch(lifecycle_pnl_query, strategy_name, portfolio_id)
            daily_value_map[(strategy_name, portfolio_id)] = daily_rows
            lifecycle_value_map[(strategy_name, portfolio_id)] = {
                "actual": [_to_float(item["pnl_actual"]) or 0.0 for item in lifecycle_rows if item["pnl_actual"] is not None],
                "raw": [_to_float(item["pnl_raw"]) or 0.0 for item in lifecycle_rows if item["pnl_raw"] is not None],
            }

        async with conn.transaction():
            delete_status = await conn.execute(
                """
                DELETE FROM insights.fact_tpsl_counterfactual
                WHERE result_payload ->> 'method' = $1
                """,
                PROXY_METHOD,
            )
            logger.info("🔍 已清理旧的代理回放实验结果 status=%s", delete_status)

            rows_upserted = 0
            strategy_count = 0
            scenario_count = 0

            for row in summary_rows:
                strategy_name = str(row["strategy_name"])
                portfolio_id = str(row["portfolio_id"])
                date_from = row["date_from"]
                date_to = row["date_to"]
                if date_from is None or date_to is None:
                    continue

                daily_rows = daily_value_map[(strategy_name, portfolio_id)]
                if not daily_rows:
                    continue

                strategy_count += 1
                tactic_id = row["tactic_id"]
                base_experiment_id = uuid5(
                    NAMESPACE_URL,
                    f"insights:{PROXY_METHOD}:{strategy_name}:{portfolio_id}:{date_from}:{date_to}",
                )

                raw_cumulative_series: list[float] = []
                actual_cumulative_series: list[float] = []
                for daily_row in daily_rows:
                    raw_cumulative_series.append(round(_to_float(daily_row["realized_pnl_raw_cum"]) or 0.0, 6))
                    actual_cumulative_series.append(round(_to_float(daily_row["realized_pnl_actual_cum"]) or 0.0, 6))

                raw_win_rate = _calculate_win_rate(lifecycle_value_map[(strategy_name, portfolio_id)]["raw"])
                actual_win_rate = _calculate_win_rate(lifecycle_value_map[(strategy_name, portfolio_id)]["actual"])
                avg_hold_actual = _to_float(row["avg_hold_minutes_actual"])
                avg_hold_raw = _to_float(row["avg_hold_minutes_raw"])
                hold_gap = 0.0
                if avg_hold_actual is not None and avg_hold_raw is not None:
                    hold_gap = avg_hold_raw - avg_hold_actual

                baseline_payload = {
                    "method": PROXY_METHOD,
                    "display_name": "原始未干预基线",
                    "note": "基于原始调仓卖点估算的默认基线，用于衡量当前 TPSL 实际净增益。",
                    "source": "fact_strategy_daily + fact_position_lifecycle",
                    "series_basis": "raw_daily",
                }
                await conn.execute(
                    insert_query,
                    base_experiment_id,
                    strategy_name,
                    portfolio_id,
                    tactic_id,
                    "raw_baseline",
                    date_from,
                    date_to,
                    raw_cumulative_series[-1],
                    _calculate_max_drawdown(raw_cumulative_series),
                    None,
                    raw_win_rate,
                    _to_int(row["lifecycle_count"]),
                    0,
                    avg_hold_raw,
                    0.0,
                    json.dumps(baseline_payload, ensure_ascii=False),
                )
                rows_upserted += 1
                scenario_count += 1

                actual_minus_baseline = round(actual_cumulative_series[-1] - raw_cumulative_series[-1], 6)
                current_payload = {
                    "method": PROXY_METHOD,
                    "display_name": "当前实际执行",
                    "note": "真实发生的策略执行路径，包含 STRAT 与 TPSL 的共同作用结果。",
                    "source": "fact_strategy_daily + fact_position_lifecycle + fact_tpsl_intervention",
                    "series_basis": "actual_daily",
                }
                await conn.execute(
                    insert_query,
                    base_experiment_id,
                    strategy_name,
                    portfolio_id,
                    tactic_id,
                    "current_live",
                    date_from,
                    date_to,
                    actual_cumulative_series[-1],
                    _calculate_max_drawdown(actual_cumulative_series),
                    None,
                    actual_win_rate,
                    _to_int(row["lifecycle_count"]),
                    _to_int(row["tpsl_trigger_count"]),
                    avg_hold_actual,
                    actual_minus_baseline,
                    json.dumps(current_payload, ensure_ascii=False),
                )
                rows_upserted += 1
                scenario_count += 1

                observed_protected = _to_float(row["protected_sum"]) or 0.0
                observed_missed = _to_float(row["missed_sum"]) or 0.0
                actual_effect = actual_minus_baseline
                raw_drawdown = _calculate_max_drawdown(raw_cumulative_series) or 0.0
                actual_drawdown = _calculate_max_drawdown(actual_cumulative_series) or 0.0

                for config in PROXY_SCENARIOS:
                    scenario_effect = round(
                        actual_effect
                        + (config.positive_factor - 1.0) * observed_protected
                        - (config.negative_factor - 1.0) * observed_missed,
                        6,
                    )
                    proxy_cum = round(raw_cumulative_series[-1] + scenario_effect, 6)

                    interpolated_win_rate = None
                    if raw_win_rate is not None or actual_win_rate is not None:
                        raw_component = raw_win_rate if raw_win_rate is not None else actual_win_rate
                        actual_component = actual_win_rate if actual_win_rate is not None else raw_win_rate
                        if raw_component is not None and actual_component is not None:
                            blend = max(0.0, min(1.25, (config.positive_factor + config.negative_factor) / 2))
                            interpolated_win_rate = round(raw_component + (actual_component - raw_component) * blend, 6)

                    avg_hold_proxy = avg_hold_actual
                    if avg_hold_actual is not None and avg_hold_raw is not None:
                        avg_hold_proxy = round(max(1.0, avg_hold_actual + hold_gap * config.hold_gap_factor), 2)

                    proxy_drawdown = round(
                        max(
                            0.0,
                            actual_drawdown + (raw_drawdown - actual_drawdown) * config.drawdown_gap_factor,
                        ),
                        6,
                    )

                    proxy_payload = {
                        "method": PROXY_METHOD,
                        "display_name": config.display_name,
                        "note": config.note,
                        "source": "proxy_from_actual_raw_and_intervention_sums",
                        "series_basis": "raw_cum + adjusted(protected_pnl, missed_pnl)",
                        "coefficients": {
                            "positive_factor": config.positive_factor,
                            "negative_factor": config.negative_factor,
                            "trigger_factor": config.trigger_factor,
                            "hold_gap_factor": config.hold_gap_factor,
                            "drawdown_gap_factor": config.drawdown_gap_factor,
                        },
                        "protected_sum": _to_float(row["protected_sum"]),
                        "missed_sum": _to_float(row["missed_sum"]),
                        "still_in_target_count": _to_int(row["still_in_target_count"]),
                        "removed_from_target_count": _to_int(row["removed_from_target_count"]),
                    }
                    await conn.execute(
                        insert_query,
                        base_experiment_id,
                        strategy_name,
                        portfolio_id,
                        tactic_id,
                        config.profile_name,
                        date_from,
                        date_to,
                        proxy_cum,
                        proxy_drawdown,
                        None,
                        interpolated_win_rate,
                        _to_int(row["lifecycle_count"]),
                        max(0, round(_to_int(row["tpsl_trigger_count"]) * config.trigger_factor)),
                        avg_hold_proxy,
                        round(proxy_cum - raw_cumulative_series[-1], 6),
                        json.dumps(proxy_payload, ensure_ascii=False),
                    )
                    rows_upserted += 1
                    scenario_count += 1

        logger.info(
            "✅ 代理回放实验结果同步完成 strategy_count=%s scenario_count=%s rows_upserted=%s",
            strategy_count,
            scenario_count,
            rows_upserted,
        )
        return {
            "strategy_count": strategy_count,
            "scenario_count": scenario_count,
            "rows_upserted": rows_upserted,
        }
