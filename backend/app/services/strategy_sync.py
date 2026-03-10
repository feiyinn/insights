from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import asyncpg

from ..db.mysql_client import MySQLClient, MySQLTargetRow


logger = logging.getLogger("insights.sync")


@dataclass(frozen=True)
class SyncStats:
    """用途：描述单次策略同步的统计结果。

    参数：
        strategy_name：策略名称。
        target_rows：同步写入的目标池记录数。
        action_rows：重建写入的原始动作记录数。
    返回值：
        便于日志输出与汇总的统计对象。
    异常/边界：
        数值字段均按非负整数使用。
    """

    strategy_name: str
    target_rows: int
    action_rows: int


async def create_job_run(
    pool: asyncpg.Pool,
    *,
    job_name: str,
    source_system: str,
) -> int:
    """用途：创建一条 ETL 运行记录。

    参数：
        pool：PostgreSQL 连接池。
        job_name：任务名。
        source_system：数据来源系统。
    返回值：
        新建的 `run_id`。
    异常/边界：
        数据库异常会向上抛出，由调用方统一捕获。
    """

    query = """
        INSERT INTO insights.etl_job_run (job_name, source_system, status)
        VALUES ($1, $2, 'RUNNING')
        RETURNING run_id
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(query, job_name, source_system)


async def finish_job_run(
    pool: asyncpg.Pool,
    *,
    run_id: int,
    status: str,
    rows_written: int,
    rows_updated: int,
    details: dict[str, Any],
) -> None:
    """用途：结束 ETL 运行记录并写入统计信息。

    参数：
        run_id：任务运行 ID。
        status：任务状态。
        rows_written：新增记录数。
        rows_updated：更新记录数。
        details：任务详情 JSON。
    返回值：
        无。
    异常/边界：
        状态值需与表约束一致，否则数据库会拒绝写入。
    """

    query = """
        UPDATE insights.etl_job_run
        SET status = $2,
            finished_at = NOW(),
            rows_written = $3,
            rows_updated = $4,
            details = $5::jsonb,
            updated_at = NOW()
        WHERE run_id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            run_id,
            status,
            rows_written,
            rows_updated,
            json.dumps(details, ensure_ascii=False),
        )


