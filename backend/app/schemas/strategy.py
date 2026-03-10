from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StrategySummary(BaseModel):
    """用途：描述单个策略实例的基础摘要信息。

    参数：
        各字段来自 `insights.dim_strategy` 查询结果。
    返回值：
        可直接被 FastAPI 序列化的摘要对象。
    异常/边界：
        `account_id` 与 `tactic_id` 允许为空，兼容尚未补齐的历史数据。
    """

    strategy_key: int
    strategy_name: str
    portfolio_id: str
    account_id: str | None
    tactic_id: str | None
    mode: str
    enabled: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

