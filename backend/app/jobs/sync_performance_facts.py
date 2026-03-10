from __future__ import annotations

import asyncio
import logging

from ..core.config import get_settings
from ..db.clickhouse_client import ClickHouseMarketClient
from ..db.pool import close_postgres_pool, create_postgres_pool
from ..services.performance_sync import (
    enrich_counterfactual_prices,
    sync_position_lifecycle_facts,
    sync_strategy_daily_facts,
)
from ..services.strategy_sync import create_job_run, finish_job_run


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insights.jobs.sync_performance_facts")


async def run() -> None:
    """用途：执行持仓生命周期与策略日度分析事实同步任务。

    参数：
        无，配置通过环境变量读取。
    返回值：
        无。
    异常/边界：
        当前任务依赖前序的目标池同步与执行事实同步；若上游数据缺失，会生成部分为空的分析结果，但任务仍可正常完成。
    """

    settings = get_settings()
    clickhouse_client: ClickHouseMarketClient | None = None
    pg_pool = await create_postgres_pool(
        settings.postgres_dsn,
        min_size=settings.postgres_min_pool_size,
        max_size=settings.postgres_max_pool_size,
    )
    run_id = await create_job_run(
        pg_pool,
        job_name="sync_performance_facts",
        source_system="SYSTEM",
    )
    try:
        lifecycle_status = await sync_position_lifecycle_facts(pg_pool)
        pricing_stats: dict[str, int] | None = None
        if settings.clickhouse_enabled:
            clickhouse_client = ClickHouseMarketClient(
                host=str(settings.clickhouse_host),
                port=settings.clickhouse_port,
                username=str(settings.clickhouse_user),
                password=settings.clickhouse_password,
                database=settings.clickhouse_database,
                secure=settings.clickhouse_secure,
            )
            await asyncio.to_thread(clickhouse_client.ping)
            pricing_stats = await enrich_counterfactual_prices(
                pg_pool,
                clickhouse_client=clickhouse_client,
            )
        else:
            logger.warning("⚠️ 未提供 ClickHouse 配置，跳过原始路径补价")
        daily_status = await sync_strategy_daily_facts(pg_pool)
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="SUCCESS",
            rows_written=0,
            rows_updated=0,
            details={
                "fact_position_lifecycle": lifecycle_status,
                "counterfactual_pricing": pricing_stats,
                "fact_strategy_daily": daily_status,
            },
        )
        logger.info(
            "✅ 绩效分析事实同步完成 lifecycle=%s daily=%s pricing=%s",
            lifecycle_status,
            daily_status,
            pricing_stats,
        )
    except Exception as exc:
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="FAILED",
            rows_written=0,
            rows_updated=0,
            details={"error": str(exc)},
        )
        logger.exception("❌ 绩效分析事实同步失败")
        raise
    finally:
        if clickhouse_client is not None:
            clickhouse_client.close()
        await close_postgres_pool(pg_pool)


if __name__ == "__main__":
    asyncio.run(run())
