from datetime import date, datetime

from pydantic import BaseModel


class StrategyTargetItem(BaseModel):
    """用途：描述策略某批次目标池中的单个标的。

    参数：
        各字段来自 `insights.fact_strategy_target`。
    返回值：
        供 API 直接输出的目标池项对象。
    异常/边界：
        `instrument_name` 与 `rank_no` 允许为空，兼容历史数据不完整场景。
    """

    trade_date: date
    batch_time_tag: datetime
    instrument_id: str
    instrument_name: str | None
    rank_no: int | None


class StrategyActionItem(BaseModel):
    """用途：描述策略原始调仓动作的一条记录。

    参数：
        各字段来自 `insights.fact_strategy_action_raw`。
    返回值：
        供 API 直接输出的调仓动作对象。
    异常/边界：
        排名字段允许为空，以兼容买入前无旧排名或卖出后无新排名的情况。
    """

    trade_date: date
    batch_time_tag: datetime
    instrument_id: str
    action_type: str
    reason_type: str
    before_in_target: bool | None
    after_in_target: bool | None
    before_rank_no: int | None
    after_rank_no: int | None
    notes: str | None


class TpSlInterventionItem(BaseModel):
    """用途：描述一条 TPSL 干预记录。

    参数：
        各字段来自 `insights.fact_tpsl_intervention`。
    返回值：
        可直接用于前端展示的干预对象。
    异常/边界：
        下一次调仓相关字段允许为空，兼容当前暂无后续目标池的场景。
    """

    intent_id: str
    instrument_id: str
    level_type: str
    level_index: int
    trigger_ts: datetime | None
    fill_ts: datetime | None
    fill_price: float | None
    filled_qty: int | None
    next_rebalance_trade_date: date | None
    next_target_still_holding: bool | None
    classification: str
    protected_pnl: float | None
    missed_pnl: float | None
    net_pnl_delta: float | None


class TpSlSummaryItem(BaseModel):
    """用途：描述 TPSL 干预汇总视图中的一条聚合记录。

    参数：
        classification：干预归因分类。
        level_type：TPSL 类型。
        event_count：事件数。
    返回值：
        用于图表或表格展示的聚合对象。
    异常/边界：
        无。
    """

    classification: str
    level_type: str
    event_count: int


class PositionLifecycleItem(BaseModel):
    """用途：描述单次持仓生命周期的归因结果。

    参数：
        各字段来自 `insights.fact_position_lifecycle`。
    返回值：
        用于前端展示单次开仓、实际退出、原始退出估计与 TPSL 干预状态的对象。
    异常/边界：
        原始退出价格和原始收益在尚未接入历史行情时允许为空。
    """

    portfolio_id: str
    instrument_id: str
    entry_ts: datetime
    entry_price: float
    entry_qty: int
    exit_ts_actual: datetime | None
    exit_price_actual: float | None
    exit_reason_actual: str | None
    exit_ts_raw: datetime | None
    exit_price_raw: float | None
    exit_reason_raw: str | None
    pnl_actual: float | None
    pnl_raw: float | None
    pnl_delta: float | None
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    tpsl_intervened: bool
    raw_path_status: str
    actual_path_status: str


class StrategyDailyItem(BaseModel):
    """用途：描述策略日度绩效分析的一条记录。

    参数：
        各字段来自 `insights.fact_strategy_daily`。
    返回值：
        用于前端展示日度收益、换手、TPSL 干预计数与仓位状态的对象。
    异常/边界：
        `nav_*` 与 `return_*` 在缺失历史净值快照时允许为空。
    """

    trade_date: date
    portfolio_id: str
    nav_actual: float | None
    nav_raw: float | None
    realized_pnl_actual_daily: float | None
    realized_pnl_raw_daily: float | None
    realized_pnl_actual_cum: float | None
    realized_pnl_raw_cum: float | None
    proxy_priced_entry_notional_cum: float | None
    proxy_priced_lifecycle_count_cum: int
    proxy_total_lifecycle_count_cum: int
    proxy_priced_coverage_ratio_cum: float | None
    proxy_return_actual_cum: float | None
    proxy_return_raw_cum: float | None
    proxy_delta_bps_cum: float | None
    fee_drag_bps_cum: float | None
    tax_drag_bps_cum: float | None
    turnover_actual: float | None
    turnover_raw: float | None
    fee_total: float
    tax_total: float
    tpsl_exit_count: int
    tpsl_reentry_count: int
    tpsl_positive_delta: float
    tpsl_negative_delta: float
    tpsl_net_delta: float
    position_open_count: int
    position_closed_count: int
    raw_exit_estimated_count: int


