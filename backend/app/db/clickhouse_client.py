from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from clickhouse_connect import get_client
from clickhouse_connect.driver.client import Client


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class MinuteBar:
    """用途：描述一根分钟 K 线，用于反事实估值。

    参数：
        symbol：标的代码。
        bar_time：分钟开始时间，按上海时区语义解释。
        open_price：分钟开盘价。
        close_price：分钟收盘价。
        vwap_price：分钟成交量加权均价，可为空。
    返回值：
        便于后续统一计算估值价格的数据对象。
    异常/边界：
        当 `vwap_price` 为空时，应由上层自行决定回退到 `open_price` 或 `close_price`。
    """

    symbol: str
    bar_time: datetime
    open_price: Decimal
    close_price: Decimal
    vwap_price: Decimal | None

    @property
    def estimated_price(self) -> Decimal:
        """用途：返回该分钟线用于估值的价格。

        参数：
            无。
        返回值：
            优先返回 `vwap_price`，其次回退到 `open_price`，最后回退到 `close_price`。
        异常/边界：
            当前分钟线字段来自 ClickHouse，理论上 `open_price` 和 `close_price` 不为空。
        """

        return self.vwap_price if self.vwap_price is not None else self.open_price or self.close_price


class ClickHouseMarketClient:
    """用途：封装 ClickHouse 历史行情查询能力。

    参数：
        host：ClickHouse 主机地址。
        port：ClickHouse HTTP 端口。
        username：用户名。
        password：密码。
        database：数据库名。
        secure：是否启用 HTTPS。
    返回值：
        可执行分钟线查询的客户端对象。
    异常/边界：
        初始化阶段不会立即发起查询；当连接参数错误时，会在首次查询时抛出底层连接异常。
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
        secure: bool,
    ) -> None:
        self._client: Client = get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            secure=secure,
        )
        self._database = database

    def ping(self) -> None:
        """用途：验证 ClickHouse 连通性。

        参数：
            无。
        返回值：
            无。
        异常/边界：
            当数据库不可达或认证失败时，会抛出底层查询异常。
        """

        self._client.command("SELECT 1")

    def fetch_minute_bars_for_points(
        self,
        points: list[tuple[str, datetime]],
    ) -> dict[tuple[str, datetime], MinuteBar]:
        """用途：按“标的 + 估值时刻”批量加载对应分钟 K 线。

        参数：
            points：待估值点列表，时间应为带时区的 `datetime`。
        返回值：
            键为 `(symbol, lookup_minute)` 的分钟线映射。
        异常/边界：
            当前实现按交易日分组查询；若某分钟无 K 线，则该键不会出现在返回映射中。
        """

        grouped: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
        for symbol, ts in points:
            local_ts = ts.astimezone(SHANGHAI_TZ)
            trade_date = local_ts.date().isoformat()
            grouped[trade_date].append((symbol, local_ts))

        result: dict[tuple[str, datetime], MinuteBar] = {}
        for trade_date, day_points in grouped.items():
            symbols = sorted({symbol for symbol, _ in day_points})
            min_minute = min(ts.replace(second=0, microsecond=0) for _, ts in day_points)
            max_minute = max(ts.replace(second=0, microsecond=0) for _, ts in day_points) + timedelta(minutes=1)
            rows = self._query_minute_bars(
                trade_date=trade_date,
                symbols=symbols,
                start_time=min_minute,
                end_time=max_minute,
            )
            bar_map: dict[tuple[str, datetime], MinuteBar] = {
                (row.symbol, row.bar_time): row for row in rows
            }

            for symbol, local_ts in day_points:
                lookup_minute = local_ts.replace(second=0, microsecond=0)
                key = (symbol, lookup_minute)
                if key in bar_map:
                    result[key] = bar_map[key]
                    continue

                future_candidates = [
                    row
                    for row_key, row in bar_map.items()
                    if row_key[0] == symbol and row_key[1] > lookup_minute
                ]
                if future_candidates:
                    result[key] = min(future_candidates, key=lambda row: row.bar_time)

        return result

    def close(self) -> None:
        """用途：关闭 ClickHouse 客户端连接。

        参数：
            无。
        返回值：
            无。
        异常/边界：
            底层客户端未提供显式关闭接口时，本方法会静默返回。
        """

        close_method = getattr(self._client, "close", None)
        if callable(close_method):
            close_method()

    def fetch_latest_daily_closes(
        self,
        symbols: list[str],
        *,
        as_of_date: date | None = None,
    ) -> dict[str, tuple[date, Decimal]]:
        """用途：批量查询标的截至某日的最新日线收盘价。

        参数：
            symbols：标的代码列表。
            as_of_date：查询截止日期；为空时表示不设上界。
        返回值：
            键为标的代码，值为 `(latest_trade_date, latest_close)`。
        异常/边界：
            当 `symbols` 为空时直接返回空字典；若某标的无日线数据，则不会出现在结果中。
        """

        if not symbols:
            return {}

        quoted_symbols = ", ".join("'" + symbol.replace("'", "''") + "'" for symbol in symbols)
        date_filter = ""
        if as_of_date is not None:
            date_filter = f"AND tradeDate <= toDate('{as_of_date.isoformat()}')"
        query = f"""
            SELECT
                symbol,
                max(tradeDate) AS latest_trade_date,
                argMax(close, tradeDate) AS latest_close
            FROM {self._database}.kline_1d
            WHERE symbol IN ({quoted_symbols})
              {date_filter}
            GROUP BY symbol
            ORDER BY symbol ASC
        """
        query_result = self._client.query(query)
        result: dict[str, tuple[date, Decimal]] = {}
        for symbol, latest_trade_date, latest_close in query_result.result_rows:
            result[str(symbol)] = (
                latest_trade_date if isinstance(latest_trade_date, date) else date.fromisoformat(str(latest_trade_date)),
                Decimal(str(latest_close)),
            )
        return result

    def _query_minute_bars(
        self,
        *,
        trade_date: str,
        symbols: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> list[MinuteBar]:
        """用途：查询指定日期与时间窗口内的分钟线。

        参数：
            trade_date：交易日字符串，格式 `YYYY-MM-DD`。
            symbols：标的代码列表。
            start_time：窗口起始时间，按上海时区解释。
            end_time：窗口结束时间，按上海时区解释。
        返回值：
            分钟线对象列表。
        异常/边界：
            当 `symbols` 为空时直接返回空列表，避免生成非法 SQL。
        """

        if not symbols:
            return []

        quoted_symbols = ", ".join("'" + symbol.replace("'", "''") + "'" for symbol in symbols)
        start_literal = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_literal = end_time.strftime("%Y-%m-%d %H:%M:%S")
        query = f"""
            SELECT
                symbol,
                formatDateTime(barTime, '%Y-%m-%d %H:%i:%S', 'Asia/Shanghai') AS bar_time_text,
                open,
                close,
                vwap
            FROM {self._database}.kline_1m
            WHERE tradeDate = toDate('{trade_date}')
              AND symbol IN ({quoted_symbols})
              AND barTime >= toDateTime('{start_literal}', 'Asia/Shanghai')
              AND barTime <= toDateTime('{end_literal}', 'Asia/Shanghai')
            ORDER BY symbol ASC, barTime ASC
        """
        query_result = self._client.query(query)
        rows: list[MinuteBar] = []
        for symbol, bar_time_text, open_price, close_price, vwap_price in query_result.result_rows:
            rows.append(
                MinuteBar(
                    symbol=str(symbol),
                    bar_time=datetime.strptime(str(bar_time_text), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI_TZ),
                    open_price=Decimal(str(open_price)),
                    close_price=Decimal(str(close_price)),
                    vwap_price=Decimal(str(vwap_price)) if vwap_price is not None else None,
                )
            )
        return rows
