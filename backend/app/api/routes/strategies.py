import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg

from ...api.dependencies import get_postgres_pool
from ...schemas.analysis import (
    ParameterLabDiagnosticItem,
    ParameterLabExportPayload,
    ParameterLabExportSymbolOverrideItem,
    ParameterLabPayload,
    ParameterLabScenarioItem,
    ParameterLabSymbolDetailItem,
    ParameterLabSymbolItem,
    ParameterProfileSuggestionItem,
    PositionLifecycleItem,
    StrategyActionItem,
    StrategyDailyItem,
    StrategyTargetItem,
    TpSlInterventionItem,
    TpSlSummaryItem,
)
from ...schemas.strategy import StrategySummary


router = APIRouter(prefix="/strategies", tags=["strategies"])


def _to_float(value: object | None) -> float | None:
    """用途：把数据库聚合值安全转换为浮点数。

    参数：
        value：可能来自 asyncpg 行对象的数值或空值。
    返回值：
        可序列化给前端的 `float` 或 `None`。
    异常/边界：
        当值为空时直接返回 `None`，避免在聚合结果缺失时抛错。
    """

    if value is None:
        return None
    return float(value)


def _to_int(value: object | None) -> int:
    """用途：把数据库聚合值安全转换为整数。

    参数：
        value：可能来自 asyncpg 行对象的整数、字符串数字或空值。
    返回值：
        转换后的整数；空值回退为 0。
    异常/边界：
        当值为空时返回 0，避免前端收到 `None` 后还要额外兜底。
    """

    if value is None:
        return 0
    return int(value)


def _safe_ratio(numerator: float | None, denominator: float | None, digits: int = 8) -> float | None:
    """用途：安全计算两个浮点数的比值。

    参数：
        numerator：分子数值。
        denominator：分母数值。
        digits：结果保留的小数位数。
    返回值：
        四舍五入后的比值；若分母缺失或为 0，则返回 `None`。
    异常/边界：
        该函数仅处理简单比值，不自动放大为百分比或 bps。
    """

    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, digits)


def _safe_bps(numerator: float | None, denominator: float | None, digits: int = 4) -> float | None:
    """用途：把收益变化标准化为 bps。

    参数：
        numerator：待标准化的收益差额。
        denominator：统一分母，通常为已补价生命周期名义本金。
        digits：结果保留的小数位数。
    返回值：
        以 bps 表示的标准化结果；若分母缺失或为 0，则返回 `None`。
    异常/边界：
        内部依赖 `_safe_ratio`，因此同样会对空值和 0 分母做安全回退。
    """

    ratio = _safe_ratio(numerator, denominator, digits=12)
    if ratio is None:
        return None
    return round(ratio * 10000, digits)


def _normalize_json_object(value: object | None) -> dict[str, object]:
    """用途：把数据库中的 JSON/JSONB 结果统一转换为字典对象。

    参数：
        value：可能是字典、JSON 字符串或空值的数据库字段。
    返回值：
        标准 Python 字典。
    异常/边界：
        当值为空、不是字典，或 JSON 解析失败时统一回退为空字典，避免接口因附加说明字段异常而整体失败。
    """

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _build_parameter_lab_symbol_item(
    row: asyncpg.Record,
    *,
    include_payloads: bool,
) -> ParameterLabSymbolItem | ParameterLabSymbolDetailItem:
    """用途：把标的级参数实验室查询结果转换为响应模型。

    参数：
        row：联合查询得到的单条记录。
        include_payloads：是否输出原始扩展载荷。
    返回值：
        标的级摘要对象或详情对象。
    异常/边界：
        当建议结果尚未生成时，建议相关字段会保留为空，不会阻断整个列表查询。
    """

    diagnostic_payload = _normalize_json_object(row["diagnostic_payload"]) if "diagnostic_payload" in row else {}
    recommendation_payload = (
        _normalize_json_object(row["recommendation_payload"]) if "recommendation_payload" in row else {}
    )
    pricing_payload = diagnostic_payload.get("pricing")
    pricing = pricing_payload if isinstance(pricing_payload, dict) else {}

    payload = {
        "as_of_date": row["as_of_date"],
        "date_from": row["date_from"],
        "date_to": row["date_to"],
        "strategy_name": row["strategy_name"],
        "portfolio_id": row["portfolio_id"],
        "account_id": row["account_id"],
        "tactic_id": row["tactic_id"],
        "instrument_id": row["instrument_id"],
        "diagnosis_label": row["diagnosis_label"],
        "total_lifecycles": _to_int(row["total_lifecycles"]),
        "priced_lifecycles": _to_int(row["priced_lifecycles"]),
        "priced_coverage_ratio": _to_float(row["priced_coverage_ratio"]),
        "tpsl_intervention_count": _to_int(row["tpsl_intervention_count"]),
        "reentry_count": _to_int(row["reentry_count"]),
        "pnl_delta_sum": _to_float(row["pnl_delta_sum"]),
        "return_actual_bps": _to_float(row["return_actual_bps"]),
        "return_raw_bps": _to_float(row["return_raw_bps"]),
        "delta_bps": _to_float(row["delta_bps"]),
        "misfire_rate": _to_float(row["misfire_rate"]),
        "protection_efficiency": _to_float(row["protection_efficiency"]),
        "avg_hold_minutes_actual": _to_float(row["avg_hold_minutes_actual"]),
        "avg_hold_minutes_raw": _to_float(row["avg_hold_minutes_raw"]),
        "hold_gap_ratio": _to_float(row["hold_gap_ratio"]),
        "confidence_score": _to_float(row["confidence_score"]),
        "direct_priced_lifecycles": _to_int(pricing.get("direct_priced_lifecycles")),
        "provisional_priced_lifecycles": _to_int(pricing.get("provisional_priced_lifecycles")),
        "latest_pricing_trade_date": pricing.get("latest_trade_date"),
        "source_method": row["source_method"],
        "recommendation_mode": recommendation_payload.get("mode"),
        "recommended_action": row["recommended_action"],
        "recommended_profile": row["recommended_profile"],
        "hard_sl_multiplier": _to_float(row["hard_sl_multiplier"]),
        "break_even_trigger_multiplier": _to_float(row["break_even_trigger_multiplier"]),
        "trailing_buffer_multiplier": _to_float(row["trailing_buffer_multiplier"]),
        "take_profit_trigger_multiplier": _to_float(row["take_profit_trigger_multiplier"]),
        "expected_delta_bps": _to_float(row["expected_delta_bps"]),
        "expected_misfire_rate": _to_float(row["expected_misfire_rate"]),
        "expected_protection_efficiency": _to_float(row["expected_protection_efficiency"]),
        "priority_score": _to_float(row["priority_score"]),
        "reason_summary": row["reason_summary"],
    }
    if include_payloads:
        payload["diagnostic_payload"] = diagnostic_payload
        payload["recommendation_payload"] = recommendation_payload
        return ParameterLabSymbolDetailItem.model_validate(payload)
    return ParameterLabSymbolItem.model_validate(payload)


