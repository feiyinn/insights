from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid4

import asyncpg

from ..db.clickhouse_client import ClickHouseMarketClient


logger = logging.getLogger("insights.symbol_tpsl_sync")

SYMBOL_PROXY_METHOD = "symbol_proxy_heuristic_v1"


@dataclass(frozen=True)
class SymbolRecommendationDraft:
    """用途：承载单个标的推荐结果的中间态数据。

    参数：
        recommended_action：建议动作。
        recommended_profile：建议档位名称。
        hard_sl_multiplier：硬止损倍数。
        break_even_trigger_multiplier：保本触发倍数。
        trailing_buffer_multiplier：跟踪止损倍数。
        take_profit_trigger_multiplier：止盈触发倍数。
        expected_delta_bps：预估的净影响 bps。
        expected_misfire_rate：预估误杀率。
        expected_protection_efficiency：预估保护效率。
        priority_score：建议优先级。
        reason_summary：建议摘要。
        payload：附加解释信息。
    返回值：
        便于批量写入建议表的不可变对象。
    异常/边界：
        该对象只表示启发式建议结果，不代表真实分钟级历史回放。
    """

    recommended_action: str
    recommended_profile: str | None
    hard_sl_multiplier: float
    break_even_trigger_multiplier: float
    trailing_buffer_multiplier: float
    take_profit_trigger_multiplier: float
    expected_delta_bps: float | None
    expected_misfire_rate: float | None
    expected_protection_efficiency: float | None
    priority_score: float
    reason_summary: str
    payload: dict[str, Any]


def _to_float(value: Any) -> float | None:
    """用途：把数据库字段安全转换为浮点数。

    参数：
        value：任意数据库字段值。
    返回值：
        转换后的浮点数，或 `None`。
    异常/边界：
        空值直接返回 `None`，避免误把缺失值当成 0。
    """

    if value is None:
        return None
    return float(value)


def _to_int(value: Any) -> int:
    """用途：把数据库字段安全转换为整数。

    参数：
        value：任意数据库字段值。
    返回值：
        转换后的整数；空值回退为 0。
    异常/边界：
        仅适用于聚合结果兜底，不用于区分真实空值与真实 0。
    """

    if value is None:
        return 0
    return int(value)


def _safe_ratio(numerator: float | None, denominator: float | None, *, digits: int = 6) -> float | None:
    """用途：安全计算比例值并控制小数位。

    参数：
        numerator：分子。
        denominator：分母。
        digits：保留小数位数。
    返回值：
        比例值；若分母为空或为 0，则返回 `None`。
    异常/边界：
        不自动放大为百分比或 bps，调用方自行决定展示单位。
    """

    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, digits)


def _safe_bps(numerator: float | None, denominator: float | None) -> float | None:
    """用途：把收益变化标准化为 bps。

    参数：
        numerator：收益或收益变化金额。
        denominator：统一分母，通常为已补价名义本金。
    返回值：
        以 bps 表示的标准化结果；若无法计算则返回 `None`。
    异常/边界：
        该函数仅负责数值换算，不负责说明口径是否为正式净值收益率。
    """

    ratio = _safe_ratio(numerator, denominator, digits=8)
    if ratio is None:
        return None
    return round(ratio * 10000, 6)


def _clamp(value: float, lower: float, upper: float) -> float:
    """用途：把浮点数限制在给定区间内。

    参数：
        value：原始值。
        lower：下界。
        upper：上界。
    返回值：
        裁剪后的数值。
    异常/边界：
        默认调用方保证 `lower <= upper`。
    """

    return max(lower, min(upper, value))


def _pick_date_bounds(row: asyncpg.Record, as_of_date: date) -> tuple[date, date]:
    """用途：从多来源日期字段中选出一个标的样本窗口。

    参数：
        row：聚合后的数据库记录。
        as_of_date：本次任务运行日期。
    返回值：
        `(date_from, date_to)`。
    异常/边界：
        若所有来源日期都为空，则统一回退到 `as_of_date`，保证结果可写入。
    """

    date_candidates_from = [
        row["lifecycle_date_from"],
        row["intervention_date_from"],
        row["reentry_date_from"],
    ]
    date_candidates_to = [
        row["lifecycle_date_to"],
        row["intervention_date_to"],
        row["reentry_date_to"],
    ]
    valid_from = [item for item in date_candidates_from if item is not None]
    valid_to = [item for item in date_candidates_to if item is not None]
    return (
        min(valid_from) if valid_from else as_of_date,
        max(valid_to) if valid_to else as_of_date,
    )


def _calculate_sample_quality(
    *,
    priced_lifecycles: int,
    tpsl_intervention_count: int,
    priced_coverage_ratio: float | None,
) -> float:
    """用途：按样本量和补价覆盖率估算样本质量分数。

    参数：
        priced_lifecycles：已补价生命周期数量。
        tpsl_intervention_count：TPSL 干预数量。
        priced_coverage_ratio：补价覆盖率。
    返回值：
        0 到 1 之间的样本质量分。
    异常/边界：
        这是启发式分数，主要用于排序与置信度，不应解读为统计显著性。
    """

    lifecycle_component = min(priced_lifecycles / 12, 1.0) * 0.5
    intervention_component = min(tpsl_intervention_count / 8, 1.0) * 0.3
    coverage_component = max(0.0, min(priced_coverage_ratio or 0.0, 1.0)) * 0.2
    return round(lifecycle_component + intervention_component + coverage_component, 6)