class StrategyOverviewItem(BaseModel):
    """用途：描述概览页中单个策略实例的聚合摘要。

    参数：
        各字段来自策略维表、最新日度分析和最新调仓批次的聚合结果。
    返回值：
        供前端概览页直接展示的策略总览对象。
    异常/边界：
        当某策略尚无日度分析或最新批次动作时，相关字段允许为空或回退为 0。
    """

    strategy_name: str
    portfolio_id: str
    mode: str
    enabled: bool
    account_id: str | None
    tactic_id: str | None
    latest_trade_date: date | None
    realized_pnl_actual_cum: float | None
    realized_pnl_raw_cum: float | None
    proxy_priced_entry_notional: float | None
    proxy_pnl_actual_sum: float | None
    proxy_pnl_raw_sum: float | None
    proxy_pnl_delta_sum: float | None
    proxy_return_actual: float | None
    proxy_return_raw: float | None
    proxy_delta_bps: float | None
    fee_drag_bps: float | None
    tax_drag_bps: float | None
    priced_coverage_ratio: float | None
    priced_lifecycle_count: int
    total_lifecycle_count: int
    latest_tpsl_net_delta: float | None
    total_tpsl_net_delta: float | None
    tpsl_positive_event_count: int
    tpsl_negative_event_count: int
    open_position_count: int
    latest_target_count: int
    latest_buy_count: int
    latest_sell_count: int


class ParameterLabScenarioItem(BaseModel):
    """用途：描述参数实验室中的单个方案结果。

    参数：
        各字段来自当前实际路径、原始基线或历史回放实验结果。
    返回值：
        供前端实验室页面直接展示的方案对象。
    异常/边界：
        当尚无完整回放结果时，部分收益风险字段允许为空。
    """

    scenario_key: str
    display_name: str
    source_type: str
    param_profile: str
    cum_pnl: float | None
    net_delta_vs_baseline: float | None
    max_drawdown: float | None
    win_rate: float | None
    trade_count: int | None
    tpsl_trigger_count: int | None
    avg_hold_minutes: float | None
    note: str | None


class ParameterLabDiagnosticItem(BaseModel):
    """用途：描述参数实验室页面顶部的诊断摘要。

    参数：
        各字段来自日度收益、TPSL 干预和生命周期样本的聚合统计。
    返回值：
        供前端展示当前策略 TPSL 敏感度状态的摘要对象。
    异常/边界：
        当样本不足时，比例和均值字段允许为空。
    """

    total_interventions: int
    positive_interventions: int
    negative_interventions: int
    still_in_target_interventions: int
    removed_from_target_interventions: int
    no_next_target_interventions: int
    total_lifecycles: int
    priced_lifecycles: int
    priced_coverage_ratio: float | None
    avg_hold_minutes_actual: float | None
    avg_hold_minutes_raw: float | None
    actual_minus_raw_pnl: float | None
    proxy_return_actual: float | None
    proxy_return_raw: float | None
    proxy_delta_bps: float | None
    latest_tpsl_net_delta: float | None


class ParameterProfileSuggestionItem(BaseModel):
    """用途：描述参数实验室中建议尝试的一组相对参数档位。

    参数：
        各字段使用相对于当前实盘参数的倍数表达，而非绝对值。
    返回值：
        供前端显示的建议实验档位对象。
    异常/边界：
        倍数为 1.0 表示保持当前配置不变。
    """

    profile_name: str
    stance: str
    hard_sl_multiplier: float
    break_even_trigger_multiplier: float
    trailing_buffer_multiplier: float
    take_profit_trigger_multiplier: float
    rationale: str