def _sort_parameter_lab_symbols(
    items: list[ParameterLabSymbolItem],
    *,
    sort_by: str,
) -> list[ParameterLabSymbolItem]:
    """用途：按指定字段对标的级参数实验室结果排序。

    参数：
        items：待排序的标的列表。
        sort_by：排序字段名。
    返回值：
        排序后的新列表。
    异常/边界：
        未识别的字段会回退为按 `priority_score` 排序。
    """

    if sort_by == "delta_bps":
        return sorted(items, key=lambda item: abs(item.delta_bps or 0.0), reverse=True)
    if sort_by == "misfire_rate":
        return sorted(items, key=lambda item: item.misfire_rate or 0.0, reverse=True)
    if sort_by == "confidence_score":
        return sorted(items, key=lambda item: item.confidence_score or 0.0, reverse=True)
    return sorted(items, key=lambda item: item.priority_score or 0.0, reverse=True)


def _matches_symbol_pricing_filter(item: ParameterLabSymbolItem, pricing_filter: str | None) -> bool:
    """用途：判断单个标的是否命中补价来源筛选条件。

    参数：
        item：标的级参数实验室摘要对象。
        pricing_filter：补价来源筛选值。
    返回值：
        命中筛选条件时返回 `True`。
    异常/边界：
        空值或未识别筛选值统一按“全部补价来源”处理，避免导出接口意外过滤掉结果。
    """

    provisional_count = item.provisional_priced_lifecycles or 0
    direct_count = item.direct_priced_lifecycles or 0
    if pricing_filter == "HAS_PROVISIONAL":
        return provisional_count > 0
    if pricing_filter == "DIRECT_ONLY":
        return provisional_count <= 0 and direct_count > 0
    return True


def _matches_symbol_mode_filter(item: ParameterLabSymbolItem, mode_filter: str | None) -> bool:
    """用途：判断单个标的是否命中建议模式筛选条件。

    参数：
        item：标的级参数实验室摘要对象。
        mode_filter：建议模式筛选值。
    返回值：
        命中筛选条件时返回 `True`。
    异常/边界：
        当建议模式为空时，仅在筛选“常规启发式建议”时视作命中。
    """

    recommendation_mode = item.recommendation_mode
    if mode_filter == "LOW_SAMPLE_TRIAL":
        return recommendation_mode == "LOW_SAMPLE_TRIAL"
    if mode_filter == "LOW_SAMPLE_NEEDS_PRICING":
        return recommendation_mode == "LOW_SAMPLE_NEEDS_PRICING"
    if mode_filter == "REGULAR":
        return recommendation_mode is None
    return True


def _filter_parameter_lab_symbols(
    items: list[ParameterLabSymbolItem],
    *,
    pricing_filter: str | None,
    mode_filter: str | None,
) -> list[ParameterLabSymbolItem]:
    """用途：对标的级参数实验室摘要执行 Python 侧补充筛选。

    参数：
        items：基础标的级摘要列表。
        pricing_filter：补价来源筛选值。
        mode_filter：建议模式筛选值。
    返回值：
        过滤后的标的级摘要列表。
    异常/边界：
        该函数只补充前端筛选所需的派生条件，不替代 SQL 中已有的基础过滤。
    """

    return [
        item
        for item in items
        if _matches_symbol_pricing_filter(item, pricing_filter)
        and _matches_symbol_mode_filter(item, mode_filter)
    ]


async def _fetch_parameter_lab_symbol_items(
    conn: asyncpg.Connection,
    *,
    strategy_name: str,
    portfolio_id: str | None,
    diagnosis_label: str | None,
    recommended_action: str | None,
    only_actionable: bool,
    include_payloads: bool,
) -> list[ParameterLabSymbolItem | ParameterLabSymbolDetailItem]:
    """用途：读取某策略的标的级参数实验室原始结果并转换为响应模型。

    参数：
        conn：当前请求复用的 PostgreSQL 连接。
        strategy_name：策略名称。
        portfolio_id：可选组合 ID。
        diagnosis_label：可选诊断标签过滤条件。
        recommended_action：可选建议动作过滤条件。
        only_actionable：是否只保留非 `HOLD` 标的。
        include_payloads：是否输出详情所需的原始 payload。
    返回值：
        已转换完成的标的级摘要或详情对象列表。
    异常/边界：
        当标的级事实表尚未生成时返回空列表，不抛出异常。
    """

    query = """
        SELECT
            d.as_of_date,
            d.date_from,
            d.date_to,
            d.strategy_name,
            d.portfolio_id,
            d.account_id,
            d.tactic_id,
            d.instrument_id,
            d.diagnosis_label,
            d.total_lifecycles,
            d.priced_lifecycles,
            d.priced_coverage_ratio::float8 AS priced_coverage_ratio,
            d.tpsl_intervention_count,
            d.reentry_count,
            d.pnl_delta_sum::float8 AS pnl_delta_sum,
            d.return_actual_bps::float8 AS return_actual_bps,
            d.return_raw_bps::float8 AS return_raw_bps,
            d.delta_bps::float8 AS delta_bps,
            d.misfire_rate::float8 AS misfire_rate,
            d.protection_efficiency::float8 AS protection_efficiency,
            d.avg_hold_minutes_actual::float8 AS avg_hold_minutes_actual,
            d.avg_hold_minutes_raw::float8 AS avg_hold_minutes_raw,
            d.hold_gap_ratio::float8 AS hold_gap_ratio,
            d.confidence_score::float8 AS confidence_score,
            r.source_method,
            r.recommended_action,
            r.recommended_profile,
            r.hard_sl_multiplier::float8 AS hard_sl_multiplier,
            r.break_even_trigger_multiplier::float8 AS break_even_trigger_multiplier,
            r.trailing_buffer_multiplier::float8 AS trailing_buffer_multiplier,
            r.take_profit_trigger_multiplier::float8 AS take_profit_trigger_multiplier,
            r.expected_delta_bps::float8 AS expected_delta_bps,
            r.expected_misfire_rate::float8 AS expected_misfire_rate,
            r.expected_protection_efficiency::float8 AS expected_protection_efficiency,
            r.priority_score::float8 AS priority_score,
            r.reason_summary,
            d.diagnostic_payload,
            r.recommendation_payload
        FROM insights.fact_symbol_tpsl_diagnostics d
        LEFT JOIN insights.fact_symbol_tpsl_recommendation r
            ON r.strategy_name = d.strategy_name
           AND r.portfolio_id = d.portfolio_id
           AND r.instrument_id = d.instrument_id
        WHERE d.strategy_name = $1
          AND ($2::text IS NULL OR d.portfolio_id = $2)
          AND ($3::text IS NULL OR d.diagnosis_label = $3)
          AND ($4::text IS NULL OR COALESCE(r.recommended_action, 'HOLD') = $4)
          AND ($5::bool = FALSE OR COALESCE(r.recommended_action, 'HOLD') <> 'HOLD')
    """

    if not await _symbol_tpsl_tables_ready(conn):
        return []
    rows = await conn.fetch(
        query,
        strategy_name,
        portfolio_id,
        diagnosis_label,
        recommended_action,
        only_actionable,
    )
    return [
        _build_parameter_lab_symbol_item(row, include_payloads=include_payloads)
        for row in rows
    ]


