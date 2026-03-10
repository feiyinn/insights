from __future__ import annotations

import logging

import asyncpg


logger = logging.getLogger("insights.execution_sync")


async def sync_order_execution_facts(pool: asyncpg.Pool) -> str:
    """用途：将真实订单与成交事实同步到 `insights.fact_order_execution`。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        PostgreSQL `execute` 返回的状态字符串。
    异常/边界：
        当前只同步已有成交回报的订单；未成交订单暂不进入该表，避免影响后续收益口径。
    """

    query = """
        INSERT INTO insights.fact_order_execution (
            order_id,
            exec_id,
            portfolio_id,
            account_id,
            strategy_name,
            instrument_id,
            trade_ts,
            order_created_at,
            order_updated_at,
            side,
            qty,
            filled_qty,
            order_price,
            avg_price,
            fee,
            tax,
            source_type,
            tactic_id,
            client_order_id,
            parent_intent_id,
            level_type,
            level_index,
            metadata,
            created_at,
            updated_at
        )
        SELECT
            o.order_id,
            f.exec_id,
            o.portfolio_id,
            o.account_id,
            sp.strategy_name,
            o.instrument_id,
            f.trade_ts,
            o.created_at,
            o.updated_at,
            o.side,
            o.qty,
            o.filled_qty,
            o.price,
            COALESCE(NULLIF(o.avg_price, 0), f.price) AS avg_price,
            COALESCE(f.fee, 0) AS fee,
            COALESCE(f.tax, 0) AS tax,
            CASE
                WHEN split_part(COALESCE(o.client_order_id, ''), '|', 1) IN ('STRAT', 'TPSL')
                    THEN split_part(COALESCE(o.client_order_id, ''), '|', 1)
                ELSE 'OTHER'
            END AS source_type,
            COALESCE(
                ti.tactic_id,
                (regexp_match(COALESCE(o.client_order_id, ''), 'TID=([^|]+)'))[1]
            ) AS tactic_id,
            o.client_order_id,
            ti.intent_id,
            ti.level_type,
            ti.level_index,
            jsonb_strip_nulls(
                jsonb_build_object(
                    'order_status', o.status,
                    'venue', f.venue,
                    'recv_ts', f.recv_ts,
                    'intent_status', ti.status
                )
            ) AS metadata,
            NOW(),
            NOW()
        FROM trading.ord_order o
        JOIN trading.exec_fill f
            ON f.order_id = o.order_id
        LEFT JOIN trading.strategy_portfolio sp
            ON sp.portfolio_id = o.portfolio_id
        LEFT JOIN trading.pos_tp_sl_exit_intent ti
            ON ti.parent_order_id = o.order_id
        ON CONFLICT (order_id, exec_id)
        DO UPDATE SET
            portfolio_id = EXCLUDED.portfolio_id,
            account_id = EXCLUDED.account_id,
            strategy_name = EXCLUDED.strategy_name,
            instrument_id = EXCLUDED.instrument_id,
            trade_ts = EXCLUDED.trade_ts,
            order_created_at = EXCLUDED.order_created_at,
            order_updated_at = EXCLUDED.order_updated_at,
            side = EXCLUDED.side,
            qty = EXCLUDED.qty,
            filled_qty = EXCLUDED.filled_qty,
            order_price = EXCLUDED.order_price,
            avg_price = EXCLUDED.avg_price,
            fee = EXCLUDED.fee,
            tax = EXCLUDED.tax,
            source_type = EXCLUDED.source_type,
            tactic_id = EXCLUDED.tactic_id,
            client_order_id = EXCLUDED.client_order_id,
            parent_intent_id = EXCLUDED.parent_intent_id,
            level_type = EXCLUDED.level_type,
            level_index = EXCLUDED.level_index,
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        return await conn.execute(query)


async def sync_tpsl_intervention_facts(pool: asyncpg.Pool) -> str:
    """用途：将 TPSL intent 与下一次原始目标池关系同步到 `insights.fact_tpsl_intervention`。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        PostgreSQL `execute` 返回的状态字符串。
    异常/边界：
        当某个组合尚未映射到策略名或尚无下一批目标池时，会保留空值并标记为 `UNKNOWN` 或 `INTRADAY_EXIT_NO_NEXT_TARGET`。
    """

    query = """
        WITH intent_base AS (
            SELECT
                i.intent_id,
                i.parent_order_id,
                i.portfolio_id,
                i.account_id,
                sp.strategy_name,
                i.instrument_id,
                i.position_state_id,
                i.tactic_id,
                i.level_type,
                i.level_index,
                i.created_ts AS trigger_ts,
                i.updated_ts AS fill_ts,
                i.filled_qty,
                i.avg_fill_price AS fill_price,
                i.status,
                i.reason AS trigger_reason
            FROM trading.pos_tp_sl_exit_intent i
            LEFT JOIN trading.strategy_portfolio sp
                ON sp.portfolio_id = i.portfolio_id
        ),
        next_batch AS (
            SELECT
                ib.*,
                (
                    SELECT MIN(ft.batch_time_tag)
                    FROM insights.fact_strategy_target ft
                    WHERE ft.strategy_name = ib.strategy_name
                      AND ft.batch_time_tag > ib.trigger_ts
                ) AS next_batch_time_tag
            FROM intent_base ib
        ),
        next_target AS (
            SELECT
                nb.*,
                (
                    SELECT MIN(ft.trade_date)
                    FROM insights.fact_strategy_target ft
                    WHERE ft.strategy_name = nb.strategy_name
                      AND ft.batch_time_tag = nb.next_batch_time_tag
                ) AS next_rebalance_trade_date,
                EXISTS (
                    SELECT 1
                    FROM insights.fact_strategy_target ft
                    WHERE ft.strategy_name = nb.strategy_name
                      AND ft.batch_time_tag = nb.next_batch_time_tag
                      AND ft.instrument_id = nb.instrument_id
                ) AS next_target_still_holding
            FROM next_batch nb
        )
        INSERT INTO insights.fact_tpsl_intervention (
            intent_id,
            parent_order_id,
            portfolio_id,
            account_id,
            strategy_name,
            instrument_id,
            position_state_id,
            tactic_id,
            level_type,
            level_index,
            trigger_ts,
            fill_ts,
            filled_qty,
            fill_price,
            status,
            trigger_reason,
            next_rebalance_trade_date,
            next_batch_time_tag,
            next_target_still_holding,
            classification,
            metadata,
            created_at,
            updated_at
        )
        SELECT
            nt.intent_id,
            nt.parent_order_id,
            nt.portfolio_id,
            nt.account_id,
            nt.strategy_name,
            nt.instrument_id,
            nt.position_state_id,
            nt.tactic_id,
            nt.level_type,
            nt.level_index,
            nt.trigger_ts,
            nt.fill_ts,
            nt.filled_qty,
            nt.fill_price,
            nt.status,
            nt.trigger_reason,
            nt.next_rebalance_trade_date,
            nt.next_batch_time_tag,
            CASE
                WHEN nt.next_batch_time_tag IS NULL THEN NULL
                ELSE nt.next_target_still_holding
            END AS next_target_still_holding,
            CASE
                WHEN nt.next_batch_time_tag IS NULL THEN 'INTRADAY_EXIT_NO_NEXT_TARGET'
                WHEN nt.next_target_still_holding THEN 'PRE_REBALANCE_EXIT_STILL_IN_TARGET'
                ELSE 'PRE_REBALANCE_EXIT_REMOVED_FROM_TARGET'
            END AS classification,
            jsonb_strip_nulls(
                jsonb_build_object(
                    'intent_status', nt.status,
                    'level_type', nt.level_type,
                    'level_index', nt.level_index
                )
            ) AS metadata,
            NOW(),
            NOW()
        FROM next_target nt
        ON CONFLICT (intent_id)
        DO UPDATE SET
            parent_order_id = EXCLUDED.parent_order_id,
            portfolio_id = EXCLUDED.portfolio_id,
            account_id = EXCLUDED.account_id,
            strategy_name = EXCLUDED.strategy_name,
            instrument_id = EXCLUDED.instrument_id,
            position_state_id = EXCLUDED.position_state_id,
            tactic_id = EXCLUDED.tactic_id,
            level_type = EXCLUDED.level_type,
            level_index = EXCLUDED.level_index,
            trigger_ts = EXCLUDED.trigger_ts,
            fill_ts = EXCLUDED.fill_ts,
            filled_qty = EXCLUDED.filled_qty,
            fill_price = EXCLUDED.fill_price,
            status = EXCLUDED.status,
            trigger_reason = EXCLUDED.trigger_reason,
            next_rebalance_trade_date = EXCLUDED.next_rebalance_trade_date,
            next_batch_time_tag = EXCLUDED.next_batch_time_tag,
            next_target_still_holding = EXCLUDED.next_target_still_holding,
            classification = EXCLUDED.classification,
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        return await conn.execute(query)

