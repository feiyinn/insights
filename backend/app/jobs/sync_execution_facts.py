from __future__ import annotations

import asyncio
import logging

from ..core.config import get_settings
from ..db.pool import close_postgres_pool, create_postgres_pool
from ..services.execution_sync import sync_order_execution_facts, sync_tpsl_intervention_facts
from ..services.strategy_sync import create_job_run, finish_job_run


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insights.jobs.sync_execution_facts")


async def run() -> None:
    """用途：执行真实成交与 TPSL 干预事实同步任务。

    参数：
        无，配置通过环境变量读取。
    返回值：
        无。
    异常/边界：
        当 PostgreSQL 连接失败时任务会直接终止，并在任务记录中标记失败。
    """

    settings = get_settings()
    pg_pool = await create_postgres_pool(
        settings.postgres_dsn,
        min_size=settings.postgres_min_pool_size,
        max_size=settings.postgres_max_pool_size,
    )
    run_id = await create_job_run(
        pg_pool,
        job_name="sync_execution_facts",
        source_system="POSTGRES",
    )
    try:
        order_status = await sync_order_execution_facts(pg_pool)
        intervention_status = await sync_tpsl_intervention_facts(pg_pool)
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="SUCCESS",
            rows_written=0,
            rows_updated=0,
            details={
                "fact_order_execution": order_status,
                "fact_tpsl_intervention": intervention_status,
            },
        )
        logger.info("✅ 执行事实同步完成 order=%s intervention=%s", order_status, intervention_status)
    except Exception as exc:
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="FAILED",
            rows_written=0,
            rows_updated=0,
            details={"error": str(exc)},
        )
        logger.exception("❌ 执行事实同步失败")
        raise
    finally:
        await close_postgres_pool(pg_pool)


if __name__ == "__main__":
    asyncio.run(run())