def _build_parameter_lab_export_payload(
    *,
    strategy_name: str,
    portfolio_id: str | None,
    recommended_action: str | None,
    only_actionable: bool,
    pricing_filter: str | None,
    mode_filter: str | None,
    filtered_items: list[ParameterLabSymbolItem],
) -> ParameterLabExportPayload:
    """用途：把当前筛选结果整理为适合下游系统消费的导出对象。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID。
        recommended_action：建议动作筛选值。
        only_actionable：是否只查看非 `HOLD`。
        pricing_filter：补价来源筛选值。
        mode_filter：建议模式筛选值。
        filtered_items：应用全部筛选后的标的级摘要列表。
    返回值：
        结构化导出对象。
    异常/边界：
        即使当前没有导出候选标的，也会保留完整的过滤快照与统计摘要。
    """

    exported_overrides = [
        ParameterLabExportSymbolOverrideItem(
            instrument_id=item.instrument_id,
            recommended_action=item.recommended_action or "HOLD",
            recommended_profile=item.recommended_profile,
            recommendation_mode=item.recommendation_mode,
            hard_sl_multiplier=item.hard_sl_multiplier,
            break_even_trigger_multiplier=item.break_even_trigger_multiplier,
            trailing_buffer_multiplier=item.trailing_buffer_multiplier,
            take_profit_trigger_multiplier=item.take_profit_trigger_multiplier,
            confidence_score=item.confidence_score,
            source_method=item.source_method,
            reason_summary=item.reason_summary,
            direct_priced_lifecycles=item.direct_priced_lifecycles,
            provisional_priced_lifecycles=item.provisional_priced_lifecycles,
            latest_pricing_trade_date=item.latest_pricing_trade_date,
        )
        for item in filtered_items
        if (item.recommended_action or "HOLD") != "HOLD"
    ]
    actionable_count = sum(1 for item in filtered_items if (item.recommended_action or "HOLD") != "HOLD")
    provisional_pricing_count = sum(1 for item in filtered_items if (item.provisional_priced_lifecycles or 0) > 0)
    regular_mode_count = sum(1 for item in filtered_items if item.recommendation_mode is None)
    average_confidence = [
        item.confidence_score
        for item in filtered_items
        if item.confidence_score is not None
    ]

    return ParameterLabExportPayload(
        generated_at=datetime.now(timezone.utc),
        strategy_name=strategy_name,
        portfolio_id=portfolio_id,
        export_method="symbol_parameter_override_v1",
        filters={
            "only_actionable": only_actionable,
            "recommended_action": recommended_action or "ALL",
            "pricing_filter": pricing_filter or "ALL",
            "mode_filter": mode_filter or "ALL",
        },
        summary={
            "filtered_symbols": len(filtered_items),
            "actionable_symbols": actionable_count,
            "exported_overrides": len(exported_overrides),
            "loosen_count": sum(1 for item in filtered_items if item.recommended_action == "LOOSEN"),
            "tighten_count": sum(1 for item in filtered_items if item.recommended_action == "TIGHTEN"),
            "custom_count": sum(1 for item in filtered_items if item.recommended_action == "CUSTOM"),
            "provisional_pricing_symbols": provisional_pricing_count,
            "low_sample_trial_symbols": sum(
                1 for item in filtered_items if item.recommendation_mode == "LOW_SAMPLE_TRIAL"
            ),
            "regular_mode_symbols": regular_mode_count,
            "average_confidence_score": (
                sum(average_confidence) / len(average_confidence)
                if average_confidence
                else None
            ),
        },
        symbol_overrides=exported_overrides,
    )


async def _symbol_tpsl_tables_ready(conn: asyncpg.Connection) -> bool:
    """用途：检查标的级 TPSL 诊断与建议表是否已存在。

    参数：
        conn：当前请求复用的 PostgreSQL 连接。
    返回值：
        当两张表都存在时返回 `True`，否则返回 `False`。
    异常/边界：
        该检查只判断表存在性，不校验表内是否已有数据。
    """

    query = """
        SELECT
            to_regclass('insights.fact_symbol_tpsl_diagnostics') IS NOT NULL AS has_diagnostics,
            to_regclass('insights.fact_symbol_tpsl_recommendation') IS NOT NULL AS has_recommendations
    """
    row = await conn.fetchrow(query)
    if row is None:
        return False
    return bool(row["has_diagnostics"] and row["has_recommendations"])


