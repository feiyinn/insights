from __future__ import annotations

import asyncio
import logging

from ..core.config import get_settings
from ..db.pool import close_postgres_pool, create_postgres_pool
from ..services.counterfactual_sync import sync_proxy_counterfactual_facts
from ..services.strategy_sync import create_job_run, finish_job_run


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insights.jobs.sync_counterfactual_facts")


async def run() -> None:
    """用途：生成并同步参数实验室所需的代理回放实验结果。

    参数：
        无，运行配置通过环境变量读取。
    返回值：
        无。
    异常/边界：
        当前任务基于已有的日度收益、TPSL 干预和生命周期事实生成启发式实验结果，
        不依赖额外行情回放，因此更适合作为参数实验室的首版可视化数据来源。
    """

    settings = get_settings()
    pg_pool = await create_postgres_pool(
        settings.postgres_dsn,
        min_size=settings.postgres_min_pool_size,
        max_size=settings.postgres_max_pool_size,
    )
    run_id = await create_job_run(
        pg_pool,
        job_name="sync_counterfactual_facts",
        source_system="SYSTEM",
    )
    try:
        stats = await sync_proxy_counterfactual_facts(pg_pool)
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="SUCCESS",
            rows_written=stats["rows_upserted"],
            rows_updated=0,
            details=stats,
        )
        logger.info("✅ 参数实验室代理回放结果同步完成 stats=%s", stats)
    except Exception as exc:
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="FAILED",
            rows_written=0,
            rows_updated=0,
            details={"error": str(exc)},
        )
        logger.exception("❌ 参数实验室代理回放结果同步失败")
        raise
    finally:
        await close_postgres_pool(pg_pool)


if __name__ == "__main__":
    asyncio.run(run())
