from fastapi import Request
import asyncpg


def get_postgres_pool(request: Request) -> asyncpg.Pool:
    """用途：从应用状态中获取 PostgreSQL 连接池。

    参数：
        request：FastAPI 请求对象。
    返回值：
        已初始化的 `asyncpg.Pool`。
    异常/边界：
        当应用尚未完成启动或连接池未注入时，抛出 `RuntimeError`。
    """

    pool = getattr(request.app.state, "postgres_pool", None)
    if pool is None:
        raise RuntimeError("PostgreSQL 连接池尚未初始化")
    return pool

