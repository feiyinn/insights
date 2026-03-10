from fastapi import APIRouter, Depends
import asyncpg

from ...api.dependencies import get_postgres_pool
from ...schemas.analysis import StrategyOverviewItem


router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("/strategies", response_model=list[StrategyOverviewItem])
async def get_strategy_overview(
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[StrategyOverviewItem]:
    """用途：返回概览页所需的策略聚合摘要列表。

    参数：
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        每个策略实例一条聚合摘要，已包含最新日度收益、TPSL 统计和最新批次动作计数。
    异常/边界：
        当某策略尚无日度分析数据时，收益字段允许为空，但策略维表信息仍会返回。
    """

    query = """
        WITH latest_daily AS (
            SELECT DISTINCT ON (fsd.strategy_name, fsd.portfolio_id)
                fsd.strategy_name,
                fsd.portfolio_id,
                fsd.trade_date,
                fsd.realized_pnl_actual_cum,
                fsd.realized_pnl_raw_cum,
                fsd.tpsl_net_delta,
                fsd.position_open_count
            FROM insights.fact_strategy_daily fsd
            ORDER BY fsd.strategy_name, fsd.portfolio_id, fsd.trade_date DESC
        ),
        tpsl_total AS (
            SELECT
                strategy_name,
                portfolio_id,
                ROUND(SUM(COALESCE(net_pnl_delta, 0))::numeric, 6) AS total_tpsl_net_delta,
                COUNT(*) FILTER (WHERE COALESCE(net_pnl_delta, 0) > 0)::int AS tpsl_positive_event_count,
                COUNT(*) FILTER (WHERE COALESCE(net_pnl_delta, 0) < 0)::int AS tpsl_negative_event_count
            FROM insights.fact_tpsl_intervention
            GROUP BY strategy_name, portfolio_id
        ),
        lifecycle_proxy AS (
            SELECT
                strategy_name,
                portfolio_id,
                COUNT(*)::int AS total_lifecycle_count,
                COUNT(*) FILTER (WHERE exit_price_raw IS NOT NULL)::int AS priced_lifecycle_count,
                ROUND(
                    SUM((entry_price * entry_qty)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_priced_entry_notional,
                ROUND(
                    SUM(COALESCE(pnl_actual, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_actual_sum,
                ROUND(
                    SUM(COALESCE(pnl_raw, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_raw_sum,
                ROUND(
                    SUM(COALESCE(pnl_delta, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_delta_sum
            FROM insights.fact_position_lifecycle
            GROUP BY strategy_name, portfolio_id
        ),
        daily_cost AS (
            SELECT
                strategy_name,
                portfolio_id,
                ROUND(SUM(COALESCE(turnover_actual, 0))::numeric, 8) AS turnover_actual_sum,
                ROUND(SUM(COALESCE(fee_total, 0))::numeric, 6) AS fee_total_sum,
                ROUND(SUM(COALESCE(tax_total, 0))::numeric, 6) AS tax_total_sum
            FROM insights.fact_strategy_daily
            GROUP BY strategy_name, portfolio_id
        ),
        latest_target_batch AS (
            SELECT
                strategy_name,
                MAX(batch_time_tag) AS batch_time_tag
            FROM insights.fact_strategy_target
            GROUP BY strategy_name
        ),
        latest_target_count AS (
            SELECT
                ltb.strategy_name,
                COUNT(*)::int AS latest_target_count
            FROM latest_target_batch ltb
            JOIN insights.fact_strategy_target fst
                ON fst.strategy_name = ltb.strategy_name
               AND fst.batch_time_tag = ltb.batch_time_tag
            GROUP BY ltb.strategy_name
        ),
        latest_action_batch AS (
            SELECT
                strategy_name,
                MAX(batch_time_tag) AS batch_time_tag
            FROM insights.fact_strategy_action_raw
            GROUP BY strategy_name
        ),
        latest_action_count AS (
            SELECT
                lab.strategy_name,
                COUNT(*) FILTER (WHERE fsar.action_type = 'BUY')::int AS latest_buy_count,
                COUNT(*) FILTER (WHERE fsar.action_type = 'SELL')::int AS latest_sell_count
            FROM latest_action_batch lab
            JOIN insights.fact_strategy_action_raw fsar
                ON fsar.strategy_name = lab.strategy_name
               AND fsar.batch_time_tag = lab.batch_time_tag
            GROUP BY lab.strategy_name
        )
        SELECT
            ds.strategy_name,
            ds.portfolio_id,
            ds.mode,
            ds.enabled,
            ds.account_id,
            ds.tactic_id,
            ld.trade_date AS latest_trade_date,
            ld.realized_pnl_actual_cum::float8 AS realized_pnl_actual_cum,
            ld.realized_pnl_raw_cum::float8 AS realized_pnl_raw_cum,
            lifecycle_proxy.proxy_priced_entry_notional::float8 AS proxy_priced_entry_notional,
            lifecycle_proxy.proxy_pnl_actual_sum::float8 AS proxy_pnl_actual_sum,
            lifecycle_proxy.proxy_pnl_raw_sum::float8 AS proxy_pnl_raw_sum,
            lifecycle_proxy.proxy_pnl_delta_sum::float8 AS proxy_pnl_delta_sum,
            CASE
                WHEN COALESCE(lifecycle_proxy.proxy_priced_entry_notional, 0) > 0
                    THEN ROUND(
                        (lifecycle_proxy.proxy_pnl_actual_sum / lifecycle_proxy.proxy_priced_entry_notional)::numeric,
                        8
                    )::float8
                ELSE NULL
            END AS proxy_return_actual,
            CASE
                WHEN COALESCE(lifecycle_proxy.proxy_priced_entry_notional, 0) > 0
                    THEN ROUND(
                        (lifecycle_proxy.proxy_pnl_raw_sum / lifecycle_proxy.proxy_priced_entry_notional)::numeric,
                        8
                    )::float8
                ELSE NULL
            END AS proxy_return_raw,
            CASE
                WHEN COALESCE(lifecycle_proxy.proxy_priced_entry_notional, 0) > 0
                    THEN ROUND(
                        (10000 * lifecycle_proxy.proxy_pnl_delta_sum / lifecycle_proxy.proxy_priced_entry_notional)::numeric,
                        4
                    )::float8
                ELSE NULL
            END AS proxy_delta_bps,
            CASE
                WHEN COALESCE(daily_cost.turnover_actual_sum, 0) > 0
                    THEN ROUND((10000 * daily_cost.fee_total_sum / daily_cost.turnover_actual_sum)::numeric, 4)::float8
                ELSE NULL
            END AS fee_drag_bps,
            CASE
                WHEN COALESCE(daily_cost.turnover_actual_sum, 0) > 0
                    THEN ROUND((10000 * daily_cost.tax_total_sum / daily_cost.turnover_actual_sum)::numeric, 4)::float8
                ELSE NULL
            END AS tax_drag_bps,
            CASE
                WHEN COALESCE(lifecycle_proxy.total_lifecycle_count, 0) > 0
                    THEN ROUND(
                        (lifecycle_proxy.priced_lifecycle_count::numeric / lifecycle_proxy.total_lifecycle_count)::numeric,
                        4
                    )::float8
                ELSE NULL
            END AS priced_coverage_ratio,
            COALESCE(lifecycle_proxy.priced_lifecycle_count, 0) AS priced_lifecycle_count,
            COALESCE(lifecycle_proxy.total_lifecycle_count, 0) AS total_lifecycle_count,
            ld.tpsl_net_delta::float8 AS latest_tpsl_net_delta,
            tt.total_tpsl_net_delta::float8 AS total_tpsl_net_delta,
            COALESCE(tt.tpsl_positive_event_count, 0) AS tpsl_positive_event_count,
            COALESCE(tt.tpsl_negative_event_count, 0) AS tpsl_negative_event_count,
            COALESCE(ld.position_open_count, 0) AS open_position_count,
            COALESCE(ltc.latest_target_count, 0) AS latest_target_count,
            COALESCE(lac.latest_buy_count, 0) AS latest_buy_count,
            COALESCE(lac.latest_sell_count, 0) AS latest_sell_count
        FROM insights.dim_strategy ds
        LEFT JOIN latest_daily ld
            ON ld.strategy_name = ds.strategy_name
           AND ld.portfolio_id = ds.portfolio_id
        LEFT JOIN tpsl_total tt
            ON tt.strategy_name = ds.strategy_name
           AND tt.portfolio_id = ds.portfolio_id
        LEFT JOIN lifecycle_proxy
            ON lifecycle_proxy.strategy_name = ds.strategy_name
           AND lifecycle_proxy.portfolio_id = ds.portfolio_id
        LEFT JOIN daily_cost
            ON daily_cost.strategy_name = ds.strategy_name
           AND daily_cost.portfolio_id = ds.portfolio_id
        LEFT JOIN latest_target_count ltc
            ON ltc.strategy_name = ds.strategy_name
        LEFT JOIN latest_action_count lac
            ON lac.strategy_name = ds.strategy_name
        WHERE ld.trade_date IS NOT NULL
        ORDER BY
            ds.enabled DESC,
            ld.realized_pnl_actual_cum DESC NULLS LAST,
            ds.strategy_name ASC,
            ds.portfolio_id ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return [StrategyOverviewItem.model_validate(dict(row)) for row in rows]
