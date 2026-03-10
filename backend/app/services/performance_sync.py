from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

import asyncpg

from ..db.clickhouse_client import ClickHouseMarketClient, SHANGHAI_TZ


logger = logging.getLogger("insights.performance_sync")


async def sync_position_lifecycle_facts(pool: asyncpg.Pool) -> str:
    """用途：重建单次建仓到实际/原始退出的持仓生命周期事实。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        PostgreSQL `execute` 返回的状态字符串。
    异常/边界：
        当前版本仅依赖 PostgreSQL 中已有的真实成交、TPSL intent 与原始目标池卖出时点；
        当缺失历史行情价格时，原始退出价格与原始收益会保留为空，并将 `raw_path_status` 标记为 `ESTIMATED`。
    """

    query = """
        WITH lot_base AS (
            SELECT
                pll.lot_id,
                pll.portfolio_id,
                pll.account_id,
                sp.strategy_name,
                pll.instrument_id,
                pll.tactic_id,
                pll.open_ts,
                pll.open_price,
                pll.open_qty,
                pll.remain_qty,
                pll.realized_pnl,
                pll.closed_ts,
                pll.position_state_id,
                ps.highest_high,
                ps.lowest_low
            FROM trading.pos_position_lot pll
            LEFT JOIN trading.strategy_portfolio sp
                ON sp.portfolio_id = pll.portfolio_id
            LEFT JOIN trading.pos_tp_sl_position_state ps
                ON ps.position_state_id = pll.position_state_id
        ),
        enriched AS (
            SELECT
                lb.*,
                entry_exec.order_id AS entry_order_id,
                entry_exec.exec_id AS entry_exec_id,
                exit_fact.intent_id AS exit_intent_id_actual,
                exit_fact.parent_order_id AS exit_order_id_actual,
                exit_fact.level_type AS exit_level_type_actual,
                exit_fact.fill_ts AS exit_fill_ts_actual,
                exit_fact.fill_price AS exit_price_actual,
                exit_fact.filled_qty AS exit_qty_actual,
                exit_fact.classification AS exit_classification_actual,
                raw_exit.estimated_exit_ts AS exit_ts_raw,
                raw_exit.reason_type AS exit_reason_raw,
                raw_exit.trade_date AS raw_trade_date
            FROM lot_base lb
            LEFT JOIN LATERAL (
                SELECT
                    foe.order_id,
                    foe.exec_id
                FROM insights.fact_order_execution foe
                WHERE foe.portfolio_id = lb.portfolio_id
                  AND foe.instrument_id = lb.instrument_id
                  AND foe.source_type = 'STRAT'
                  AND foe.side = 'BUY'
                  AND foe.trade_ts BETWEEN lb.open_ts - INTERVAL '5 minutes' AND lb.open_ts + INTERVAL '5 minutes'
                ORDER BY ABS(EXTRACT(EPOCH FROM (foe.trade_ts - lb.open_ts))) ASC, foe.trade_ts ASC
                LIMIT 1
            ) entry_exec ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    fti.intent_id,
                    fti.parent_order_id,
                    fti.level_type,
                    fti.fill_ts,
                    fti.fill_price,
                    fti.filled_qty,
                    fti.classification
                FROM insights.fact_tpsl_intervention fti
                WHERE fti.position_state_id = lb.position_state_id
                ORDER BY fti.fill_ts DESC NULLS LAST, fti.trigger_ts DESC NULLS LAST
                LIMIT 1
            ) exit_fact ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    COALESCE(rebalance_exec.rebalance_exec_ts, far.batch_time_tag) AS estimated_exit_ts,
                    far.reason_type,
                    far.trade_date
                FROM insights.fact_strategy_action_raw far
                LEFT JOIN LATERAL (
                    SELECT MIN(foe.trade_ts) AS rebalance_exec_ts
                    FROM insights.fact_order_execution foe
                    WHERE foe.portfolio_id = lb.portfolio_id
                      AND foe.source_type = 'STRAT'
                      AND foe.side = 'BUY'
                      AND foe.trade_ts::date = far.batch_time_tag::date
                ) rebalance_exec ON TRUE
                WHERE far.strategy_name = lb.strategy_name
                  AND far.instrument_id = lb.instrument_id
                  AND far.action_type = 'SELL'
                  AND far.batch_time_tag > lb.open_ts
                ORDER BY far.batch_time_tag ASC
                LIMIT 1
            ) raw_exit ON TRUE
        )
        INSERT INTO insights.fact_position_lifecycle (
            portfolio_id,
            account_id,
            strategy_name,
            instrument_id,
            tactic_id,
            entry_order_id,
            entry_exec_id,
            entry_ts,
            entry_price,
            entry_qty,
            exit_ts_actual,
            exit_price_actual,
            exit_qty_actual,
            exit_reason_actual,
            exit_order_id_actual,
            exit_intent_id_actual,
            exit_ts_raw,
            exit_price_raw,
            exit_qty_raw,
            exit_reason_raw,
            holding_minutes_actual,
            holding_minutes_raw,
            pnl_actual,
            pnl_raw,
            pnl_delta,
            max_favorable_excursion,
            max_adverse_excursion,
            tpsl_intervened,
            raw_path_status,
            actual_path_status,
            metadata,
            updated_at
        )
        SELECT
            enriched.portfolio_id,
            enriched.account_id,
            enriched.strategy_name,
            enriched.instrument_id,
            enriched.tactic_id,
            enriched.entry_order_id,
            enriched.entry_exec_id,
            enriched.open_ts AS entry_ts,
            enriched.open_price AS entry_price,
            enriched.open_qty AS entry_qty,
            COALESCE(enriched.exit_fill_ts_actual, enriched.closed_ts) AS exit_ts_actual,
            enriched.exit_price_actual,
            COALESCE(
                enriched.exit_qty_actual,
                CASE
                    WHEN enriched.remain_qty = 0 THEN enriched.open_qty
                    ELSE NULL
                END
            ) AS exit_qty_actual,
            CASE
                WHEN enriched.exit_level_type_actual IS NOT NULL THEN 'TPSL_' || enriched.exit_level_type_actual
                WHEN enriched.closed_ts IS NOT NULL THEN 'LOT_CLOSED'
                ELSE NULL
            END AS exit_reason_actual,
            enriched.exit_order_id_actual,
            enriched.exit_intent_id_actual,
            enriched.exit_ts_raw,
            NULL::NUMERIC(18, 6) AS exit_price_raw,
            CASE
                WHEN enriched.exit_ts_raw IS NOT NULL THEN enriched.open_qty
                ELSE NULL
            END AS exit_qty_raw,
            enriched.exit_reason_raw,
            CASE
                WHEN COALESCE(enriched.exit_fill_ts_actual, enriched.closed_ts) IS NOT NULL
                    THEN ROUND((EXTRACT(EPOCH FROM (COALESCE(enriched.exit_fill_ts_actual, enriched.closed_ts) - enriched.open_ts)) / 60.0)::numeric, 2)
                ELSE NULL
            END AS holding_minutes_actual,
            CASE
                WHEN enriched.exit_ts_raw IS NOT NULL
                    THEN ROUND((EXTRACT(EPOCH FROM (enriched.exit_ts_raw - enriched.open_ts)) / 60.0)::numeric, 2)
                ELSE NULL
            END AS holding_minutes_raw,
            CASE
                WHEN enriched.remain_qty = 0 THEN enriched.realized_pnl
                ELSE NULL
            END AS pnl_actual,
            NULL::NUMERIC(18, 6) AS pnl_raw,
            NULL::NUMERIC(18, 6) AS pnl_delta,
            CASE
                WHEN enriched.highest_high IS NOT NULL
                    THEN ROUND(((enriched.highest_high - enriched.open_price) * enriched.open_qty)::numeric, 6)
                ELSE NULL
            END AS max_favorable_excursion,
            CASE
                WHEN enriched.lowest_low IS NOT NULL
                    THEN ROUND(((enriched.lowest_low - enriched.open_price) * enriched.open_qty)::numeric, 6)
                ELSE NULL
            END AS max_adverse_excursion,
            (enriched.exit_intent_id_actual IS NOT NULL) AS tpsl_intervened,
            CASE
                WHEN enriched.exit_ts_raw IS NOT NULL THEN 'ESTIMATED'
                ELSE 'OPEN'
            END AS raw_path_status,
            CASE
                WHEN COALESCE(enriched.exit_fill_ts_actual, enriched.closed_ts) IS NOT NULL OR enriched.remain_qty = 0
                    THEN 'CLOSED'
                ELSE 'OPEN'
            END AS actual_path_status,
            jsonb_strip_nulls(
                jsonb_build_object(
                    'lot_id', enriched.lot_id,
                    'position_state_id', enriched.position_state_id,
                    'raw_exit_trade_date', enriched.raw_trade_date,
                    'raw_price_status', CASE
                        WHEN enriched.exit_ts_raw IS NOT NULL THEN 'MISSING_PRICE_SOURCE'
                        ELSE NULL
                    END,
                    'actual_exit_classification', enriched.exit_classification_actual
                )
            ) AS metadata,
            NOW()
        FROM enriched
        ON CONFLICT (portfolio_id, instrument_id, entry_ts, entry_order_id)
        DO UPDATE SET
            account_id = EXCLUDED.account_id,
            strategy_name = EXCLUDED.strategy_name,
            tactic_id = EXCLUDED.tactic_id,
            entry_exec_id = EXCLUDED.entry_exec_id,
            entry_price = EXCLUDED.entry_price,
            entry_qty = EXCLUDED.entry_qty,
            exit_ts_actual = EXCLUDED.exit_ts_actual,
            exit_price_actual = EXCLUDED.exit_price_actual,
            exit_qty_actual = EXCLUDED.exit_qty_actual,
            exit_reason_actual = EXCLUDED.exit_reason_actual,
            exit_order_id_actual = EXCLUDED.exit_order_id_actual,
            exit_intent_id_actual = EXCLUDED.exit_intent_id_actual,
            exit_ts_raw = EXCLUDED.exit_ts_raw,
            exit_price_raw = EXCLUDED.exit_price_raw,
            exit_qty_raw = EXCLUDED.exit_qty_raw,
            exit_reason_raw = EXCLUDED.exit_reason_raw,
            holding_minutes_actual = EXCLUDED.holding_minutes_actual,
            holding_minutes_raw = EXCLUDED.holding_minutes_raw,
            pnl_actual = EXCLUDED.pnl_actual,
            pnl_raw = EXCLUDED.pnl_raw,
            pnl_delta = EXCLUDED.pnl_delta,
            max_favorable_excursion = EXCLUDED.max_favorable_excursion,
            max_adverse_excursion = EXCLUDED.max_adverse_excursion,
            tpsl_intervened = EXCLUDED.tpsl_intervened,
            raw_path_status = EXCLUDED.raw_path_status,
            actual_path_status = EXCLUDED.actual_path_status,
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM insights.fact_position_lifecycle")
            return await conn.execute(query)


async def enrich_counterfactual_prices(
    pool: asyncpg.Pool,
    *,
    clickhouse_client: ClickHouseMarketClient,
) -> dict[str, int]:
    """用途：使用历史分钟线为原始路径补价，并计算 TPSL 干预净影响。

    参数：
        pool：PostgreSQL 连接池。
        clickhouse_client：ClickHouse 历史行情客户端。
    返回值：
        包含生命周期与 TPSL 干预更新行数的统计字典。
    异常/边界：
        当 ClickHouse 缺失对应分钟线时，会保留 `ESTIMATED` 状态并跳过该记录，避免写入伪造价格。
    """

    lifecycle_rows = await _fetch_pending_raw_price_lifecycles(pool)
    if not lifecycle_rows:
        logger.info("⚠️ 未发现待补价的原始路径生命周期")
        return {"lifecycle_updates": 0, "intervention_updates": 0}

    points = [
        (str(row["instrument_id"]), row["exit_ts_raw"])
        for row in lifecycle_rows
        if row["exit_ts_raw"] is not None
    ]
    price_map = await asyncio.to_thread(clickhouse_client.fetch_minute_bars_for_points, points)

    lifecycle_updates: list[tuple[Any, ...]] = []
    intervention_updates: list[tuple[Any, ...]] = []
    for row in lifecycle_rows:
        exit_ts_raw = row["exit_ts_raw"]
        if exit_ts_raw is None:
            continue

        local_lookup_minute = exit_ts_raw.astimezone(SHANGHAI_TZ).replace(second=0, microsecond=0)
        bar = price_map.get((str(row["instrument_id"]), local_lookup_minute))
        if bar is None:
            continue

        entry_price = Decimal(str(row["entry_price"]))
        entry_qty = int(row["entry_qty"])
        exit_price_raw = bar.estimated_price
        pnl_raw = (exit_price_raw - entry_price) * entry_qty

        pnl_actual_value = row["pnl_actual"]
        pnl_actual = Decimal(str(pnl_actual_value)) if pnl_actual_value is not None else None
        pnl_delta = pnl_actual - pnl_raw if pnl_actual is not None else None
        raw_path_status = "CLOSED"
        metadata_value = row["metadata"] or {}
        if isinstance(metadata_value, str):
            metadata = json.loads(metadata_value)
        else:
            metadata = dict(metadata_value)
        metadata.update(
            {
                "raw_price_status": "PRICED",
                "raw_price_source": "cnstock.kline_1m.vwap_or_open",
                "raw_price_bar_time": bar.bar_time.isoformat(),
            }
        )

        lifecycle_updates.append(
            (
                exit_price_raw,
                pnl_raw,
                pnl_delta,
                raw_path_status,
                json.dumps(metadata, ensure_ascii=False),
                int(row["lifecycle_id"]),
            )
        )

        intent_id = row["exit_intent_id_actual"]
        if intent_id is not None and row["exit_price_actual"] is not None:
            actual_exit_price = Decimal(str(row["exit_price_actual"]))
            qty = int(row["exit_qty_actual"] or entry_qty)
            net_pnl_delta = (actual_exit_price - exit_price_raw) * qty
            protected_pnl = net_pnl_delta if net_pnl_delta > 0 else Decimal("0")
            missed_pnl = abs(net_pnl_delta) if net_pnl_delta < 0 else Decimal("0")
            intervention_updates.append(
                (
                    protected_pnl,
                    missed_pnl,
                    net_pnl_delta,
                    intent_id,
                )
            )

    if not lifecycle_updates:
        logger.info("⚠️ ClickHouse 未命中可用于补价的分钟线")
        return {"lifecycle_updates": 0, "intervention_updates": 0}

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                UPDATE insights.fact_position_lifecycle
                SET exit_price_raw = $1,
                    pnl_raw = $2,
                    pnl_delta = $3,
                    raw_path_status = $4,
                    metadata = $5::jsonb,
                    updated_at = NOW()
                WHERE lifecycle_id = $6
                """,
                lifecycle_updates,
            )
            if intervention_updates:
                await conn.executemany(
                    """
                    UPDATE insights.fact_tpsl_intervention
                    SET protected_pnl = $1,
                        missed_pnl = $2,
                        net_pnl_delta = $3,
                        updated_at = NOW()
                    WHERE intent_id = $4
                    """,
                    intervention_updates,
                )

    logger.info(
        "✅ 反事实补价完成 lifecycle_updates=%s intervention_updates=%s",
        len(lifecycle_updates),
        len(intervention_updates),
    )
    return {
        "lifecycle_updates": len(lifecycle_updates),
        "intervention_updates": len(intervention_updates),
    }