async def fetch_distinct_strategy_names(pool: asyncpg.Pool) -> list[str]:
    """用途：从分析维表中读取需要同步的策略名称列表。

    参数：
        pool：PostgreSQL 连接池。
    返回值：
        去重后的策略名称列表。
    异常/边界：
        当维表为空时返回空列表。
    """

    query = """
        SELECT DISTINCT strategy_name
        FROM insights.dim_strategy
        ORDER BY strategy_name ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return [str(row["strategy_name"]) for row in rows]


def _group_targets_by_batch(rows: list[MySQLTargetRow]) -> list[tuple[datetime, date, dict[str, MySQLTargetRow]]]:
    """用途：将 MySQL 目标池记录按批次时间聚合。

    参数：
        rows：同一策略的目标池原始记录列表。
    返回值：
        形如 `(batch_time_tag, trade_date, code->row)` 的有序批次列表。
    异常/边界：
        空输入返回空列表；同一批次同一标的若重复出现，后写会覆盖前写。
    """

    grouped: dict[datetime, dict[str, MySQLTargetRow]] = defaultdict(dict)
    trade_dates: dict[datetime, date] = {}
    for row in rows:
        grouped[row.time_tag][row.code] = row
        trade_dates[row.time_tag] = row.trade_date

    return [
        (batch_time_tag, trade_dates[batch_time_tag], grouped[batch_time_tag])
        for batch_time_tag in sorted(grouped.keys())
    ]


def _build_raw_actions(
    *,
    strategy_name: str,
    batches: list[tuple[datetime, date, dict[str, MySQLTargetRow]]],
) -> list[dict[str, Any]]:
    """用途：根据相邻批次目标池重建原始调仓动作。

    参数：
        strategy_name：策略名称。
        batches：按时间升序排列的批次数据。
    返回值：
        适合写入 `insights.fact_strategy_action_raw` 的字典列表。
    异常/边界：
        第一批由于没有前序目标池，会把全部标的视作初始买入；当前版本会同时生成 `HOLD` 记录，便于后续归因分析。
    """

    actions: list[dict[str, Any]] = []
    previous_map: dict[str, MySQLTargetRow] = {}

    for batch_time_tag, trade_date, current_map in batches:
        all_codes = sorted(set(previous_map.keys()) | set(current_map.keys()))
        for code in all_codes:
            prev_row = previous_map.get(code)
            curr_row = current_map.get(code)

            if prev_row is None and curr_row is not None:
                actions.append(
                    {
                        "trade_date": trade_date,
                        "strategy_name": strategy_name,
                        "batch_time_tag": batch_time_tag,
                        "instrument_id": code,
                        "action_type": "BUY",
                        "reason_type": "NEW_ENTRY",
                        "before_in_target": False,
                        "after_in_target": True,
                        "before_rank_no": None,
                        "after_rank_no": curr_row.rank,
                        "raw_holding_qty": None,
                        "planned_qty": None,
                        "planned_weight": None,
                        "notes": "首次进入目标池或相对上一批新纳入",
                    }
                )
            elif prev_row is not None and curr_row is None:
                actions.append(
                    {
                        "trade_date": trade_date,
                        "strategy_name": strategy_name,
                        "batch_time_tag": batch_time_tag,
                        "instrument_id": code,
                        "action_type": "SELL",
                        "reason_type": "REMOVE_FROM_TARGET",
                        "before_in_target": True,
                        "after_in_target": False,
                        "before_rank_no": prev_row.rank,
                        "after_rank_no": None,
                        "raw_holding_qty": None,
                        "planned_qty": None,
                        "planned_weight": None,
                        "notes": "相对上一批从目标池移除",
                    }
                )
            elif prev_row is not None and curr_row is not None:
                actions.append(
                    {
                        "trade_date": trade_date,
                        "strategy_name": strategy_name,
                        "batch_time_tag": batch_time_tag,
                        "instrument_id": code,
                        "action_type": "HOLD",
                        "reason_type": "CONTINUE_HOLD",
                        "before_in_target": True,
                        "after_in_target": True,
                        "before_rank_no": prev_row.rank,
                        "after_rank_no": curr_row.rank,
                        "raw_holding_qty": None,
                        "planned_qty": None,
                        "planned_weight": None,
                        "notes": "相邻批次均在目标池中，原始策略应继续持有",
                    }
                )

        previous_map = current_map

    return actions


async def _upsert_strategy_targets(
    pool: asyncpg.Pool,
    *,
    strategy_name: str,
    source_schema: str,
    source_table: str,
    rows: list[MySQLTargetRow],
) -> int:
    """用途：将策略目标池快照写入 PostgreSQL 分析表。

    参数：
        pool：PostgreSQL 连接池。
        strategy_name：策略名称。
        source_schema：MySQL schema 名称。
        source_table：MySQL 策略表名。
        rows：目标池记录列表。
    返回值：
        传入记录数，便于做同步统计。
    异常/边界：
        若列表为空则直接返回 0，不执行写入。
    """

    insert_query = """
        INSERT INTO insights.fact_strategy_target (
            trade_date,
            strategy_name,
            portfolio_id,
            batch_time_tag,
            instrument_id,
            instrument_name,
            rank_no,
            is_latest_batch,
            source_system,
            source_schema,
            source_table,
            updated_at
        ) VALUES (
            $1, $2, NULL, $3, $4, $5, $6, FALSE, 'mysql', $7, $8, NOW()
        )
        ON CONFLICT (strategy_name, trade_date, batch_time_tag, instrument_id)
        DO UPDATE SET
            instrument_name = EXCLUDED.instrument_name,
            rank_no = EXCLUDED.rank_no,
            source_schema = EXCLUDED.source_schema,
            source_table = EXCLUDED.source_table,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM insights.fact_strategy_target WHERE strategy_name = $1",
                strategy_name,
            )
            if not rows:
                return 0
            await conn.executemany(
                insert_query,
                [
                    (
                        row.trade_date,
                        strategy_name,
                        row.time_tag,
                        row.code,
                        row.name,
                        row.rank,
                        source_schema,
                        source_table,
                    )
                    for row in rows
                ],
            )
            latest_batch = max(row.time_tag for row in rows)
            await conn.execute(
                """
                UPDATE insights.fact_strategy_target
                SET is_latest_batch = (batch_time_tag = $2),
                    updated_at = NOW()
                WHERE strategy_name = $1
                """,
                strategy_name,
                latest_batch,
            )

    return len(rows)