def _calculate_confidence_score(
    *,
    sample_quality_score: float,
    date_to: date,
    as_of_date: date,
) -> float:
    """用途：基于样本质量与时间新鲜度估算置信度。

    参数：
        sample_quality_score：样本质量分。
        date_to：最近样本日期。
        as_of_date：本次任务运行日期。
    返回值：
        0 到 1 之间的置信度分数。
    异常/边界：
        当前只做简单新鲜度衰减，后续可加入标的波动性与市场状态修正。
    """

    days_gap = max(0, (as_of_date - date_to).days)
    if days_gap <= 10:
        freshness_factor = 1.0
    elif days_gap <= 20:
        freshness_factor = 0.85
    else:
        freshness_factor = 0.7
    return round(sample_quality_score * freshness_factor, 6)


def _build_diagnosis_label(
    *,
    priced_lifecycles: int,
    tpsl_intervention_count: int,
    delta_bps: float | None,
    misfire_rate: float | None,
    protection_efficiency: float | None,
) -> str:
    """用途：根据标的样本统计结果生成诊断标签。

    参数：
        priced_lifecycles：已补价生命周期数量。
        tpsl_intervention_count：TPSL 干预数量。
        delta_bps：TPSL 净影响 bps。
        misfire_rate：误杀率。
        protection_efficiency：保护效率。
    返回值：
        诊断标签枚举。
    异常/边界：
        当前阈值来自产品首版约定，后续可迁移为配置或表驱动规则。
    """

    if priced_lifecycles < 5 or tpsl_intervention_count < 3:
        return "LOW_SAMPLE"

    delta_value = delta_bps or 0.0
    misfire_value = misfire_rate or 0.0
    protection_value = protection_efficiency or 0.0

    if delta_value <= -25 and misfire_value >= 0.5:
        return "OVER_SENSITIVE"
    if delta_value >= 15 and protection_value >= 0.6 and misfire_value <= 0.35:
        return "PROTECTIVE"
    if abs(delta_value) < 15 and misfire_value < 0.5:
        return "BALANCED"
    return "MIXED"


def _calculate_loosen_severity(
    *,
    delta_bps: float | None,
    misfire_rate: float | None,
    reentry_count: int,
    hold_gap_ratio: float | None,
) -> float:
    """用途：估算放宽型建议的严重度。

    参数：
        delta_bps：TPSL 净影响 bps。
        misfire_rate：误杀率。
        reentry_count：回补买入次数。
        hold_gap_ratio：实际持有时长相对原始路径的偏差。
    返回值：
        0 到 1 之间的严重度分数。
    异常/边界：
        该分数仅用于启发式建议，不代表统计意义上的真实最优参数强度。
    """

    drag_score = min(abs(min(delta_bps or 0.0, 0.0)) / 60, 1.0)
    misfire_score = min(misfire_rate or 0.0, 1.0)
    reentry_score = min(reentry_count / 6, 1.0)
    hold_score = min(abs(min(hold_gap_ratio or 0.0, 0.0)) / 0.5, 1.0)
    return round(drag_score * 0.35 + misfire_score * 0.35 + reentry_score * 0.15 + hold_score * 0.15, 6)


def _calculate_tighten_severity(
    *,
    delta_bps: float | None,
    protection_efficiency: float | None,
    misfire_rate: float | None,
) -> float:
    """用途：估算收紧型建议的严重度。

    参数：
        delta_bps：TPSL 净影响 bps。
        protection_efficiency：保护效率。
        misfire_rate：误杀率。
    返回值：
        0 到 1 之间的严重度分数。
    异常/边界：
        当前假设“正向净影响显著且误杀率较低”时，才考虑轻微收紧。
    """

    positive_score = min(max(delta_bps or 0.0, 0.0) / 60, 1.0)
    protection_score = min(protection_efficiency or 0.0, 1.0)
    discipline_score = 1.0 - min(misfire_rate or 0.0, 1.0)
    return round(positive_score * 0.45 + protection_score * 0.35 + discipline_score * 0.2, 6)