async def sync_strategy_daily_facts(pool: asyncpg.Pool) -> str:
    """用途：按交易日汇总策略执行、TPSL 干预与生命周期统计。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        PostgreSQL `execute` 返回的状态字符串。
    异常/边界：
        由于当前缺少统一的历史净值快照与原始路径估值价格，本版本优先落地已实现收益、换手、费用与干预计数；
        `nav_*`、`return_*` 与 `drawdown_*` 暂保留为空，等待后续接入历史行情回放后补齐。
    """

    query = """
        WITH portfolio_anchor AS (
            SELECT
                ds.strategy_name,
                ds.portfolio_id,
                ds.account_id,
                MIN(activity.trade_date) AS anchor_trade_date
            FROM insights.dim_strategy ds
            JOIN (
                SELECT strategy_name, portfolio_id, trade_ts::date AS trade_date
                FROM insights.fact_order_execution
                WHERE trade_ts IS NOT NULL
                UNION ALL
                SELECT strategy_name, portfolio_id, entry_ts::date AS trade_date
                FROM insights.fact_position_lifecycle
            ) activity
                ON activity.strategy_name = ds.strategy_name
               AND activity.portfolio_id = ds.portfolio_id
            GROUP BY ds.strategy_name, ds.portfolio_id, ds.account_id
        ),
        trade_calendar AS (
            SELECT DISTINCT
                anchor.strategy_name,
                anchor.portfolio_id,
                anchor.account_id,
                dates.trade_date
            FROM portfolio_anchor anchor
            JOIN (
                SELECT strategy_name, portfolio_id, trade_ts::date AS trade_date
                FROM insights.fact_order_execution
                WHERE trade_ts IS NOT NULL
                UNION
                SELECT strategy_name, portfolio_id, entry_ts::date AS trade_date
                FROM insights.fact_position_lifecycle
                UNION
                SELECT strategy_name, portfolio_id, exit_ts_actual::date AS trade_date
                FROM insights.fact_position_lifecycle
                WHERE exit_ts_actual IS NOT NULL
                UNION
                SELECT strategy_name, portfolio_id, exit_ts_raw::date AS trade_date
                FROM insights.fact_position_lifecycle
                WHERE exit_ts_raw IS NOT NULL
                UNION
                SELECT strategy_name, portfolio_id, trade_date
                FROM insights.fact_strategy_target
            ) dates
                ON dates.strategy_name = anchor.strategy_name
               AND (dates.portfolio_id = anchor.portfolio_id OR dates.portfolio_id IS NULL)
               AND dates.trade_date >= anchor.anchor_trade_date
        ),
        execution_daily AS (
            SELECT
                strategy_name,
                portfolio_id,
                trade_ts::date AS trade_date,
                ROUND(SUM(COALESCE(avg_price, order_price, 0) * COALESCE(filled_qty, qty, 0))::numeric, 8) AS turnover_actual,
                ROUND(SUM(COALESCE(fee, 0))::numeric, 6) AS fee_total,
                ROUND(SUM(COALESCE(tax, 0))::numeric, 6) AS tax_total
            FROM insights.fact_order_execution
            WHERE trade_ts IS NOT NULL
            GROUP BY strategy_name, portfolio_id, trade_ts::date
        ),
        reentry_daily AS (
            SELECT
                foe.strategy_name,
                foe.portfolio_id,
                foe.trade_ts::date AS trade_date,
                COUNT(*)::INTEGER AS tpsl_reentry_count
            FROM insights.fact_order_execution foe
            WHERE foe.source_type = 'STRAT'
              AND foe.side = 'BUY'
              AND EXISTS (
                  SELECT 1
                  FROM insights.fact_tpsl_intervention fti
                  WHERE fti.portfolio_id = foe.portfolio_id
                    AND fti.instrument_id = foe.instrument_id
                    AND fti.fill_ts IS NOT NULL
                    AND fti.fill_ts < foe.trade_ts
              )
            GROUP BY foe.strategy_name, foe.portfolio_id, foe.trade_ts::date
        ),
        tpsl_daily AS (
            SELECT
                strategy_name,
                portfolio_id,
                fill_ts::date AS trade_date,
                COUNT(*)::INTEGER AS tpsl_exit_count
            FROM insights.fact_tpsl_intervention
            WHERE fill_ts IS NOT NULL
            GROUP BY strategy_name, portfolio_id, fill_ts::date
        ),
        tpsl_delta_daily AS (
            SELECT
                strategy_name,
                portfolio_id,
                fill_ts::date AS trade_date,
                ROUND(SUM(COALESCE(protected_pnl, 0))::numeric, 6) AS tpsl_positive_delta,
                ROUND(SUM(COALESCE(missed_pnl, 0))::numeric, 6) AS tpsl_negative_delta,
                ROUND(SUM(COALESCE(net_pnl_delta, 0))::numeric, 6) AS tpsl_net_delta
            FROM insights.fact_tpsl_intervention
            WHERE fill_ts IS NOT NULL
            GROUP BY strategy_name, portfolio_id, fill_ts::date
        ),
        lifecycle_close_daily AS (
            SELECT
                strategy_name,
                portfolio_id,
                exit_ts_actual::date AS trade_date,
                COUNT(*)::INTEGER AS position_closed_count,
                ROUND(SUM(COALESCE(pnl_actual, 0))::numeric, 6) AS realized_pnl_actual_daily
            FROM insights.fact_position_lifecycle
            WHERE exit_ts_actual IS NOT NULL
            GROUP BY strategy_name, portfolio_id, exit_ts_actual::date
        ),
        lifecycle_raw_daily AS (
            SELECT
                strategy_name,
                portfolio_id,
                exit_ts_raw::date AS trade_date,
                COUNT(*) FILTER (WHERE raw_path_status = 'ESTIMATED')::INTEGER AS raw_exit_estimated_count,
                ROUND(SUM(COALESCE(pnl_raw, 0))::numeric, 6) AS realized_pnl_raw_daily
            FROM insights.fact_position_lifecycle
            WHERE exit_ts_raw IS NOT NULL
            GROUP BY strategy_name, portfolio_id, exit_ts_raw::date
        ),
        open_position_daily AS (
            SELECT
                calendar.strategy_name,
                calendar.portfolio_id,
                calendar.trade_date,
                COUNT(*)::INTEGER AS position_open_count
            FROM trade_calendar calendar
            JOIN insights.fact_position_lifecycle fpl
                ON fpl.strategy_name = calendar.strategy_name
               AND fpl.portfolio_id = calendar.portfolio_id
               AND fpl.entry_ts::date <= calendar.trade_date
               AND (
                   fpl.exit_ts_actual IS NULL
                   OR fpl.exit_ts_actual::date > calendar.trade_date
               )
            GROUP BY calendar.strategy_name, calendar.portfolio_id, calendar.trade_date
        ),
        base AS (
            SELECT
                calendar.trade_date,
                calendar.strategy_name,
                calendar.portfolio_id,
                calendar.account_id,
                NULL::NUMERIC(18, 6) AS nav_actual,
                NULL::NUMERIC(18, 6) AS nav_raw,
                NULL::NUMERIC(18, 8) AS daily_return_actual,
                NULL::NUMERIC(18, 8) AS daily_return_raw,
                NULL::NUMERIC(18, 8) AS cum_return_actual,
                NULL::NUMERIC(18, 8) AS cum_return_raw,
                NULL::NUMERIC(18, 8) AS drawdown_actual,
                NULL::NUMERIC(18, 8) AS drawdown_raw,
                execution_daily.turnover_actual,
                NULL::NUMERIC(18, 8) AS turnover_raw,
                COALESCE(tpsl_daily.tpsl_exit_count, 0) AS tpsl_exit_count,
                COALESCE(reentry_daily.tpsl_reentry_count, 0) AS tpsl_reentry_count,
                COALESCE(tpsl_delta_daily.tpsl_positive_delta, 0) AS tpsl_positive_delta,
                COALESCE(tpsl_delta_daily.tpsl_negative_delta, 0) AS tpsl_negative_delta,
                COALESCE(tpsl_delta_daily.tpsl_net_delta, 0) AS tpsl_net_delta,
                COALESCE(execution_daily.fee_total, 0) AS fee_total,
                COALESCE(execution_daily.tax_total, 0) AS tax_total,
                COALESCE(lifecycle_close_daily.realized_pnl_actual_daily, 0) AS realized_pnl_actual_daily,
                COALESCE(lifecycle_raw_daily.realized_pnl_raw_daily, 0) AS realized_pnl_raw_daily,
                COALESCE(open_position_daily.position_open_count, 0) AS position_open_count,
                COALESCE(lifecycle_close_daily.position_closed_count, 0) AS position_closed_count,
                COALESCE(lifecycle_raw_daily.raw_exit_estimated_count, 0) AS raw_exit_estimated_count,
                jsonb_strip_nulls(
                    jsonb_build_object(
                        'nav_status', 'PENDING_MARK_TO_MARKET',
                        'raw_pricing_status', CASE
                            WHEN COALESCE(lifecycle_raw_daily.raw_exit_estimated_count, 0) > 0 THEN 'MISSING_PRICE_SOURCE'
                            ELSE NULL
                        END
                    )
                ) AS notes
            FROM trade_calendar calendar
            LEFT JOIN execution_daily
                ON execution_daily.strategy_name = calendar.strategy_name
               AND execution_daily.portfolio_id = calendar.portfolio_id
               AND execution_daily.trade_date = calendar.trade_date
            LEFT JOIN reentry_daily
                ON reentry_daily.strategy_name = calendar.strategy_name
               AND reentry_daily.portfolio_id = calendar.portfolio_id
               AND reentry_daily.trade_date = calendar.trade_date
            LEFT JOIN tpsl_daily
                ON tpsl_daily.strategy_name = calendar.strategy_name
               AND tpsl_daily.portfolio_id = calendar.portfolio_id
               AND tpsl_daily.trade_date = calendar.trade_date
            LEFT JOIN tpsl_delta_daily
                ON tpsl_delta_daily.strategy_name = calendar.strategy_name
               AND tpsl_delta_daily.portfolio_id = calendar.portfolio_id
               AND tpsl_delta_daily.trade_date = calendar.trade_date
            LEFT JOIN lifecycle_close_daily
                ON lifecycle_close_daily.strategy_name = calendar.strategy_name
               AND lifecycle_close_daily.portfolio_id = calendar.portfolio_id
               AND lifecycle_close_daily.trade_date = calendar.trade_date
            LEFT JOIN lifecycle_raw_daily
                ON lifecycle_raw_daily.strategy_name = calendar.strategy_name
               AND lifecycle_raw_daily.portfolio_id = calendar.portfolio_id
               AND lifecycle_raw_daily.trade_date = calendar.trade_date
            LEFT JOIN open_position_daily
                ON open_position_daily.strategy_name = calendar.strategy_name
               AND open_position_daily.portfolio_id = calendar.portfolio_id
               AND open_position_daily.trade_date = calendar.trade_date
        ),
        final AS (
            SELECT
                base.*,
                ROUND(
                    SUM(base.realized_pnl_actual_daily) OVER (
                        PARTITION BY base.strategy_name, base.portfolio_id
                        ORDER BY base.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                ) AS realized_pnl_actual_cum,
                ROUND(
                    SUM(base.realized_pnl_raw_daily) OVER (
                        PARTITION BY base.strategy_name, base.portfolio_id
                        ORDER BY base.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                ) AS realized_pnl_raw_cum
            FROM base
        )
        INSERT INTO insights.fact_strategy_daily (
            trade_date,
            strategy_name,
            portfolio_id,
            account_id,
            nav_actual,
            nav_raw,
            daily_return_actual,
            daily_return_raw,
            cum_return_actual,
            cum_return_raw,
            drawdown_actual,
            drawdown_raw,
            turnover_actual,
            turnover_raw,
            tpsl_exit_count,
            tpsl_reentry_count,
            tpsl_positive_delta,
            tpsl_negative_delta,
            tpsl_net_delta,
            fee_total,
            tax_total,
            notes,
            realized_pnl_actual_daily,
            realized_pnl_raw_daily,
            realized_pnl_actual_cum,
            realized_pnl_raw_cum,
            position_open_count,
            position_closed_count,
            raw_exit_estimated_count,
            updated_at
        )
        SELECT
            trade_date,
            strategy_name,
            portfolio_id,
            account_id,
            nav_actual,
            nav_raw,
            daily_return_actual,
            daily_return_raw,
            cum_return_actual,
            cum_return_raw,
            drawdown_actual,
            drawdown_raw,
            turnover_actual,
            turnover_raw,
            tpsl_exit_count,
            tpsl_reentry_count,
            tpsl_positive_delta,
            tpsl_negative_delta,
            tpsl_net_delta,
            fee_total,
            tax_total,
            notes,
            realized_pnl_actual_daily,
            realized_pnl_raw_daily,
            realized_pnl_actual_cum,
            realized_pnl_raw_cum,
            position_open_count,
            position_closed_count,
            raw_exit_estimated_count,
            NOW()
        FROM final
        ON CONFLICT (strategy_name, portfolio_id, trade_date)
        DO UPDATE SET
            account_id = EXCLUDED.account_id,
            nav_actual = EXCLUDED.nav_actual,
            nav_raw = EXCLUDED.nav_raw,
            daily_return_actual = EXCLUDED.daily_return_actual,
            daily_return_raw = EXCLUDED.daily_return_raw,
            cum_return_actual = EXCLUDED.cum_return_actual,
            cum_return_raw = EXCLUDED.cum_return_raw,
            drawdown_actual = EXCLUDED.drawdown_actual,
            drawdown_raw = EXCLUDED.drawdown_raw,
            turnover_actual = EXCLUDED.turnover_actual,
            turnover_raw = EXCLUDED.turnover_raw,
            tpsl_exit_count = EXCLUDED.tpsl_exit_count,
            tpsl_reentry_count = EXCLUDED.tpsl_reentry_count,
            tpsl_positive_delta = EXCLUDED.tpsl_positive_delta,
            tpsl_negative_delta = EXCLUDED.tpsl_negative_delta,
            tpsl_net_delta = EXCLUDED.tpsl_net_delta,
            fee_total = EXCLUDED.fee_total,
            tax_total = EXCLUDED.tax_total,
            notes = EXCLUDED.notes,
            realized_pnl_actual_daily = EXCLUDED.realized_pnl_actual_daily,
            realized_pnl_raw_daily = EXCLUDED.realized_pnl_raw_daily,
            realized_pnl_actual_cum = EXCLUDED.realized_pnl_actual_cum,
            realized_pnl_raw_cum = EXCLUDED.realized_pnl_raw_cum,
            position_open_count = EXCLUDED.position_open_count,
            position_closed_count = EXCLUDED.position_closed_count,
            raw_exit_estimated_count = EXCLUDED.raw_exit_estimated_count,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM insights.fact_strategy_daily")
            return await conn.execute(query)


async def _fetch_pending_raw_price_lifecycles(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """用途：读取待使用历史行情补价的生命周期记录。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        生命周期记录列表，包含原始退出时间、进出场价格和对应 intent。
    异常/边界：
        当前仅抓取 `exit_ts_raw` 不为空的记录；已经补过价的记录也会重新计算，以便支持幂等重跑。
    """

    query = """
        SELECT
            lifecycle_id,
            strategy_name,
            portfolio_id,
            instrument_id,
            entry_price,
            entry_qty,
            exit_ts_raw,
            exit_price_actual,
            exit_qty_actual,
            exit_intent_id_actual,
            pnl_actual,
            metadata
        FROM insights.fact_position_lifecycle
        WHERE exit_ts_raw IS NOT NULL
        ORDER BY exit_ts_raw ASC, instrument_id ASC
    """
    async with pool.acquire() as conn:
        return await conn.fetch(query)
