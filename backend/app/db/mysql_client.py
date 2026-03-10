from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

import pymysql
from pymysql.cursors import DictCursor


CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class MySQLTargetRow:
    """用途：描述从 MySQL 策略表读取的一行目标池记录。

    参数：
        trade_date：目标池对应交易日。
        code：标的代码。
        name：标的名称。
        rank：排序名次。
        time_tag：该批次生成时间，已标准化为带时区时间。
    返回值：
        不可变数据对象，用于同步与动作重建。
    异常/边界：
        `time_tag` 若为无时区时间，将默认按北京时间解释。
    """

    trade_date: date
    code: str
    name: str
    rank: int
    time_tag: datetime


def _normalize_time_tag(raw_value: Any) -> datetime:
    """用途：将 MySQL 返回的批次时间标准化为带北京时间的时间对象。

    参数：
        raw_value：MySQL 查询返回的时间值。
    返回值：
        带 `Asia/Shanghai` 时区的 `datetime` 对象。
    异常/边界：
        当输入不是 `datetime` 时抛出 `TypeError`，由上层捕获并作为同步失败处理。
    """

    if not isinstance(raw_value, datetime):
        raise TypeError(f"time_tag 类型非法: {type(raw_value)!r}")

    if raw_value.tzinfo is not None:
        return raw_value.astimezone(CN_TZ)

    return raw_value.replace(tzinfo=CN_TZ)


class MySQLClient:
    """用途：提供 `insights` 项目的 MySQL 只读查询能力。

    参数：
        dsn：MySQL DSN，格式 `mysql://user:password@host:port/database`。
    返回值：
        可复用的 MySQL 客户端实例。
    异常/边界：
        当 DSN 缺失或格式非法时，构造阶段抛出 `ValueError`。
    """

    def __init__(self, dsn: str):
        if not dsn:
            raise ValueError("MySQL DSN 不能为空")

        parsed = urlparse(dsn)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise ValueError("MySQL DSN 必须以 mysql:// 或 mysql+pymysql:// 开头")

        self._host = parsed.hostname or "localhost"
        self._port = int(parsed.port or 3306)
        self._user = unquote(parsed.username or "")
        self._password = unquote(parsed.password or "")
        self._database = (parsed.path or "").lstrip("/")
        if not self._user or not self._database:
            raise ValueError("MySQL DSN 需要包含 user 和 database")

        self._conn: pymysql.connections.Connection | None = None

    def connect(self) -> None:
        """用途：建立 MySQL 连接。

        参数：
            无。
        返回值：
            无。
        异常/边界：
            当数据库不可达或认证失败时抛出驱动异常。
        """

        self._conn = pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
        )

    def close(self) -> None:
        """用途：关闭 MySQL 连接。

        参数：
            无。
        返回值：
            无。
        异常/边界：
            当连接尚未建立时直接返回。
        """

        if self._conn is None:
            return

        self._conn.close()
        self._conn = None

    def __enter__(self) -> "MySQLClient":
        """用途：支持上下文管理方式自动建立连接。

        参数：
            无。
        返回值：
            已连接的客户端对象。
        异常/边界：
            若连接建立失败则直接向外抛出异常。
        """

        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """用途：在上下文退出时自动关闭连接。

        参数：
            exc_type/exc/tb：上下文异常信息。
        返回值：
            无。
        异常/边界：
            无论上下文是否抛错，都会尝试关闭连接。
        """

        self.close()

    def fetch_strategy_targets(
        self,
        *,
        schema: str,
        table_name: str,
        start_trade_date: date | None = None,
    ) -> list[MySQLTargetRow]:
        """用途：读取某个策略表中的全部目标池记录。

        参数：
            schema：MySQL schema 名称。
            table_name：策略表名，当前与策略名一致。
            start_trade_date：可选的起始交易日，仅返回该日期及之后的记录。
        返回值：
            `MySQLTargetRow` 列表，按 `time_tag` 与 `rank` 升序排序。
        异常/边界：
            当表不存在或查询失败时抛出驱动异常；调用方可据此记录失败任务。
        """

        if self._conn is None:
            raise RuntimeError("MySQL 连接尚未建立")

        safe_schema = schema.replace("`", "``")
        safe_table = table_name.replace("`", "``")
        query = f"""
            SELECT trade_date, code, name, `rank`, time_tag
            FROM `{safe_schema}`.`{safe_table}`
            WHERE (%s IS NULL OR trade_date >= %s)
            ORDER BY time_tag ASC, `rank` ASC
        """
        with self._conn.cursor() as cursor:
            cursor.execute(query, (start_trade_date, start_trade_date))
            rows = cursor.fetchall()

        result: list[MySQLTargetRow] = []
        for row in rows:
            result.append(
                MySQLTargetRow(
                    trade_date=row["trade_date"],
                    code=str(row["code"]),
                    name=str(row["name"]),
                    rank=int(row["rank"]),
                    time_tag=_normalize_time_tag(row["time_tag"]),
                )
            )
        return result