def _build_parameter_recommendation(
    diagnostics: ParameterLabDiagnosticItem,
) -> tuple[str, str, list[ParameterProfileSuggestionItem]]:
    """用途：基于当前策略诊断结果生成参数敏感度结论和建议档位。

    参数：
        diagnostics：当前策略的聚合诊断结果。
    返回值：
        敏感度信号、总结文案和建议试验档位列表。
    异常/边界：
        当前建议使用相对倍数而非绝对阈值，避免在未知现网参数时输出误导性的固定值。
    """

    if diagnostics.total_interventions == 0:
        return (
            "NO_SAMPLE",
            "当前样本中尚未出现 TPSL 干预，先继续积累更多交易日与干预样本，再决定是否需要调参。",
            [
                ParameterProfileSuggestionItem(
                    profile_name="保持当前",
                    stance="观察",
                    hard_sl_multiplier=1.0,
                    break_even_trigger_multiplier=1.0,
                    trailing_buffer_multiplier=1.0,
                    take_profit_trigger_multiplier=1.0,
                    rationale="当前没有足够的风控触发样本，先维持现状并继续观察。",
                )
            ],
        )

    still_ratio = diagnostics.still_in_target_interventions / diagnostics.total_interventions
    net_delta = diagnostics.actual_minus_raw_pnl or 0.0

    if net_delta < 0 and still_ratio >= 0.55:
        return (
            "HIGH",
            "当前更像是 TPSL 偏敏感，尤其是大量干预发生在“下一次调仓仍应继续持有”的标的上，建议优先做放宽型实验。",
            [
                ParameterProfileSuggestionItem(
                    profile_name="温和放宽",
                    stance="推荐",
                    hard_sl_multiplier=1.08,
                    break_even_trigger_multiplier=1.12,
                    trailing_buffer_multiplier=1.15,
                    take_profit_trigger_multiplier=1.05,
                    rationale="先小幅放宽止损、保本与跟踪止损触发阈值，观察是否能减少被趋势中途甩出。",
                ),
                ParameterProfileSuggestionItem(
                    profile_name="趋势优先",
                    stance="进攻",
                    hard_sl_multiplier=1.15,
                    break_even_trigger_multiplier=1.25,
                    trailing_buffer_multiplier=1.22,
                    take_profit_trigger_multiplier=1.1,
                    rationale="更强调持有趋势完整性，适合排查当前是否因为过早止盈止损而损失收益。",
                ),
                ParameterProfileSuggestionItem(
                    profile_name="保持当前",
                    stance="对照",
                    hard_sl_multiplier=1.0,
                    break_even_trigger_multiplier=1.0,
                    trailing_buffer_multiplier=1.0,
                    take_profit_trigger_multiplier=1.0,
                    rationale="保留当前实盘参数作为对照组，便于比较放宽前后的收益与回撤差异。",
                ),
            ],
        )

    if net_delta > 0 and still_ratio <= 0.4:
        return (
            "DEFENSIVE",
            "当前 TPSL 总体在正向保护收益，说明现有风控并不算过度敏感，可尝试少量收紧做回撤优化实验。",
            [
                ParameterProfileSuggestionItem(
                    profile_name="保持当前",
                    stance="推荐",
                    hard_sl_multiplier=1.0,
                    break_even_trigger_multiplier=1.0,
                    trailing_buffer_multiplier=1.0,
                    take_profit_trigger_multiplier=1.0,
                    rationale="当前参数已经呈现正向净贡献，建议把现网参数保留为主对照组。",
                ),
                ParameterProfileSuggestionItem(
                    profile_name="轻微收紧",
                    stance="防守",
                    hard_sl_multiplier=0.95,
                    break_even_trigger_multiplier=0.96,
                    trailing_buffer_multiplier=0.92,
                    take_profit_trigger_multiplier=0.98,
                    rationale="轻微提升风控灵敏度，验证是否还能进一步降低回撤而不显著损伤收益。",
                ),
                ParameterProfileSuggestionItem(
                    profile_name="趋势保护",
                    stance="平衡",
                    hard_sl_multiplier=1.02,
                    break_even_trigger_multiplier=1.05,
                    trailing_buffer_multiplier=1.08,
                    take_profit_trigger_multiplier=1.03,
                    rationale="作为平衡档位，兼顾当前保护效果与趋势延续空间。",
                ),
            ],
        )

    return (
        "BALANCED",
        "当前 TPSL 的正负效果比较接近，说明参数未必严重失衡，建议围绕现网配置做小步宽松/收紧双向实验。",
        [
            ParameterProfileSuggestionItem(
                profile_name="保持当前",
                stance="推荐",
                hard_sl_multiplier=1.0,
                break_even_trigger_multiplier=1.0,
                trailing_buffer_multiplier=1.0,
                take_profit_trigger_multiplier=1.0,
                rationale="当前参数表现中性，保留现网配置作为中心对照组最稳妥。",
            ),
            ParameterProfileSuggestionItem(
                profile_name="小幅放宽",
                stance="进攻",
                hard_sl_multiplier=1.06,
                break_even_trigger_multiplier=1.08,
                trailing_buffer_multiplier=1.1,
                take_profit_trigger_multiplier=1.04,
                rationale="验证收益侧是否有被提前打断的趋势仓位。",
            ),
            ParameterProfileSuggestionItem(
                profile_name="小幅收紧",
                stance="防守",
                hard_sl_multiplier=0.96,
                break_even_trigger_multiplier=0.97,
                trailing_buffer_multiplier=0.95,
                take_profit_trigger_multiplier=0.98,
                rationale="验证回撤保护是否还能进一步增强，同时观察收益损耗是否可接受。",
            ),
        ],
    )


@router.get("", response_model=list[StrategySummary])
async def list_strategies(
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[StrategySummary]:
    """用途：返回当前已注册到分析系统中的策略列表。

    参数：
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        `StrategySummary` 列表，按策略名与组合 ID 排序。
    异常/边界：
        当表中暂无数据时返回空列表；查询异常会继续向上抛出，由框架统一处理。
    """

    query = """
        SELECT
            strategy_key,
            strategy_name,
            portfolio_id,
            account_id,
            tactic_id,
            mode,
            enabled,
            metadata,
            created_at,
            updated_at
        FROM insights.dim_strategy
        ORDER BY strategy_name ASC, portfolio_id ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)

    result: list[StrategySummary] = []
    for row in rows:
        payload = dict(row)
        metadata = payload.get("metadata")
        if isinstance(metadata, str):
            payload["metadata"] = json.loads(metadata)
        result.append(StrategySummary.model_validate(payload))
    return result


@router.get("/{strategy_name}/targets/latest", response_model=list[StrategyTargetItem])
async def get_latest_targets(
    strategy_name: str,
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[StrategyTargetItem]:
    """用途：返回某策略当前最新批次的目标池列表。

    参数：
        strategy_name：策略名称。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        最新批次目标池列表，按 `rank_no` 升序排列。
    异常/边界：
        当策略尚未同步目标池时返回空列表。
    """

    query = """
        SELECT
            trade_date,
            batch_time_tag,
            instrument_id,
            instrument_name,
            rank_no
        FROM insights.fact_strategy_target
        WHERE strategy_name = $1
          AND is_latest_batch = TRUE
        ORDER BY rank_no ASC NULLS LAST, instrument_id ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, strategy_name)
    return [StrategyTargetItem.model_validate(dict(row)) for row in rows]


@router.get("/{strategy_name}/actions/latest", response_model=list[StrategyActionItem])
async def get_latest_actions(
    strategy_name: str,
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[StrategyActionItem]:
    """用途：返回某策略最新批次的原始调仓动作。

    参数：
        strategy_name：策略名称。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        最新一批原始动作列表。
    异常/边界：
        若该策略尚无动作数据，则返回空列表。
    """

    query = """
        WITH latest_batch AS (
            SELECT MAX(batch_time_tag) AS batch_time_tag
            FROM insights.fact_strategy_action_raw
            WHERE strategy_name = $1
        )
        SELECT
            a.trade_date,
            a.batch_time_tag,
            a.instrument_id,
            a.action_type,
            a.reason_type,
            a.before_in_target,
            a.after_in_target,
            a.before_rank_no,
            a.after_rank_no,
            a.notes
        FROM insights.fact_strategy_action_raw a
        JOIN latest_batch lb
            ON a.batch_time_tag = lb.batch_time_tag
        WHERE a.strategy_name = $1
        ORDER BY
            CASE a.action_type
                WHEN 'BUY' THEN 1
                WHEN 'SELL' THEN 2
                ELSE 3
            END,
            a.instrument_id ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, strategy_name)
    return [StrategyActionItem.model_validate(dict(row)) for row in rows]


@router.get("/{strategy_name}/tpsl/interventions", response_model=list[TpSlInterventionItem])
async def get_tpsl_interventions(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[TpSlInterventionItem]:
    """用途：返回某策略的 TPSL 干预明细列表。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID，用于在同名策略实例间进一步过滤。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        按触发时间倒序排列的干预记录列表。
    异常/边界：
        当策略尚无 TPSL 干预时返回空列表。
    """

    query = """
        SELECT
            intent_id::text AS intent_id,
            instrument_id,
            level_type,
            level_index,
            trigger_ts,
            fill_ts,
            fill_price::float8 AS fill_price,
            filled_qty,
            next_rebalance_trade_date,
            next_target_still_holding,
            classification,
            protected_pnl::float8 AS protected_pnl,
            missed_pnl::float8 AS missed_pnl,
            net_pnl_delta::float8 AS net_pnl_delta
        FROM insights.fact_tpsl_intervention
        WHERE strategy_name = $1
          AND ($2::text IS NULL OR portfolio_id = $2)
        ORDER BY trigger_ts DESC NULLS LAST, instrument_id ASC
        LIMIT 200
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, strategy_name, portfolio_id)
    return [TpSlInterventionItem.model_validate(dict(row)) for row in rows]


