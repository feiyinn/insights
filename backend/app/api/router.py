from fastapi import APIRouter

from .routes.overview import router as overview_router
from .routes.health import router as health_router
from .routes.strategies import router as strategies_router


def build_api_router() -> APIRouter:
    """用途：组装分析服务 API 路由。

    参数：
        无。
    返回值：
        已挂载健康检查与策略接口的 `APIRouter`。
    异常/边界：
        当新增路由模块时，需要在这里显式注册才能生效。
    """

    api_router = APIRouter()
    api_router.include_router(health_router)
    api_router.include_router(overview_router)
    api_router.include_router(strategies_router)
    return api_router