class ParameterLabPayload(BaseModel):
    """用途：描述参数实验室页面的完整返回载荷。

    参数：
        各字段来自策略区间统计、方案对比和参数建议结果。
    返回值：
        供前端一次性渲染参数实验室页面的聚合对象。
    异常/边界：
        当尚无历史回放结果时，`has_counterfactual_results` 为 False，但基线与实际方案仍会返回。
    """

    strategy_name: str
    portfolio_id: str | None
    date_from: date | None
    date_to: date | None
    has_counterfactual_results: bool
    sensitivity_signal: str
    summary: str
    diagnostics: ParameterLabDiagnosticItem
    scenarios: list[ParameterLabScenarioItem]
    suggested_profiles: list[ParameterProfileSuggestionItem]


class ParameterLabSymbolItem(BaseModel):
    """用途：描述参数实验室中单个标的的诊断与建议摘要。

    参数：
        各字段来自 `fact_symbol_tpsl_diagnostics` 与 `fact_symbol_tpsl_recommendation` 的联合结果。
    返回值：
        供前端标的级参数实验室列表直接展示的对象。
    异常/边界：
        当尚无建议结果时，建议相关字段允许为空，并由前端回退为“保持观察”。
    """

    as_of_date: date
    date_from: date
    date_to: date
    strategy_name: str
    portfolio_id: str
    account_id: str | None
    tactic_id: str | None
    instrument_id: str
    diagnosis_label: str
    total_lifecycles: int
    priced_lifecycles: int
    priced_coverage_ratio: float | None
    tpsl_intervention_count: int
    reentry_count: int
    pnl_delta_sum: float | None
    return_actual_bps: float | None
    return_raw_bps: float | None
    delta_bps: float | None
    misfire_rate: float | None
    protection_efficiency: float | None
    avg_hold_minutes_actual: float | None
    avg_hold_minutes_raw: float | None
    hold_gap_ratio: float | None
    confidence_score: float | None
    direct_priced_lifecycles: int | None
    provisional_priced_lifecycles: int | None
    latest_pricing_trade_date: str | None
    source_method: str | None
    recommendation_mode: str | None
    recommended_action: str | None
    recommended_profile: str | None
    hard_sl_multiplier: float | None
    break_even_trigger_multiplier: float | None
    trailing_buffer_multiplier: float | None
    take_profit_trigger_multiplier: float | None
    expected_delta_bps: float | None
    expected_misfire_rate: float | None
    expected_protection_efficiency: float | None
    priority_score: float | None
    reason_summary: str | None


class ParameterLabSymbolDetailItem(ParameterLabSymbolItem):
    """用途：描述标的级参数实验室的单标的详情对象。

    参数：
        在摘要字段基础上额外包含诊断与建议的原始扩展载荷。
    返回值：
        供前端详情抽屉或详情页使用的完整对象。
    异常/边界：
        扩展载荷允许为空字典，以兼容建议表尚未生成的场景。
    """

    diagnostic_payload: dict[str, object]
    recommendation_payload: dict[str, object]


class ParameterLabExportSymbolOverrideItem(BaseModel):
    """用途：描述参数实验室导出结果中的单标的参数覆盖项。

    参数：
        各字段来自标的级建议摘要，用于下游系统消费。
    返回值：
        单标的的结构化建议对象。
    异常/边界：
        当前仅导出非 `HOLD` 标的，避免把无动作样本误当成参数覆盖项。
    """

    instrument_id: str
    recommended_action: str
    recommended_profile: str | None
    recommendation_mode: str | None
    hard_sl_multiplier: float | None
    break_even_trigger_multiplier: float | None
    trailing_buffer_multiplier: float | None
    take_profit_trigger_multiplier: float | None
    confidence_score: float | None
    source_method: str | None
    reason_summary: str | None
    direct_priced_lifecycles: int | None
    provisional_priced_lifecycles: int | None
    latest_pricing_trade_date: str | None


class ParameterLabExportPayload(BaseModel):
    """用途：描述参数实验室导出的结构化清单。

    参数：
        包含过滤快照、摘要统计与可供下游消费的标的覆盖列表。
    返回值：
        一次导出动作对应的完整结构化对象。
    异常/边界：
        导出结果即使没有候选标的，也会保留空数组与统计信息，便于下游显式识别“本轮无动作”。
    """

    generated_at: datetime
    strategy_name: str
    portfolio_id: str | None
    export_method: str
    filters: dict[str, object]
    summary: dict[str, object]
    symbol_overrides: list[ParameterLabExportSymbolOverrideItem]