def _build_symbol_recommendation(row: asyncpg.Record) -> SymbolRecommendationDraft:
    """用途：根据标的诊断结果生成参数建议。

    参数：
        row：标的诊断表中的单条记录。
    返回值：
        可直接写入建议表的推荐草案。
    异常/边界：
        当前建议基于启发式规则，不应宣称为真实最优参数解。
    """

    diagnosis_label = str(row["diagnosis_label"])
    delta_bps = _to_float(row["delta_bps"])
    misfire_rate = _to_float(row["misfire_rate"])
    protection_efficiency = _to_float(row["protection_efficiency"])
    hold_gap_ratio = _to_float(row["hold_gap_ratio"])
    reentry_count = _to_int(row["reentry_count"])
    confidence_score = _to_float(row["confidence_score"]) or 0.0
    tpsl_intervention_count = _to_int(row["tpsl_intervention_count"])
    priced_lifecycles = _to_int(row["priced_lifecycles"])
    current_misfire = misfire_rate or 0.0
    current_protection = protection_efficiency or 0.0

    if (
        diagnosis_label == "LOW_SAMPLE"
        and priced_lifecycles >= 2
        and tpsl_intervention_count >= 2
        and confidence_score >= 0.3
        and (delta_bps or 0.0) <= -80
        and current_misfire >= 0.5
    ):
        severity = max(
            0.35,
            _calculate_loosen_severity(
                delta_bps=delta_bps,
                misfire_rate=misfire_rate,
                reentry_count=reentry_count,
                hold_gap_ratio=hold_gap_ratio,
            ),
        )
        priority_score = round(confidence_score * severity * 0.9, 6)
        reason_summary = "当前仍属低样本，但负向净影响和误杀率已经足够明显，建议先把该标的纳入试验性放宽名单。"
        payload = {
            "method": SYMBOL_PROXY_METHOD,
            "mode": "LOW_SAMPLE_TRIAL",
            "severity_score": severity,
            "basis": {
                "priced_lifecycles": priced_lifecycles,
                "tpsl_intervention_count": tpsl_intervention_count,
                "delta_bps": delta_bps,
                "misfire_rate": misfire_rate,
                "reentry_count": reentry_count,
                "hold_gap_ratio": hold_gap_ratio,
            },
        }
        return SymbolRecommendationDraft(
            recommended_action="LOOSEN",
            recommended_profile="symbol_loose_guard_trial",
            hard_sl_multiplier=round(_clamp(1.0 + 0.10 * severity, 1.0, 1.22), 6),
            break_even_trigger_multiplier=round(_clamp(1.0 + 0.14 * severity, 1.0, 1.24), 6),
            trailing_buffer_multiplier=round(_clamp(1.0 + 0.18 * severity, 1.0, 1.26), 6),
            take_profit_trigger_multiplier=round(_clamp(1.0 + 0.08 * severity, 1.0, 1.18), 6),
            expected_delta_bps=round((delta_bps or 0.0) + max(4.0, severity * 12.0), 6),
            expected_misfire_rate=round(max(0.0, current_misfire - 0.12 * severity), 6),
            expected_protection_efficiency=round(min(1.0, current_protection + 0.05 * severity), 6),
            priority_score=priority_score,
            reason_summary=reason_summary,
            payload=payload,
        )

    if (
        diagnosis_label == "LOW_SAMPLE"
        and tpsl_intervention_count >= 3
        and priced_lifecycles == 0
        and current_misfire >= 0.9
    ):
        severity = round(min(1.0, 0.4 + tpsl_intervention_count * 0.1), 6)
        return SymbolRecommendationDraft(
            recommended_action="CUSTOM",
            recommended_profile="symbol_review_pending_pricing",
            hard_sl_multiplier=1.0,
            break_even_trigger_multiplier=1.0,
            trailing_buffer_multiplier=1.0,
            take_profit_trigger_multiplier=1.0,
            expected_delta_bps=delta_bps,
            expected_misfire_rate=misfire_rate,
            expected_protection_efficiency=protection_efficiency,
            priority_score=round(confidence_score * severity * 0.6, 6),
            reason_summary="该标的误杀迹象很强，但原始路径尚未补价完成，建议优先人工复核或补更多价格样本后再定参数。",
            payload={
                "method": SYMBOL_PROXY_METHOD,
                "mode": "LOW_SAMPLE_NEEDS_PRICING",
                "severity_score": severity,
                "basis": {
                    "priced_lifecycles": priced_lifecycles,
                    "tpsl_intervention_count": tpsl_intervention_count,
                    "misfire_rate": misfire_rate,
                },
            },
        )

    if diagnosis_label == "OVER_SENSITIVE":
        severity = _calculate_loosen_severity(
            delta_bps=delta_bps,
            misfire_rate=misfire_rate,
            reentry_count=reentry_count,
            hold_gap_ratio=hold_gap_ratio,
        )
        priority_score = round(confidence_score * severity, 6)
        hard_sl_multiplier = round(_clamp(1.0 + 0.15 * severity, 1.0, 1.3), 6)
        break_even_trigger_multiplier = round(_clamp(1.0 + 0.20 * severity, 1.0, 1.3), 6)
        trailing_buffer_multiplier = round(_clamp(1.0 + 0.25 * severity, 1.0, 1.3), 6)
        take_profit_trigger_multiplier = round(_clamp(1.0 + 0.10 * severity, 1.0, 1.3), 6)
        reason_summary = "该标的更像是 TPSL 偏敏感，建议优先放宽止损与跟踪止损阈值，减少仍在目标池内的提前离场。"
        payload = {
            "method": SYMBOL_PROXY_METHOD,
            "severity_score": severity,
            "basis": {
                "delta_bps": delta_bps,
                "misfire_rate": misfire_rate,
                "reentry_count": reentry_count,
                "hold_gap_ratio": hold_gap_ratio,
            },
        }
        return SymbolRecommendationDraft(
            recommended_action="LOOSEN",
            recommended_profile="symbol_loose_guard",
            hard_sl_multiplier=hard_sl_multiplier,
            break_even_trigger_multiplier=break_even_trigger_multiplier,
            trailing_buffer_multiplier=trailing_buffer_multiplier,
            take_profit_trigger_multiplier=take_profit_trigger_multiplier,
            expected_delta_bps=round((delta_bps or 0.0) + max(6.0, severity * 18.0), 6),
            expected_misfire_rate=round(max(0.0, current_misfire - 0.18 * severity), 6),
            expected_protection_efficiency=round(min(1.0, current_protection + 0.08 * severity), 6),
            priority_score=priority_score,
            reason_summary=reason_summary,
            payload=payload,
        )

    if diagnosis_label == "PROTECTIVE" and confidence_score >= 0.75 and (delta_bps or 0.0) >= 25:
        severity = _calculate_tighten_severity(
            delta_bps=delta_bps,
            protection_efficiency=protection_efficiency,
            misfire_rate=misfire_rate,
        )
        priority_score = round(confidence_score * severity * 0.7, 6)
        reason_summary = "该标的当前 TPSL 保护效果较稳定，且误杀率较低，可尝试轻微收紧以验证回撤控制是否还能继续增强。"
        payload = {
            "method": SYMBOL_PROXY_METHOD,
            "severity_score": severity,
            "basis": {
                "delta_bps": delta_bps,
                "misfire_rate": misfire_rate,
                "protection_efficiency": protection_efficiency,
            },
        }
        return SymbolRecommendationDraft(
            recommended_action="TIGHTEN",
            recommended_profile="symbol_tight_guard",
            hard_sl_multiplier=round(_clamp(1.0 - 0.08 * severity, 0.85, 1.0), 6),
            break_even_trigger_multiplier=round(_clamp(1.0 - 0.06 * severity, 0.85, 1.0), 6),
            trailing_buffer_multiplier=round(_clamp(1.0 - 0.10 * severity, 0.85, 1.0), 6),
            take_profit_trigger_multiplier=round(_clamp(1.0 - 0.04 * severity, 0.85, 1.0), 6),
            expected_delta_bps=round((delta_bps or 0.0) - max(2.0, severity * 6.0), 6),
            expected_misfire_rate=round(min(1.0, current_misfire + 0.06 * severity), 6),
            expected_protection_efficiency=round(min(1.0, current_protection + 0.05 * severity), 6),
            priority_score=priority_score,
            reason_summary=reason_summary,
            payload=payload,
        )

    if diagnosis_label == "MIXED":
        severity = min(1.0, max(abs(delta_bps or 0.0) / 80, misfire_rate or 0.0))
        priority_score = round(confidence_score * severity * 0.5, 6)
        return SymbolRecommendationDraft(
            recommended_action="CUSTOM",
            recommended_profile="symbol_custom_review",
            hard_sl_multiplier=1.0,
            break_even_trigger_multiplier=1.0,
            trailing_buffer_multiplier=1.0,
            take_profit_trigger_multiplier=1.0,
            expected_delta_bps=delta_bps,
            expected_misfire_rate=misfire_rate,
            expected_protection_efficiency=protection_efficiency,
            priority_score=priority_score,
            reason_summary="该标的正负信号交织，建议先人工复核生命周期明细，再决定是否做定制化参数偏移。",
            payload={
                "method": SYMBOL_PROXY_METHOD,
                "severity_score": severity,
                "basis": {
                    "delta_bps": delta_bps,
                    "misfire_rate": misfire_rate,
                    "reentry_count": reentry_count,
                    "tpsl_intervention_count": tpsl_intervention_count,
                },
            },
        )

    return SymbolRecommendationDraft(
        recommended_action="HOLD",
        recommended_profile="symbol_hold",
        hard_sl_multiplier=1.0,
        break_even_trigger_multiplier=1.0,
        trailing_buffer_multiplier=1.0,
        take_profit_trigger_multiplier=1.0,
        expected_delta_bps=delta_bps,
        expected_misfire_rate=misfire_rate,
        expected_protection_efficiency=protection_efficiency,
        priority_score=round(confidence_score * 0.2, 6),
        reason_summary="当前样本不足或信号较平衡，建议先保持现有参数，继续积累更多标的级样本。",
        payload={
            "method": SYMBOL_PROXY_METHOD,
            "basis": {
                "diagnosis_label": diagnosis_label,
                "delta_bps": delta_bps,
                "misfire_rate": misfire_rate,
                "protection_efficiency": protection_efficiency,
            },
        },
    )


