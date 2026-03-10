from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """用途：提供服务健康检查接口。

    参数：
        无。
    返回值：
        包含服务状态的简单字典。
    异常/边界：
        该接口不依赖数据库，用于最小可用性探测。
    """

    return {"status": "ok"}

