from typing import Optional

import asyncpg


async def create_postgres_pool(
    dsn: str,
    *,
    min_size: int,
    max_size: int,
) -> asyncpg.Pool:
    """用途：创建 PostgreSQL 连接池。

    参数：
        dsn：数据库连接字符串。
        min_size：连接池最小连接数。
        max_size：连接池最大连接数。
    返回值：
        `asyncpg.Pool` 连接池实例。
    异常/边界：
        当 DSN 无效或数据库不可达时抛出连接异常，由上层决定是否终止服务启动。
    """

    return await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
    )


async def close_postgres_pool(pool: Optional[asyncpg.Pool]) -> None:
    """用途：安全关闭 PostgreSQL 连接池。

    参数：
        pool：待关闭的连接池，可为空。
    返回值：
        无。
    异常/边界：
        当连接池为空时直接返回，不执行任何操作。
    """

    if pool is None:
        return

    await pool.close()