async def _fetch_open_raw_lifecycles(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """用途：读取原始路径仍在持有、但实际路径已关闭的生命周期样本。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        生命周期记录列表，用于后续做临时盯市补价。
    异常/边界：
        当前只抓取 `raw_path_status = 'OPEN'` 且 `actual_path_status = 'CLOSED'` 的样本，
        因为这类样本最能体现 TPSL 提前离场后的潜在收益差。
    """

    query = """
        SELECT
            strategy_name,
            portfolio_id,
            instrument_id,
            entry_ts::date AS entry_date,
            entry_price::float8 AS entry_price,
            entry_qty,
            pnl_actual::float8 AS pnl_actual
        FROM insights.fact_position_lifecycle
        WHERE strategy_name IS NOT NULL
          AND raw_path_status = 'OPEN'
          AND actual_path_status = 'CLOSED'
          AND pnl_actual IS NOT NULL
    """
    async with pool.acquire() as conn:
        return await conn.fetch(query)


def _build_provisional_symbol_metrics(
    lifecycle_rows: list[asyncpg.Record],
    latest_close_map: dict[str, tuple[date, Any]],
) -> dict[tuple[str, str, str], dict[str, float | int | str | None]]:
    """用途：基于最新日线收盘价为开放中的原始路径构建临时盯市指标。

    参数：
        lifecycle_rows：满足“原始路径仍持有、实际路径已关闭”的生命周期列表。
        latest_close_map：按标的映射的最新日线收盘价。
    返回值：
        以 `(strategy_name, portfolio_id, instrument_id)` 为键的聚合结果字典。
    异常/边界：
        若某标的无日线价格，则对应生命周期不会进入临时盯市统计。
    """

    result: dict[tuple[str, str, str], dict[str, float | int | str | None]] = {}
    for row in lifecycle_rows:
        instrument_id = str(row["instrument_id"])
        latest_payload = latest_close_map.get(instrument_id)
        if latest_payload is None:
            continue

        latest_trade_date, latest_close = latest_payload
        entry_price = _to_float(row["entry_price"])
        pnl_actual = _to_float(row["pnl_actual"])
        entry_qty = _to_int(row["entry_qty"])
        if entry_price is None or pnl_actual is None or entry_qty <= 0:
            continue

        provisional_raw_pnl = round((float(latest_close) - entry_price) * entry_qty, 6)
        provisional_delta = round(pnl_actual - provisional_raw_pnl, 6)
        entry_notional = round(entry_price * entry_qty, 6)
        key = (str(row["strategy_name"]), str(row["portfolio_id"]), instrument_id)
        bucket = result.setdefault(
            key,
            {
                "provisional_priced_lifecycles": 0,
                "provisional_entry_notional": 0.0,
                "provisional_raw_pnl_sum": 0.0,
                "provisional_delta_pnl_sum": 0.0,
                "latest_trade_date": latest_trade_date.isoformat(),
            },
        )
        bucket["provisional_priced_lifecycles"] = int(bucket["provisional_priced_lifecycles"]) + 1
        bucket["provisional_entry_notional"] = round(float(bucket["provisional_entry_notional"]) + entry_notional, 6)
        bucket["provisional_raw_pnl_sum"] = round(float(bucket["provisional_raw_pnl_sum"]) + provisional_raw_pnl, 6)
        bucket["provisional_delta_pnl_sum"] = round(float(bucket["provisional_delta_pnl_sum"]) + provisional_delta, 6)
        bucket["latest_trade_date"] = latest_trade_date.isoformat()
    return result


async def sync_symbol_tpsl_diagnostics(
    pool: asyncpg.Pool,
    *,
    clickhouse_client: ClickHouseMarketClient | None = None,
) -> dict[str, Any]:
    """用途：聚合并写入标的级 TPSL 诊断事实表。

    参数：
        pool：PostgreSQL 连接池。
        clickhouse_client：可选 ClickHouse 客户端，用于补充开放原始路径的临时盯市估值。
    返回值：
        包含运行标识、写入行数与标签分布的统计字典。
    异常/边界：
        当前仅依赖已落库的生命周期、TPSL 干预与执行事实，因此结果是代理诊断口径；
        若样本尚未补价完成，`confidence_score` 会自动降低。
    """

    query = """
        WITH lifecycle_stats AS (
            SELECT
                strategy_name,
                portfolio_id,
                account_id,
                tactic_id,
                instrument_id,
                MIN(entry_ts::date) AS lifecycle_date_from,
                MAX(COALESCE(exit_ts_actual::date, exit_ts_raw::date, entry_ts::date)) AS lifecycle_date_to,
                COUNT(*)::int AS total_lifecycles,
                COUNT(*) FILTER (WHERE actual_path_status = 'CLOSED')::int AS closed_lifecycles,
                COUNT(*) FILTER (WHERE pnl_raw IS NOT NULL)::int AS priced_lifecycles,
                ROUND(
                    COALESCE(SUM((entry_price * entry_qty)) FILTER (WHERE pnl_raw IS NOT NULL), 0)::numeric,
                    6
                )::float8 AS priced_entry_notional,
                ROUND(COALESCE(SUM(pnl_actual), 0)::numeric, 6)::float8 AS pnl_actual_sum,
                ROUND(COALESCE(SUM(pnl_raw), 0)::numeric, 6)::float8 AS pnl_raw_sum,
                ROUND(COALESCE(SUM(pnl_delta), 0)::numeric, 6)::float8 AS pnl_delta_sum,
                ROUND(AVG(holding_minutes_actual)::numeric, 2)::float8 AS avg_hold_minutes_actual,
                ROUND(AVG(holding_minutes_raw)::numeric, 2)::float8 AS avg_hold_minutes_raw
            FROM insights.fact_position_lifecycle
            WHERE strategy_name IS NOT NULL
            GROUP BY strategy_name, portfolio_id, account_id, tactic_id, instrument_id
        ),
        intervention_stats AS (
            SELECT
                strategy_name,
                portfolio_id,
                account_id,
                tactic_id,
                instrument_id,
                MIN(COALESCE(fill_ts::date, trigger_ts::date)) AS intervention_date_from,
                MAX(COALESCE(fill_ts::date, trigger_ts::date)) AS intervention_date_to,
                COUNT(*)::int AS tpsl_intervention_count,
                COUNT(*) FILTER (WHERE COALESCE(net_pnl_delta, 0) > 0)::int AS positive_intervention_count,
                COUNT(*) FILTER (WHERE COALESCE(net_pnl_delta, 0) < 0)::int AS negative_intervention_count,
                COUNT(*) FILTER (WHERE classification = 'PRE_REBALANCE_EXIT_STILL_IN_TARGET')::int AS still_in_target_intervention_count,
                COUNT(*) FILTER (WHERE classification = 'PRE_REBALANCE_EXIT_REMOVED_FROM_TARGET')::int AS removed_from_target_intervention_count,
                COUNT(*) FILTER (WHERE classification = 'INTRADAY_EXIT_NO_NEXT_TARGET')::int AS no_next_target_intervention_count,
                ROUND(COALESCE(SUM(protected_pnl), 0)::numeric, 6)::float8 AS protected_pnl_sum,
                ROUND(COALESCE(SUM(missed_pnl), 0)::numeric, 6)::float8 AS missed_pnl_sum
            FROM insights.fact_tpsl_intervention
            WHERE strategy_name IS NOT NULL
            GROUP BY strategy_name, portfolio_id, account_id, tactic_id, instrument_id
        ),
        reentry_stats AS (
            SELECT
                foe.strategy_name,
                foe.portfolio_id,
                foe.instrument_id,
                MIN(foe.trade_ts::date) AS reentry_date_from,
                MAX(foe.trade_ts::date) AS reentry_date_to,
                COUNT(*)::int AS reentry_count
            FROM insights.fact_order_execution foe
            WHERE foe.source_type = 'STRAT'
              AND foe.side = 'BUY'
              AND foe.trade_ts IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM insights.fact_tpsl_intervention fti
                  WHERE fti.strategy_name = foe.strategy_name
                    AND fti.portfolio_id = foe.portfolio_id
                    AND fti.instrument_id = foe.instrument_id
                    AND COALESCE(fti.fill_ts, fti.trigger_ts) IS NOT NULL
                    AND COALESCE(fti.fill_ts, fti.trigger_ts) < foe.trade_ts
              )
            GROUP BY foe.strategy_name, foe.portfolio_id, foe.instrument_id
        ),
        symbol_keys AS (
            SELECT strategy_name, portfolio_id, instrument_id FROM lifecycle_stats
            UNION
            SELECT strategy_name, portfolio_id, instrument_id FROM intervention_stats
            UNION
            SELECT strategy_name, portfolio_id, instrument_id FROM reentry_stats
        )
        SELECT
            keys.strategy_name,
            keys.portfolio_id,
            COALESCE(lifecycle_stats.account_id, intervention_stats.account_id, ds.account_id) AS account_id,
            COALESCE(lifecycle_stats.tactic_id, intervention_stats.tactic_id, ds.tactic_id) AS tactic_id,
            keys.instrument_id,
            lifecycle_stats.lifecycle_date_from,
            lifecycle_stats.lifecycle_date_to,
            intervention_stats.intervention_date_from,
            intervention_stats.intervention_date_to,
            reentry_stats.reentry_date_from,
            reentry_stats.reentry_date_to,
            lifecycle_stats.total_lifecycles,
            lifecycle_stats.closed_lifecycles,
            lifecycle_stats.priced_lifecycles,
            lifecycle_stats.priced_entry_notional,
            lifecycle_stats.pnl_actual_sum,
            lifecycle_stats.pnl_raw_sum,
            lifecycle_stats.pnl_delta_sum,
            lifecycle_stats.avg_hold_minutes_actual,
            lifecycle_stats.avg_hold_minutes_raw,
            intervention_stats.tpsl_intervention_count,
            intervention_stats.positive_intervention_count,
            intervention_stats.negative_intervention_count,
            intervention_stats.still_in_target_intervention_count,
            intervention_stats.removed_from_target_intervention_count,
            intervention_stats.no_next_target_intervention_count,
            intervention_stats.protected_pnl_sum,
            intervention_stats.missed_pnl_sum,
            reentry_stats.reentry_count
        FROM symbol_keys keys
        LEFT JOIN lifecycle_stats
            ON lifecycle_stats.strategy_name = keys.strategy_name
           AND lifecycle_stats.portfolio_id = keys.portfolio_id
           AND lifecycle_stats.instrument_id = keys.instrument_id
        LEFT JOIN intervention_stats
            ON intervention_stats.strategy_name = keys.strategy_name
           AND intervention_stats.portfolio_id = keys.portfolio_id
           AND intervention_stats.instrument_id = keys.instrument_id
        LEFT JOIN reentry_stats
            ON reentry_stats.strategy_name = keys.strategy_name
           AND reentry_stats.portfolio_id = keys.portfolio_id
           AND reentry_stats.instrument_id = keys.instrument_id
        LEFT JOIN insights.dim_strategy ds
            ON ds.strategy_name = keys.strategy_name
           AND ds.portfolio_id = keys.portfolio_id
        ORDER BY keys.strategy_name ASC, keys.portfolio_id ASC, keys.instrument_id ASC
    """

    insert_query = """
        INSERT INTO insights.fact_symbol_tpsl_diagnostics (
            analysis_run_id,
            as_of_date,
            date_from,
            date_to,
            strategy_name,
            portfolio_id,
            account_id,
            tactic_id,
            instrument_id,
            total_lifecycles,
            closed_lifecycles,
            priced_lifecycles,
            priced_coverage_ratio,
            priced_entry_notional,
            pnl_actual_sum,
            pnl_raw_sum,
            pnl_delta_sum,
            return_actual_bps,
            return_raw_bps,
            delta_bps,
            tpsl_intervention_count,
            positive_intervention_count,
            negative_intervention_count,
            still_in_target_intervention_count,
            removed_from_target_intervention_count,
            no_next_target_intervention_count,
            reentry_count,
            misfire_count,
            misfire_rate,
            protected_pnl_sum,
            missed_pnl_sum,
            protection_efficiency,
            avg_hold_minutes_actual,
            avg_hold_minutes_raw,
            hold_gap_ratio,
            sample_quality_score,
            confidence_score,
            diagnosis_label,
            diagnostic_payload,
            updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
            $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
            $31, $32, $33, $34, $35, $36, $37, $38, $39::jsonb, NOW()
        )
    """

    as_of_date = date.today()
    provisional_metrics: dict[tuple[str, str, str], dict[str, float | int | str | None]] = {}
    provisional_symbol_count = 0
    if clickhouse_client is not None:
        open_raw_rows = await _fetch_open_raw_lifecycles(pool)
        open_symbols = sorted({str(row["instrument_id"]) for row in open_raw_rows})
        latest_close_map = await asyncio.to_thread(
            clickhouse_client.fetch_latest_daily_closes,
            open_symbols,
            as_of_date=as_of_date,
        )
        provisional_metrics = _build_provisional_symbol_metrics(open_raw_rows, latest_close_map)
        provisional_symbol_count = sum(
            int(item["provisional_priced_lifecycles"]) for item in provisional_metrics.values()
        )

    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
        if not rows:
            logger.warning("⚠️ 没有可用于生成标的级 TPSL 诊断的样本")
            return {
                "analysis_run_id": None,
                "symbol_count": 0,
                "rows_written": 0,
                "diagnosis_counts": {},
                "provisional_symbol_count": 0,
            }

        analysis_run_id = uuid4()
        records: list[tuple[Any, ...]] = []
        diagnosis_counts: dict[str, int] = {}

        for row in rows:
            strategy_name = str(row["strategy_name"])
            portfolio_id = str(row["portfolio_id"])
            instrument_id = str(row["instrument_id"])
            date_from, date_to = _pick_date_bounds(row, as_of_date)
            total_lifecycles = _to_int(row["total_lifecycles"])
            closed_lifecycles = _to_int(row["closed_lifecycles"])
            direct_priced_lifecycles = _to_int(row["priced_lifecycles"])
            direct_priced_entry_notional = _to_float(row["priced_entry_notional"]) or 0.0
            pnl_actual_sum = _to_float(row["pnl_actual_sum"]) or 0.0
            pnl_raw_sum = _to_float(row["pnl_raw_sum"]) or 0.0
            pnl_delta_sum = _to_float(row["pnl_delta_sum"]) or 0.0
            tpsl_intervention_count = _to_int(row["tpsl_intervention_count"])
            still_in_target_intervention_count = _to_int(row["still_in_target_intervention_count"])
            removed_from_target_intervention_count = _to_int(row["removed_from_target_intervention_count"])
            no_next_target_intervention_count = _to_int(row["no_next_target_intervention_count"])
            positive_intervention_count = _to_int(row["positive_intervention_count"])
            negative_intervention_count = _to_int(row["negative_intervention_count"])
            reentry_count = _to_int(row["reentry_count"])
            protected_pnl_sum = _to_float(row["protected_pnl_sum"]) or 0.0
            missed_pnl_sum = _to_float(row["missed_pnl_sum"]) or 0.0
            avg_hold_minutes_actual = _to_float(row["avg_hold_minutes_actual"])
            avg_hold_minutes_raw = _to_float(row["avg_hold_minutes_raw"])

            provisional_payload = provisional_metrics.get((strategy_name, portfolio_id, instrument_id), {})
            provisional_priced_lifecycles = int(provisional_payload.get("provisional_priced_lifecycles", 0) or 0)
            provisional_entry_notional = float(provisional_payload.get("provisional_entry_notional", 0.0) or 0.0)
            provisional_raw_pnl_sum = float(provisional_payload.get("provisional_raw_pnl_sum", 0.0) or 0.0)
            provisional_delta_pnl_sum = float(provisional_payload.get("provisional_delta_pnl_sum", 0.0) or 0.0)

            priced_lifecycles = direct_priced_lifecycles + provisional_priced_lifecycles
            priced_entry_notional = round(direct_priced_entry_notional + provisional_entry_notional, 6)
            pnl_raw_sum = round(pnl_raw_sum + provisional_raw_pnl_sum, 6)
            pnl_delta_sum = round(pnl_delta_sum + provisional_delta_pnl_sum, 6)

            priced_coverage_ratio = _safe_ratio(priced_lifecycles, total_lifecycles, digits=8)
            return_actual_bps = _safe_bps(pnl_actual_sum, priced_entry_notional)
            return_raw_bps = _safe_bps(pnl_raw_sum, priced_entry_notional)
            delta_bps = _safe_bps(pnl_delta_sum, priced_entry_notional)
            misfire_rate = _safe_ratio(still_in_target_intervention_count, tpsl_intervention_count, digits=8)
            protection_efficiency = _safe_ratio(
                protected_pnl_sum,
                protected_pnl_sum + missed_pnl_sum,
                digits=8,
            )
            hold_gap_ratio = None
            if avg_hold_minutes_actual is not None and avg_hold_minutes_raw not in (None, 0):
                hold_gap_ratio = round((avg_hold_minutes_actual - avg_hold_minutes_raw) / avg_hold_minutes_raw, 8)

            sample_quality_score = _calculate_sample_quality(
                priced_lifecycles=priced_lifecycles,
                tpsl_intervention_count=tpsl_intervention_count,
                priced_coverage_ratio=priced_coverage_ratio,
            )
            confidence_score = _calculate_confidence_score(
                sample_quality_score=sample_quality_score,
                date_to=date_to,
                as_of_date=as_of_date,
            )
            diagnosis_label = _build_diagnosis_label(
                priced_lifecycles=priced_lifecycles,
                tpsl_intervention_count=tpsl_intervention_count,
                delta_bps=delta_bps,
                misfire_rate=misfire_rate,
                protection_efficiency=protection_efficiency,
            )
            diagnosis_counts[diagnosis_label] = diagnosis_counts.get(diagnosis_label, 0) + 1

            diagnostic_payload = {
                "method": SYMBOL_PROXY_METHOD,
                "window": {
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "as_of_date": as_of_date.isoformat(),
                },
                "pricing": {
                    "direct_priced_lifecycles": direct_priced_lifecycles,
                    "provisional_priced_lifecycles": provisional_priced_lifecycles,
                    "latest_trade_date": provisional_payload.get("latest_trade_date"),
                },
                "metrics": {
                    "pnl_actual_sum": pnl_actual_sum,
                    "pnl_raw_sum": pnl_raw_sum,
                    "pnl_delta_sum": pnl_delta_sum,
                    "return_actual_bps": return_actual_bps,
                    "return_raw_bps": return_raw_bps,
                    "delta_bps": delta_bps,
                    "misfire_rate": misfire_rate,
                    "protection_efficiency": protection_efficiency,
                    "hold_gap_ratio": hold_gap_ratio,
                },
            }

            records.append(
                (
                    analysis_run_id,
                    as_of_date,
                    date_from,
                    date_to,
                    strategy_name,
                    portfolio_id,
                    row["account_id"],
                    row["tactic_id"],
                    instrument_id,
                    total_lifecycles,
                    closed_lifecycles,
                    priced_lifecycles,
                    priced_coverage_ratio,
                    round(priced_entry_notional, 6),
                    round(pnl_actual_sum, 6),
                    round(pnl_raw_sum, 6),
                    round(pnl_delta_sum, 6),
                    return_actual_bps,
                    return_raw_bps,
                    delta_bps,
                    tpsl_intervention_count,
                    positive_intervention_count,
                    negative_intervention_count,
                    still_in_target_intervention_count,
                    removed_from_target_intervention_count,
                    no_next_target_intervention_count,
                    reentry_count,
                    still_in_target_intervention_count,
                    misfire_rate,
                    round(protected_pnl_sum, 6),
                    round(missed_pnl_sum, 6),
                    protection_efficiency,
                    avg_hold_minutes_actual,
                    avg_hold_minutes_raw,
                    hold_gap_ratio,
                    sample_quality_score,
                    confidence_score,
                    diagnosis_label,
                    json.dumps(diagnostic_payload, ensure_ascii=False),
                )
            )

        async with conn.transaction():
            delete_status = await conn.execute("DELETE FROM insights.fact_symbol_tpsl_diagnostics")
            logger.info("🔍 已清理旧的标的级 TPSL 诊断结果 status=%s", delete_status)
            await conn.executemany(insert_query, records)

    logger.info(
        "✅ 标的级 TPSL 诊断同步完成 symbols=%s provisional_lifecycles=%s analysis_run_id=%s",
        len(records),
        provisional_symbol_count,
        analysis_run_id,
    )
    return {
        "analysis_run_id": str(analysis_run_id),
        "symbol_count": len(records),
        "rows_written": len(records),
        "diagnosis_counts": diagnosis_counts,
        "provisional_symbol_count": provisional_symbol_count,
    }


async def sync_symbol_tpsl_recommendations(pool: asyncpg.Pool) -> dict[str, Any]:
    """用途：根据标的级诊断结果生成参数建议并写入建议表。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        包含运行标识、写入行数与动作分布的统计字典。
    异常/边界：
        当前输出的是启发式建议，推荐动作与建议倍数应被视为“优先实验方向”，
        而不是可以直接替代真实回放结果的生产配置。
    """

    query = """
        SELECT
            analysis_run_id,
            as_of_date,
            date_from,
            date_to,
            strategy_name,
            portfolio_id,
            account_id,
            tactic_id,
            instrument_id,
            total_lifecycles,
            priced_lifecycles,
            priced_coverage_ratio::float8 AS priced_coverage_ratio,
            tpsl_intervention_count,
            reentry_count,
            delta_bps::float8 AS delta_bps,
            misfire_rate::float8 AS misfire_rate,
            protection_efficiency::float8 AS protection_efficiency,
            hold_gap_ratio::float8 AS hold_gap_ratio,
            confidence_score::float8 AS confidence_score,
            diagnosis_label
        FROM insights.fact_symbol_tpsl_diagnostics
        ORDER BY strategy_name ASC, portfolio_id ASC, instrument_id ASC
    """

    insert_query = """
        INSERT INTO insights.fact_symbol_tpsl_recommendation (
            recommendation_run_id,
            as_of_date,
            date_from,
            date_to,
            strategy_name,
            portfolio_id,
            account_id,
            tactic_id,
            instrument_id,
            source_method,
            based_on_analysis_run_id,
            recommended_action,
            recommended_profile,
            hard_sl_multiplier,
            break_even_trigger_multiplier,
            trailing_buffer_multiplier,
            take_profit_trigger_multiplier,
            expected_delta_bps,
            expected_misfire_rate,
            expected_protection_efficiency,
            confidence_score,
            priority_score,
            reason_summary,
            recommendation_payload,
            updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
            $21, $22, $23, $24::jsonb, NOW()
        )
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
        if not rows:
            logger.warning("⚠️ 没有可用于生成标的级 TPSL 建议的诊断结果")
            return {
                "recommendation_run_id": None,
                "rows_written": 0,
                "action_counts": {},
            }

        recommendation_run_id = uuid4()
        records: list[tuple[Any, ...]] = []
        action_counts: dict[str, int] = {}
        for row in rows:
            draft = _build_symbol_recommendation(row)
            action_counts[draft.recommended_action] = action_counts.get(draft.recommended_action, 0) + 1
            records.append(
                (
                    recommendation_run_id,
                    row["as_of_date"],
                    row["date_from"],
                    row["date_to"],
                    row["strategy_name"],
                    row["portfolio_id"],
                    row["account_id"],
                    row["tactic_id"],
                    row["instrument_id"],
                    SYMBOL_PROXY_METHOD,
                    row["analysis_run_id"],
                    draft.recommended_action,
                    draft.recommended_profile,
                    draft.hard_sl_multiplier,
                    draft.break_even_trigger_multiplier,
                    draft.trailing_buffer_multiplier,
                    draft.take_profit_trigger_multiplier,
                    draft.expected_delta_bps,
                    draft.expected_misfire_rate,
                    draft.expected_protection_efficiency,
                    row["confidence_score"],
                    draft.priority_score,
                    draft.reason_summary,
                    json.dumps(draft.payload, ensure_ascii=False),
                )
            )

        async with conn.transaction():
            delete_status = await conn.execute("DELETE FROM insights.fact_symbol_tpsl_recommendation")
            logger.info("🔍 已清理旧的标的级 TPSL 建议结果 status=%s", delete_status)
            await conn.executemany(insert_query, records)

    logger.info(
        "✅ 标的级 TPSL 建议同步完成 recommendations=%s recommendation_run_id=%s",
        len(records),
        recommendation_run_id,
    )
    return {
        "recommendation_run_id": str(recommendation_run_id),
        "rows_written": len(records),
        "action_counts": action_counts,
    }
