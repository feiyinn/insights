from __future__ import annotations

import asyncio
import logging

from ..core.config import get_settings
from ..db.pool import close_postgres_pool, create_postgres_pool
from ..services.strategy_sync import create_job_run, finish_job_run, sync_strategy_targets_and_actions


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insights.jobs.sync_strategy_data")


async def run() -> None:
    """用途：执行目标池同步与原始动作重建任务。

    参数：
        无，配置通过环境变量读取。
    返回值：
        无。
    异常/边界：
        当 MySQL 或 PostgreSQL 连接信息缺失时会抛出异常并标记任务失败。
    """

    settings = get_settings()
    if not settings.mysql_dsn:
        raise ValueError("缺少 INSIGHTS_MYSQL_DSN，无法执行目标池同步")

    pg_pool = await create_postgres_pool(
        settings.postgres_dsn,
        min_size=settings.postgres_min_pool_size,
        max_size=settings.postgres_max_pool_size,
    )
    run_id = await create_job_run(
        pg_pool,
        job_name="sync_strategy_targets_and_actions",
        source_system="MYSQL",
    )
    try:
        stats = await sync_strategy_targets_and_actions(
            pg_pool=pg_pool,
            mysql_dsn=settings.mysql_dsn,
            mysql_schema=settings.mysql_schema,
            min_trade_date=settings.mysql_min_trade_date,
        )
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="SUCCESS",
            rows_written=sum(item.target_rows + item.action_rows for item in stats),
            rows_updated=0,
            details={
                "strategies": [
                    {
                        "strategy_name": item.strategy_name,
                        "target_rows": item.target_rows,
                        "action_rows": item.action_rows,
                    }
                    for item in stats
                ]
            },
        )
        logger.info("✅ 目标池同步任务完成，共处理 %s 个策略", len(stats))
    except Exception as exc:
        await finish_job_run(
            pg_pool,
            run_id=run_id,
            status="FAILED",
            rows_written=0,
            rows_updated=0,
            details={"error": str(exc)},
        )
        logger.exception("❌ 目标池同步任务失败")
        raise
    finally:
        await close_postgres_pool(pg_pool)


if __name__ == "__main__":
    asyncio.run(run())
