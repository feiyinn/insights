from __future__ import annotations

import asyncio
import logging

from ..core.config import get_settings
from ..db.clickhouse_client import ClickHouseMarketClient
from ..db.pool import close_postgres_pool, create_postgres_pool
from ..services.strategy_sync import create_job_run, finish_job_run
from ..services.symbol_tpsl_sync import (
    sync_symbol_tpsl_diagnostics,
    sync_symbol_tpsl_recommendations,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insights.jobs.sync_symbol_tpsl_facts")


async def run() -> None:
    """用途：同步标的级 TPSL 诊断与参数建议事实。

    参数：
        无，配置通过环境变量读取。
    返回值：
        无。
    异常/边界：
        该任务依赖生命周期、TPSL 干预与执行事实已完成同步；若上游样本不足，
        任务仍会正常完成，但可能仅产出少量 `LOW_SAMPLE` 结果。
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
        job_name="sync_symbol_tpsl_facts",
        source_system="SYSTEM",
    )
    try:
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
        else:
            logger.warning("⚠️ 未提供 ClickHouse 配置，标的级诊断将跳过临时盯市补价")

        diagnostic_stats = await sync_symbol_tpsl_diagnostics(
            pg_pool,
            clickhouse_client=clickhouse_client,
        )
        recommendation_stats = await sync_symbol_tpsl_recommendations(pg_pool)
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="SUCCESS",
            rows_written=diagnostic_stats["rows_written"] + recommendation_stats["rows_written"],
            rows_updated=0,
            details={
                "fact_symbol_tpsl_diagnostics": diagnostic_stats,
                "fact_symbol_tpsl_recommendation": recommendation_stats,
            },
        )
        logger.info(
            "✅ 标的级 TPSL 参数实验室事实同步完成 diagnostics=%s recommendations=%s",
            diagnostic_stats,
            recommendation_stats,
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
        logger.exception("❌ 标的级 TPSL 参数实验室事实同步失败")
        raise
    finally:
        if clickhouse_client is not None:
            clickhouse_client.close()
        await close_postgres_pool(pg_pool)


if __name__ == "__main__":
    asyncio.run(run())