async def _refresh_raw_actions(
    pool: asyncpg.Pool,
    *,
    strategy_name: str,
    actions: list[dict[str, Any]],
) -> int:
    """用途：刷新某策略的原始调仓动作快照。

    参数：
        pool：PostgreSQL 连接池。
        strategy_name：策略名称。
        actions：已计算完成的动作记录列表。
    返回值：
        写入动作记录数。
    异常/边界：
        当前实现采用“按策略全量删除后重建”，以保证结果一致性；当动作列表为空时仅执行删除。
    """

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM insights.fact_strategy_action_raw WHERE strategy_name = $1",
                strategy_name,
            )
            if not actions:
                return 0

            insert_query = """
                INSERT INTO insights.fact_strategy_action_raw (
                    trade_date,
                    strategy_name,
                    portfolio_id,
                    batch_time_tag,
                    instrument_id,
                    action_type,
                    reason_type,
                    before_in_target,
                    after_in_target,
                    before_rank_no,
                    after_rank_no,
                    raw_holding_qty,
                    planned_qty,
                    planned_weight,
                    notes,
                    updated_at
                ) VALUES (
                    $1, $2, NULL, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW()
                )
            """
            await conn.executemany(
                insert_query,
                [
                    (
                        action["trade_date"],
                        action["strategy_name"],
                        action["batch_time_tag"],
                        action["instrument_id"],
                        action["action_type"],
                        action["reason_type"],
                        action["before_in_target"],
                        action["after_in_target"],
                        action["before_rank_no"],
                        action["after_rank_no"],
                        action["raw_holding_qty"],
                        action["planned_qty"],
                        action["planned_weight"],
                        action["notes"],
                    )
                    for action in actions
                ],
            )

    return len(actions)


async def sync_strategy_targets_and_actions(
    *,
    pg_pool: asyncpg.Pool,
    mysql_dsn: str,
    mysql_schema: str,
    min_trade_date: date,
    strategy_names: list[str] | None = None,
) -> list[SyncStats]:
    """用途：同步策略目标池并重建原始调仓动作。

    参数：
        pg_pool：PostgreSQL 连接池。
        mysql_dsn：MySQL DSN。
        mysql_schema：策略表所在 schema。
        min_trade_date：MySQL 目标池同步的最早交易日。
        strategy_names：可选的策略名称列表；为空时自动读取维表中的全部策略。
    返回值：
        每个策略对应一条 `SyncStats` 统计结果。
    异常/边界：
        单个策略同步失败会中断当前任务并向上抛出异常，以避免出现部分成功、部分失败但未被注意的状态。
    """

    names = strategy_names or await fetch_distinct_strategy_names(pg_pool)
    if not names:
        logger.info("⚠️ 未发现可同步的策略名称，跳过目标池同步")
        return []

    stats: list[SyncStats] = []
    with MySQLClient(mysql_dsn) as mysql_client:
        for strategy_name in names:
            logger.info("⏳ 正在同步策略目标池: %s", strategy_name)
            rows = mysql_client.fetch_strategy_targets(
                schema=mysql_schema,
                table_name=strategy_name,
                start_trade_date=min_trade_date,
            )
            target_count = await _upsert_strategy_targets(
                pg_pool,
                strategy_name=strategy_name,
                source_schema=mysql_schema,
                source_table=strategy_name,
                rows=rows,
            )
            batches = _group_targets_by_batch(rows)
            actions = _build_raw_actions(
                strategy_name=strategy_name,
                batches=batches,
            )
            action_count = await _refresh_raw_actions(
                pg_pool,
                strategy_name=strategy_name,
                actions=actions,
            )
            logger.info(
                "✅ 策略同步完成: %s target_rows=%s action_rows=%s",
                strategy_name,
                target_count,
                action_count,
            )
            stats.append(
                SyncStats(
                    strategy_name=strategy_name,
                    target_rows=target_count,
                    action_rows=action_count,
                )
            )

    return stats
