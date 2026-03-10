import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import build_api_router
from .core.config import get_settings
from .db.pool import close_postgres_pool, create_postgres_pool


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insights")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """用途：管理应用启动与关闭时的资源生命周期。

    参数：
        app：FastAPI 应用实例。
    返回值：
        异步上下文管理器，负责注入与回收数据库连接池。
    异常/边界：
        当数据库连接创建失败时，异常会向上抛出并阻止应用启动，避免服务处于半可用状态。
    """

    settings = get_settings()
    logger.info("🚀 正在初始化 insights 分析服务")
    app.state.settings = settings
    app.state.postgres_pool = await create_postgres_pool(
        settings.postgres_dsn,
        min_size=settings.postgres_min_pool_size,
        max_size=settings.postgres_max_pool_size,
    )
    logger.info("✅ PostgreSQL 连接池初始化完成")

    try:
        yield
    finally:
        logger.info("⏳ 正在关闭 PostgreSQL 连接池")
        await close_postgres_pool(getattr(app.state, "postgres_pool", None))
        logger.info("✅ insights 分析服务资源已释放")


def create_app() -> FastAPI:
    """用途：创建并配置 FastAPI 应用实例。

    参数：
        无。
    返回值：
        完整配置后的 FastAPI 应用。
    异常/边界：
        路由与生命周期均在此集中装配，后续扩展应优先在此注册。
    """

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_api_router(), prefix=settings.api_prefix)
    return app


app = create_app()
