from datetime import date
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """用途：统一读取分析服务配置。

    参数：
        无，配置通过环境变量注入。
    返回值：
        `Settings` 实例，包含 API 前缀与 PostgreSQL 连接参数。
    异常/边界：
        当 `INSIGHTS_POSTGRES_DSN` 缺失时，应用启动阶段会因连接失败而无法正常服务。
    """

    app_name: str = Field(default="insights", alias="INSIGHTS_APP_NAME")
    api_prefix: str = Field(default="/api", alias="INSIGHTS_API_PREFIX")
    cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        alias="INSIGHTS_CORS_ORIGINS",
    )
    postgres_dsn: str = Field(alias="INSIGHTS_POSTGRES_DSN")
    postgres_min_pool_size: int = Field(default=1, alias="INSIGHTS_POSTGRES_MIN_POOL_SIZE")
    postgres_max_pool_size: int = Field(default=10, alias="INSIGHTS_POSTGRES_MAX_POOL_SIZE")
    mysql_dsn: str | None = Field(default=None, alias="INSIGHTS_MYSQL_DSN")
    mysql_schema: str = Field(default="CB_HISTORY", alias="INSIGHTS_MYSQL_SCHEMA")
    mysql_min_trade_date: date = Field(default=date(2026, 3, 1), alias="INSIGHTS_MYSQL_MIN_TRADE_DATE")
    clickhouse_host: str | None = Field(default=None, alias="INSIGHTS_CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=8123, alias="INSIGHTS_CLICKHOUSE_PORT")
    clickhouse_user: str | None = Field(default=None, alias="INSIGHTS_CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="INSIGHTS_CLICKHOUSE_PASSWORD")
    clickhouse_database: str = Field(default="cnstock", alias="INSIGHTS_CLICKHOUSE_DATABASE")
    clickhouse_secure: bool = Field(default=False, alias="INSIGHTS_CLICKHOUSE_SECURE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def clickhouse_enabled(self) -> bool:
        """用途：判断当前是否提供了可用的 ClickHouse 连接配置。

        参数：
            无。
        返回值：
            当主机与用户名均存在时返回 `True`，否则返回 `False`。
        异常/边界：
            该属性只检查最小配置完整性，不主动探测网络可达性。
        """

        return bool(self.clickhouse_host and self.clickhouse_user)

    @property
    def cors_origin_list(self) -> list[str]:
        """用途：将逗号分隔的 CORS 源配置转换为列表。

        参数：
            无。
        返回值：
            去除空白和空字符串后的来源地址列表。
        异常/边界：
            当环境变量为空字符串时返回空列表，表示不额外放行任何跨域来源。
        """

        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """用途：返回全局缓存的配置对象。

    参数：
        无。
    返回值：
        `Settings` 单例配置对象。
    异常/边界：
        当环境变量缺失时，首次调用会抛出配置校验异常。
    """

    return Settings()