@router.get("/{strategy_name}/tpsl/summary", response_model=list[TpSlSummaryItem])
async def get_tpsl_summary(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[TpSlSummaryItem]:
    """用途：返回某策略按干预分类与 level_type 聚合的 TPSL 摘要。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID，用于在同名策略实例间进一步过滤。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        聚合后的 TPSL 统计列表。
    异常/边界：
        无干预记录时返回空列表。
    """

    query = """
        SELECT
            classification,
            level_type,
            COUNT(*)::int AS event_count
        FROM insights.fact_tpsl_intervention
        WHERE strategy_name = $1
          AND ($2::text IS NULL OR portfolio_id = $2)
        GROUP BY classification, level_type
        ORDER BY classification ASC, level_type ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, strategy_name, portfolio_id)
    return [TpSlSummaryItem.model_validate(dict(row)) for row in rows]


@router.get("/{strategy_name}/lifecycles", response_model=list[PositionLifecycleItem])
async def get_position_lifecycles(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[PositionLifecycleItem]:
    """用途：返回某策略最近的持仓生命周期归因结果。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID，用于在同名策略实例间进一步过滤。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        按开仓时间倒序排列的生命周期记录列表。
    异常/边界：
        当前会返回最近 200 条，避免前端首次加载过重。
    """

    query = """
        SELECT
            portfolio_id,
            instrument_id,
            entry_ts,
            entry_price::float8 AS entry_price,
            entry_qty,
            exit_ts_actual,
            exit_price_actual::float8 AS exit_price_actual,
            exit_reason_actual,
            exit_ts_raw,
            exit_price_raw::float8 AS exit_price_raw,
            exit_reason_raw,
            pnl_actual::float8 AS pnl_actual,
            pnl_raw::float8 AS pnl_raw,
            pnl_delta::float8 AS pnl_delta,
            max_favorable_excursion::float8 AS max_favorable_excursion,
            max_adverse_excursion::float8 AS max_adverse_excursion,
            tpsl_intervened,
            raw_path_status,
            actual_path_status
        FROM insights.fact_position_lifecycle
        WHERE strategy_name = $1
          AND ($2::text IS NULL OR portfolio_id = $2)
        ORDER BY entry_ts DESC, instrument_id ASC
        LIMIT 200
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, strategy_name, portfolio_id)
    return [PositionLifecycleItem.model_validate(dict(row)) for row in rows]


@router.get("/{strategy_name}/daily", response_model=list[StrategyDailyItem])
async def get_strategy_daily(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[StrategyDailyItem]:
    """用途：返回某策略的日度绩效分析记录。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID，用于在同名策略实例间进一步过滤。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        按交易日升序排列的日度分析结果。
    异常/边界：
        当尚未执行日度同步任务时返回空列表。
    """

    query = """
        WITH scoped_daily AS (
            SELECT *
            FROM insights.fact_strategy_daily
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
        ),
        lifecycle_proxy_daily AS (
            SELECT
                strategy_name,
                portfolio_id,
                exit_ts_raw::date AS trade_date,
                COUNT(*)::int AS proxy_total_lifecycle_count_daily,
                COUNT(*) FILTER (WHERE exit_price_raw IS NOT NULL)::int AS proxy_priced_lifecycle_count_daily,
                ROUND(
                    SUM((entry_price * entry_qty)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_priced_entry_notional_daily,
                ROUND(
                    SUM(COALESCE(pnl_actual, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_realized_pnl_actual_daily,
                ROUND(
                    SUM(COALESCE(pnl_raw, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_realized_pnl_raw_daily,
                ROUND(
                    SUM(COALESCE(pnl_delta, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_delta_daily
            FROM insights.fact_position_lifecycle
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
              AND exit_ts_raw IS NOT NULL
            GROUP BY strategy_name, portfolio_id, exit_ts_raw::date
        ),
        joined AS (
            SELECT
                sd.*,
                COALESCE(lpd.proxy_total_lifecycle_count_daily, 0) AS proxy_total_lifecycle_count_daily,
                COALESCE(lpd.proxy_priced_lifecycle_count_daily, 0) AS proxy_priced_lifecycle_count_daily,
                COALESCE(lpd.proxy_priced_entry_notional_daily, 0)::float8 AS proxy_priced_entry_notional_daily,
                COALESCE(lpd.proxy_realized_pnl_actual_daily, 0)::float8 AS proxy_realized_pnl_actual_daily,
                COALESCE(lpd.proxy_realized_pnl_raw_daily, 0)::float8 AS proxy_realized_pnl_raw_daily,
                COALESCE(lpd.proxy_pnl_delta_daily, 0)::float8 AS proxy_pnl_delta_daily
            FROM scoped_daily sd
            LEFT JOIN lifecycle_proxy_daily lpd
                ON lpd.strategy_name = sd.strategy_name
               AND lpd.portfolio_id = sd.portfolio_id
               AND lpd.trade_date = sd.trade_date
        ),
        final AS (
            SELECT
                joined.*,
                SUM(proxy_total_lifecycle_count_daily) OVER (
                    PARTITION BY joined.strategy_name, joined.portfolio_id
                    ORDER BY joined.trade_date ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )::int AS proxy_total_lifecycle_count_cum,
                SUM(proxy_priced_lifecycle_count_daily) OVER (
                    PARTITION BY joined.strategy_name, joined.portfolio_id
                    ORDER BY joined.trade_date ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )::int AS proxy_priced_lifecycle_count_cum,
                ROUND(
                    SUM(proxy_priced_entry_notional_daily) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                )::float8 AS proxy_priced_entry_notional_cum,
                ROUND(
                    SUM(proxy_realized_pnl_actual_daily) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                )::float8 AS proxy_realized_pnl_actual_cum,
                ROUND(
                    SUM(proxy_realized_pnl_raw_daily) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                )::float8 AS proxy_realized_pnl_raw_cum,
                ROUND(
                    SUM(proxy_pnl_delta_daily) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                )::float8 AS proxy_pnl_delta_cum,
                ROUND(
                    SUM(COALESCE(joined.turnover_actual, 0)) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    8
                )::float8 AS turnover_actual_cum,
                ROUND(
                    SUM(COALESCE(joined.fee_total, 0)) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                )::float8 AS fee_total_cum,
                ROUND(
                    SUM(COALESCE(joined.tax_total, 0)) OVER (
                        PARTITION BY joined.strategy_name, joined.portfolio_id
                        ORDER BY joined.trade_date ASC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )::numeric,
                    6
                )::float8 AS tax_total_cum
            FROM joined
        )
        SELECT
            trade_date,
            portfolio_id,
            nav_actual::float8 AS nav_actual,
            nav_raw::float8 AS nav_raw,
            realized_pnl_actual_daily::float8 AS realized_pnl_actual_daily,
            realized_pnl_raw_daily::float8 AS realized_pnl_raw_daily,
            realized_pnl_actual_cum::float8 AS realized_pnl_actual_cum,
            realized_pnl_raw_cum::float8 AS realized_pnl_raw_cum,
            proxy_priced_entry_notional_cum,
            proxy_priced_lifecycle_count_cum,
            proxy_total_lifecycle_count_cum,
            CASE
                WHEN proxy_total_lifecycle_count_cum > 0
                    THEN ROUND(
                        (proxy_priced_lifecycle_count_cum::numeric / proxy_total_lifecycle_count_cum)::numeric,
                        4
                    )::float8
                ELSE NULL
            END AS proxy_priced_coverage_ratio_cum,
            CASE
                WHEN COALESCE(proxy_priced_entry_notional_cum, 0) > 0
                    THEN ROUND((proxy_realized_pnl_actual_cum / proxy_priced_entry_notional_cum)::numeric, 8)::float8
                ELSE NULL
            END AS proxy_return_actual_cum,
            CASE
                WHEN COALESCE(proxy_priced_entry_notional_cum, 0) > 0
                    THEN ROUND((proxy_realized_pnl_raw_cum / proxy_priced_entry_notional_cum)::numeric, 8)::float8
                ELSE NULL
            END AS proxy_return_raw_cum,
            CASE
                WHEN COALESCE(proxy_priced_entry_notional_cum, 0) > 0
                    THEN ROUND((10000 * proxy_pnl_delta_cum / proxy_priced_entry_notional_cum)::numeric, 4)::float8
                ELSE NULL
            END AS proxy_delta_bps_cum,
            CASE
                WHEN COALESCE(turnover_actual_cum, 0) > 0
                    THEN ROUND((10000 * fee_total_cum / turnover_actual_cum)::numeric, 4)::float8
                ELSE NULL
            END AS fee_drag_bps_cum,
            CASE
                WHEN COALESCE(turnover_actual_cum, 0) > 0
                    THEN ROUND((10000 * tax_total_cum / turnover_actual_cum)::numeric, 4)::float8
                ELSE NULL
            END AS tax_drag_bps_cum,
            turnover_actual::float8 AS turnover_actual,
            turnover_raw::float8 AS turnover_raw,
            fee_total::float8 AS fee_total,
            tax_total::float8 AS tax_total,
            tpsl_exit_count,
            tpsl_reentry_count,
            tpsl_positive_delta::float8 AS tpsl_positive_delta,
            tpsl_negative_delta::float8 AS tpsl_negative_delta,
            tpsl_net_delta::float8 AS tpsl_net_delta,
            position_open_count,
            position_closed_count,
            raw_exit_estimated_count
        FROM final
        ORDER BY trade_date ASC, portfolio_id ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, strategy_name, portfolio_id)
    return [StrategyDailyItem.model_validate(dict(row)) for row in rows]


@router.get("/{strategy_name}/parameter-lab", response_model=ParameterLabPayload)
async def get_parameter_lab(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> ParameterLabPayload:
    """用途：返回某策略的参数实验室聚合数据。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID，用于在同名策略实例间进一步过滤。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        包含基线方案、当前实际方案、历史实验结果和参数建议的聚合对象。
    异常/边界：
        当尚无回放实验结果时，仍会返回“原始基线 + 当前实际”两条默认方案，保证实验室页面可用。
    """

    summary_query = """
        WITH scoped_daily AS (
            SELECT *
            FROM insights.fact_strategy_daily
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
        ),
        latest_daily AS (
            SELECT *
            FROM scoped_daily
            ORDER BY trade_date DESC, portfolio_id ASC
            LIMIT 1
        ),
        intervention_stats AS (
            SELECT
                COUNT(*)::int AS total_interventions,
                COUNT(*) FILTER (WHERE COALESCE(net_pnl_delta, 0) > 0)::int AS positive_interventions,
                COUNT(*) FILTER (WHERE COALESCE(net_pnl_delta, 0) < 0)::int AS negative_interventions,
                COUNT(*) FILTER (WHERE classification = 'PRE_REBALANCE_EXIT_STILL_IN_TARGET')::int AS still_in_target_interventions,
                COUNT(*) FILTER (WHERE classification = 'PRE_REBALANCE_EXIT_REMOVED_FROM_TARGET')::int AS removed_from_target_interventions,
                COUNT(*) FILTER (WHERE classification = 'INTRADAY_EXIT_NO_NEXT_TARGET')::int AS no_next_target_interventions
            FROM insights.fact_tpsl_intervention
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
        ),
        lifecycle_stats AS (
            SELECT
                COUNT(*)::int AS total_lifecycles,
                COUNT(*) FILTER (WHERE exit_price_raw IS NOT NULL)::int AS priced_lifecycles,
                ROUND(AVG(holding_minutes_actual)::numeric, 2)::float8 AS avg_hold_minutes_actual,
                ROUND(AVG(holding_minutes_raw)::numeric, 2)::float8 AS avg_hold_minutes_raw
            FROM insights.fact_position_lifecycle
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
        ),
        lifecycle_proxy_stats AS (
            SELECT
                ROUND(
                    SUM((entry_price * entry_qty)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_priced_entry_notional,
                ROUND(
                    SUM(COALESCE(pnl_actual, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_actual_sum,
                ROUND(
                    SUM(COALESCE(pnl_raw, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_raw_sum,
                ROUND(
                    SUM(COALESCE(pnl_delta, 0)) FILTER (WHERE exit_price_raw IS NOT NULL)::numeric,
                    6
                ) AS proxy_pnl_delta_sum
            FROM insights.fact_position_lifecycle
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
        )
        SELECT
            (SELECT MIN(trade_date) FROM scoped_daily) AS date_from,
            (SELECT MAX(trade_date) FROM scoped_daily) AS date_to,
            (SELECT realized_pnl_actual_cum::float8 FROM latest_daily) AS realized_pnl_actual_cum,
            (SELECT realized_pnl_raw_cum::float8 FROM latest_daily) AS realized_pnl_raw_cum,
            (SELECT tpsl_net_delta::float8 FROM latest_daily) AS latest_tpsl_net_delta,
            (SELECT SUM(tpsl_exit_count)::int FROM scoped_daily) AS total_tpsl_exit_count,
            intervention_stats.total_interventions,
            intervention_stats.positive_interventions,
            intervention_stats.negative_interventions,
            intervention_stats.still_in_target_interventions,
            intervention_stats.removed_from_target_interventions,
            intervention_stats.no_next_target_interventions,
            lifecycle_stats.total_lifecycles,
            lifecycle_stats.priced_lifecycles,
            lifecycle_stats.avg_hold_minutes_actual,
            lifecycle_stats.avg_hold_minutes_raw,
            lifecycle_proxy_stats.proxy_priced_entry_notional::float8 AS proxy_priced_entry_notional,
            lifecycle_proxy_stats.proxy_pnl_actual_sum::float8 AS proxy_pnl_actual_sum,
            lifecycle_proxy_stats.proxy_pnl_raw_sum::float8 AS proxy_pnl_raw_sum,
            lifecycle_proxy_stats.proxy_pnl_delta_sum::float8 AS proxy_pnl_delta_sum
        FROM intervention_stats, lifecycle_stats, lifecycle_proxy_stats
    """

    counterfactual_query = """
        WITH latest_experiment AS (
            SELECT experiment_id
            FROM insights.fact_tpsl_counterfactual
            WHERE strategy_name = $1
              AND ($2::text IS NULL OR portfolio_id = $2)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
        )
        SELECT
            param_profile,
            cum_return::float8 AS cum_return,
            max_drawdown::float8 AS max_drawdown,
            win_rate::float8 AS win_rate,
            trade_count,
            tpsl_trigger_count,
            avg_hold_minutes::float8 AS avg_hold_minutes,
            net_delta_vs_baseline::float8 AS net_delta_vs_baseline,
            result_payload
        FROM insights.fact_tpsl_counterfactual
        WHERE experiment_id = (SELECT experiment_id FROM latest_experiment)
        ORDER BY param_profile ASC
    """

    async with pool.acquire() as conn:
        summary_row = await conn.fetchrow(summary_query, strategy_name, portfolio_id)
        counterfactual_rows = await conn.fetch(counterfactual_query, strategy_name, portfolio_id)

    if summary_row is None:
        diagnostics = ParameterLabDiagnosticItem(
            total_interventions=0,
            positive_interventions=0,
            negative_interventions=0,
            still_in_target_interventions=0,
            removed_from_target_interventions=0,
            no_next_target_interventions=0,
            total_lifecycles=0,
            priced_lifecycles=0,
            priced_coverage_ratio=None,
            avg_hold_minutes_actual=None,
            avg_hold_minutes_raw=None,
            actual_minus_raw_pnl=None,
            proxy_return_actual=None,
            proxy_return_raw=None,
            proxy_delta_bps=None,
            latest_tpsl_net_delta=None,
        )
        sensitivity_signal, summary, suggested_profiles = _build_parameter_recommendation(diagnostics)
        return ParameterLabPayload(
            strategy_name=strategy_name,
            portfolio_id=portfolio_id,
            date_from=None,
            date_to=None,
            has_counterfactual_results=False,
            sensitivity_signal=sensitivity_signal,
            summary=summary,
            diagnostics=diagnostics,
            scenarios=[],
            suggested_profiles=suggested_profiles,
        )

    actual_cum = _to_float(summary_row["realized_pnl_actual_cum"])
    raw_cum = _to_float(summary_row["realized_pnl_raw_cum"])
    actual_minus_raw = None
    if actual_cum is not None and raw_cum is not None:
        actual_minus_raw = round(actual_cum - raw_cum, 6)

    total_lifecycles = _to_int(summary_row["total_lifecycles"])
    priced_lifecycles = _to_int(summary_row["priced_lifecycles"])
    priced_coverage_ratio = None
    if total_lifecycles > 0:
        priced_coverage_ratio = round(priced_lifecycles / total_lifecycles, 4)

    diagnostics = ParameterLabDiagnosticItem(
        total_interventions=_to_int(summary_row["total_interventions"]),
        positive_interventions=_to_int(summary_row["positive_interventions"]),
        negative_interventions=_to_int(summary_row["negative_interventions"]),
        still_in_target_interventions=_to_int(summary_row["still_in_target_interventions"]),
        removed_from_target_interventions=_to_int(summary_row["removed_from_target_interventions"]),
        no_next_target_interventions=_to_int(summary_row["no_next_target_interventions"]),
        total_lifecycles=total_lifecycles,
        priced_lifecycles=priced_lifecycles,
        priced_coverage_ratio=priced_coverage_ratio,
        avg_hold_minutes_actual=_to_float(summary_row["avg_hold_minutes_actual"]),
        avg_hold_minutes_raw=_to_float(summary_row["avg_hold_minutes_raw"]),
        actual_minus_raw_pnl=actual_minus_raw,
        proxy_return_actual=_safe_ratio(
            _to_float(summary_row["proxy_pnl_actual_sum"]),
            _to_float(summary_row["proxy_priced_entry_notional"]),
        ),
        proxy_return_raw=_safe_ratio(
            _to_float(summary_row["proxy_pnl_raw_sum"]),
            _to_float(summary_row["proxy_priced_entry_notional"]),
        ),
        proxy_delta_bps=_safe_bps(
            _to_float(summary_row["proxy_pnl_delta_sum"]),
            _to_float(summary_row["proxy_priced_entry_notional"]),
        ),
        latest_tpsl_net_delta=_to_float(summary_row["latest_tpsl_net_delta"]),
    )
    sensitivity_signal, summary, suggested_profiles = _build_parameter_recommendation(diagnostics)

    scenarios = [
        ParameterLabScenarioItem(
            scenario_key="actual_current",
            display_name="当前实际执行",
            source_type="ACTUAL",
            param_profile="current_live",
            cum_pnl=actual_cum,
            net_delta_vs_baseline=actual_minus_raw,
            max_drawdown=None,
            win_rate=None,
            trade_count=total_lifecycles,
            tpsl_trigger_count=_to_int(summary_row["total_tpsl_exit_count"]),
            avg_hold_minutes=diagnostics.avg_hold_minutes_actual,
            note="真实发生的策略执行路径，包含 STRAT 与 TPSL 的共同作用结果。",
        ),
        ParameterLabScenarioItem(
            scenario_key="raw_baseline",
            display_name="原始未干预基线",
            source_type="RAW",
            param_profile="raw_baseline",
            cum_pnl=raw_cum,
            net_delta_vs_baseline=0.0,
            max_drawdown=None,
            win_rate=None,
            trade_count=total_lifecycles,
            tpsl_trigger_count=0,
            avg_hold_minutes=diagnostics.avg_hold_minutes_raw,
            note="按照原始调仓卖点估算的未干预路径，是评估 TPSL 是否增益的默认基线。",
        ),
    ]

    existing_profiles = {scenario.param_profile for scenario in scenarios}
    for row in counterfactual_rows:
        param_profile = str(row["param_profile"])
        if param_profile in existing_profiles:
            continue
        payload = _normalize_json_object(row["result_payload"])
        scenarios.append(
            ParameterLabScenarioItem(
                scenario_key=param_profile.lower(),
                display_name=payload.get("display_name") or str(row["param_profile"]),
                source_type="COUNTERFACTUAL",
                param_profile=param_profile,
                cum_pnl=_to_float(row["cum_return"]),
                net_delta_vs_baseline=_to_float(row["net_delta_vs_baseline"]),
                max_drawdown=_to_float(row["max_drawdown"]),
                win_rate=_to_float(row["win_rate"]),
                trade_count=_to_int(row["trade_count"]) if row["trade_count"] is not None else None,
                tpsl_trigger_count=_to_int(row["tpsl_trigger_count"]) if row["tpsl_trigger_count"] is not None else None,
                avg_hold_minutes=_to_float(row["avg_hold_minutes"]),
                note=payload.get("note"),
            )
        )
        existing_profiles.add(param_profile)

    return ParameterLabPayload(
        strategy_name=strategy_name,
        portfolio_id=portfolio_id,
        date_from=summary_row["date_from"],
        date_to=summary_row["date_to"],
        has_counterfactual_results=bool(counterfactual_rows),
        sensitivity_signal=sensitivity_signal,
        summary=summary,
        diagnostics=diagnostics,
        scenarios=scenarios,
        suggested_profiles=suggested_profiles,
    )


@router.get("/{strategy_name}/parameter-lab/symbols", response_model=list[ParameterLabSymbolItem])
async def list_parameter_lab_symbols(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    diagnosis_label: str | None = Query(default=None),
    recommended_action: str | None = Query(default=None),
    only_actionable: bool = Query(default=False),
    sort_by: str = Query(default="priority_score"),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> list[ParameterLabSymbolItem]:
    """用途：返回某策略的标的级参数实验室诊断与建议列表。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID。
        diagnosis_label：可选诊断标签过滤条件。
        recommended_action：可选建议动作过滤条件。
        only_actionable：是否只保留非 `HOLD` 的标的。
        sort_by：排序字段，支持 `priority_score`、`delta_bps`、`misfire_rate`、`confidence_score`。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        标的级参数实验室摘要列表。
    异常/边界：
        当尚未生成标的级事实表时返回空列表，前端可据此提示先执行同步任务。
    """

    async with pool.acquire() as conn:
        items = await _fetch_parameter_lab_symbol_items(
            conn,
            strategy_name=strategy_name,
            portfolio_id=portfolio_id,
            diagnosis_label=diagnosis_label,
            recommended_action=recommended_action,
            only_actionable=only_actionable,
            include_payloads=False,
        )

    filtered_items = _filter_parameter_lab_symbols(
        items,
        pricing_filter=None,
        mode_filter=None,
    )
    return _sort_parameter_lab_symbols(filtered_items, sort_by=sort_by)


@router.get("/{strategy_name}/parameter-lab/export", response_model=ParameterLabExportPayload)
async def get_parameter_lab_export(
    strategy_name: str,
    portfolio_id: str | None = Query(default=None),
    recommended_action: str | None = Query(default=None),
    only_actionable: bool = Query(default=False),
    pricing_filter: str | None = Query(default=None),
    mode_filter: str | None = Query(default=None),
    sort_by: str = Query(default="priority_score"),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> ParameterLabExportPayload:
    """用途：返回当前筛选条件下可供下游消费的标的级参数覆盖清单。

    参数：
        strategy_name：策略名称。
        portfolio_id：可选组合 ID。
        recommended_action：可选建议动作筛选条件。
        only_actionable：是否只保留非 `HOLD` 标的。
        pricing_filter：补价来源筛选，支持 `HAS_PROVISIONAL`、`DIRECT_ONLY`。
        mode_filter：建议模式筛选，支持 `LOW_SAMPLE_TRIAL`、`LOW_SAMPLE_NEEDS_PRICING`、`REGULAR`。
        sort_by：排序字段，支持 `priority_score`、`delta_bps`、`misfire_rate`、`confidence_score`。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        当前筛选结果对应的结构化导出对象。
    异常/边界：
        导出接口会继续保留过滤快照与摘要，即使当前没有任何导出候选标的。
    """

    async with pool.acquire() as conn:
        items = await _fetch_parameter_lab_symbol_items(
            conn,
            strategy_name=strategy_name,
            portfolio_id=portfolio_id,
            diagnosis_label=None,
            recommended_action=recommended_action,
            only_actionable=only_actionable,
            include_payloads=False,
        )

    filtered_items = _filter_parameter_lab_symbols(
        items,
        pricing_filter=pricing_filter,
        mode_filter=mode_filter,
    )
    sorted_items = _sort_parameter_lab_symbols(filtered_items, sort_by=sort_by)
    return _build_parameter_lab_export_payload(
        strategy_name=strategy_name,
        portfolio_id=portfolio_id,
        recommended_action=recommended_action,
        only_actionable=only_actionable,
        pricing_filter=pricing_filter,
        mode_filter=mode_filter,
        filtered_items=sorted_items,
    )


@router.get("/{strategy_name}/parameter-lab/symbols/{instrument_id}", response_model=ParameterLabSymbolDetailItem)
async def get_parameter_lab_symbol_detail(
    strategy_name: str,
    instrument_id: str,
    portfolio_id: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(get_postgres_pool),
) -> ParameterLabSymbolDetailItem:
    """用途：返回某策略某标的的参数实验室诊断详情。

    参数：
        strategy_name：策略名称。
        instrument_id：标的代码。
        portfolio_id：可选组合 ID。
        pool：通过依赖注入获得的 PostgreSQL 连接池。
    返回值：
        单标的的完整诊断与建议详情对象。
    异常/边界：
        当目标标的不存在时返回 404，避免前端误把空结果当成“样本不足”。
    """

    async with pool.acquire() as conn:
        if not await _symbol_tpsl_tables_ready(conn):
            raise HTTPException(status_code=404, detail="标的级参数实验室结果尚未生成")
        items = await _fetch_parameter_lab_symbol_items(
            conn,
            strategy_name=strategy_name,
            portfolio_id=portfolio_id,
            diagnosis_label=None,
            recommended_action=None,
            only_actionable=False,
            include_payloads=True,
        )

    item = next((current for current in items if current.instrument_id == instrument_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="未找到该标的的参数实验室结果")
    return item
