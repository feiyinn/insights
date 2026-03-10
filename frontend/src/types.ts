/**
 * 用途：描述后端策略维表接口返回的单条策略摘要。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   `metadata` 保持宽松结构，以兼容后端后续扩展字段。
 */
export interface StrategySummary {
  strategy_key: number;
  strategy_name: string;
  portfolio_id: string;
  account_id: string | null;
  tactic_id: string | null;
  mode: string;
  enabled: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * 用途：描述策略日度分析接口返回的单条记录。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   净值与收益率字段当前允许为空，等待后续完整回放接入。
 */
export interface StrategyDailyItem {
  trade_date: string;
  portfolio_id: string;
  nav_actual: number | null;
  nav_raw: number | null;
  realized_pnl_actual_daily: number | null;
  realized_pnl_raw_daily: number | null;
  realized_pnl_actual_cum: number | null;
  realized_pnl_raw_cum: number | null;
  proxy_priced_entry_notional_cum: number | null;
  proxy_priced_lifecycle_count_cum: number;
  proxy_total_lifecycle_count_cum: number;
  proxy_priced_coverage_ratio_cum: number | null;
  proxy_return_actual_cum: number | null;
  proxy_return_raw_cum: number | null;
  proxy_delta_bps_cum: number | null;
  fee_drag_bps_cum: number | null;
  tax_drag_bps_cum: number | null;
  turnover_actual: number | null;
  turnover_raw: number | null;
  fee_total: number;
  tax_total: number;
  tpsl_exit_count: number;
  tpsl_reentry_count: number;
  tpsl_positive_delta: number;
  tpsl_negative_delta: number;
  tpsl_net_delta: number;
  position_open_count: number;
  position_closed_count: number;
  raw_exit_estimated_count: number;
}

/**
 * 用途：描述 TPSL 干预明细记录。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   部分干预尚无反事实补价，因此正负贡献字段允许为空。
 */
export interface TpSlInterventionItem {
  intent_id: string;
  instrument_id: string;
  level_type: string;
  level_index: number;
  trigger_ts: string | null;
  fill_ts: string | null;
  fill_price: number | null;
  filled_qty: number | null;
  next_rebalance_trade_date: string | null;
  next_target_still_holding: boolean | null;
  classification: string;
  protected_pnl: number | null;
  missed_pnl: number | null;
  net_pnl_delta: number | null;
}

/**
 * 用途：描述持仓生命周期明细记录。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   未触发原始退出或实际退出的仓位，相关字段允许为空。
 */
export interface PositionLifecycleItem {
  portfolio_id: string;
  instrument_id: string;
  entry_ts: string;
  entry_price: number;
  entry_qty: number;
  exit_ts_actual: string | null;
  exit_price_actual: number | null;
  exit_reason_actual: string | null;
  exit_ts_raw: string | null;
  exit_price_raw: number | null;
  exit_reason_raw: string | null;
  pnl_actual: number | null;
  pnl_raw: number | null;
  pnl_delta: number | null;
  max_favorable_excursion: number | null;
  max_adverse_excursion: number | null;
  tpsl_intervened: boolean;
  raw_path_status: string;
  actual_path_status: string;
}

/**
 * 用途：描述策略目标池最新快照中的单条标的。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   排名与名称允许为空，以兼容历史数据不完整情况。
 */
export interface StrategyTargetItem {
  trade_date: string;
  batch_time_tag: string;
  instrument_id: string;
  instrument_name: string | null;
  rank_no: number | null;
}

/**
 * 用途：描述策略最新批次的原始调仓动作。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   排名与备注允许为空。
 */
export interface StrategyActionItem {
  trade_date: string;
  batch_time_tag: string;
  instrument_id: string;
  action_type: string;
  reason_type: string;
  before_in_target: boolean | null;
  after_in_target: boolean | null;
  before_rank_no: number | null;
  after_rank_no: number | null;
  notes: string | null;
}

/**
 * 用途：描述前端一次完整策略详情请求的聚合结果。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   各数组均允许为空，前端需自行处理空态。
 */
export interface StrategyDetailPayload {
  daily: StrategyDailyItem[];
  interventions: TpSlInterventionItem[];
  lifecycles: PositionLifecycleItem[];
  targets: StrategyTargetItem[];
  actions: StrategyActionItem[];
}

/**
 * 用途：描述参数实验室中的单个方案结果。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   当尚无完整回放结果时，收益风险字段允许为空。
 */
export interface ParameterLabScenarioItem {
  scenario_key: string;
  display_name: string;
  source_type: string;
  param_profile: string;
  cum_pnl: number | null;
  net_delta_vs_baseline: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  trade_count: number | null;
  tpsl_trigger_count: number | null;
  avg_hold_minutes: number | null;
  note: string | null;
}

/**
 * 用途：描述参数实验室顶部的诊断摘要。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   样本不足时比率和均值允许为空。
 */
export interface ParameterLabDiagnosticItem {
  total_interventions: number;
  positive_interventions: number;
  negative_interventions: number;
  still_in_target_interventions: number;
  removed_from_target_interventions: number;
  no_next_target_interventions: number;
  total_lifecycles: number;
  priced_lifecycles: number;
  priced_coverage_ratio: number | null;
  avg_hold_minutes_actual: number | null;
  avg_hold_minutes_raw: number | null;
  actual_minus_raw_pnl: number | null;
  proxy_return_actual: number | null;
  proxy_return_raw: number | null;
  proxy_delta_bps: number | null;
  latest_tpsl_net_delta: number | null;
}

/**
 * 用途：描述建议尝试的一组相对参数档位。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   倍数为 1.0 表示保持当前参数不变。
 */
export interface ParameterProfileSuggestionItem {
  profile_name: string;
  stance: string;
  hard_sl_multiplier: number;
  break_even_trigger_multiplier: number;
  trailing_buffer_multiplier: number;
  take_profit_trigger_multiplier: number;
  rationale: string;
}

/**
 * 用途：描述参数实验室页面的完整接口载荷。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   没有历史回放结果时，仍会返回默认的实际与原始两条方案。
 */
export interface ParameterLabPayload {
  strategy_name: string;
  portfolio_id: string | null;
  date_from: string | null;
  date_to: string | null;
  has_counterfactual_results: boolean;
  sensitivity_signal: string;
  summary: string;
  diagnostics: ParameterLabDiagnosticItem;
  scenarios: ParameterLabScenarioItem[];
  suggested_profiles: ParameterProfileSuggestionItem[];
}

/**
 * 用途：描述参数实验室中的标的级诊断与建议摘要。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   当建议结果尚未生成时，建议相关字段允许为空。
 */
export interface ParameterLabSymbolItem {
  as_of_date: string;
  date_from: string;
  date_to: string;
  strategy_name: string;
  portfolio_id: string;
  account_id: string | null;
  tactic_id: string | null;
  instrument_id: string;
  diagnosis_label: string;
  total_lifecycles: number;
  priced_lifecycles: number;
  priced_coverage_ratio: number | null;
  tpsl_intervention_count: number;
  reentry_count: number;
  pnl_delta_sum: number | null;
  return_actual_bps: number | null;
  return_raw_bps: number | null;
  delta_bps: number | null;
  misfire_rate: number | null;
  protection_efficiency: number | null;
  avg_hold_minutes_actual: number | null;
  avg_hold_minutes_raw: number | null;
  hold_gap_ratio: number | null;
  confidence_score: number | null;
  direct_priced_lifecycles: number | null;
  provisional_priced_lifecycles: number | null;
  latest_pricing_trade_date: string | null;
  source_method: string | null;
  recommendation_mode: string | null;
  recommended_action: string | null;
  recommended_profile: string | null;
  hard_sl_multiplier: number | null;
  break_even_trigger_multiplier: number | null;
  trailing_buffer_multiplier: number | null;
  take_profit_trigger_multiplier: number | null;
  expected_delta_bps: number | null;
  expected_misfire_rate: number | null;
  expected_protection_efficiency: number | null;
  priority_score: number | null;
  reason_summary: string | null;
}

/**
 * 用途：描述参数实验室中的单标的详情对象。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   详情对象在摘要字段基础上包含额外 payload，用于解释建议来源。
 */
export interface ParameterLabSymbolDetailItem extends ParameterLabSymbolItem {
  diagnostic_payload: Record<string, unknown>;
  recommendation_payload: Record<string, unknown>;
}

/**
 * 用途：描述参数实验室导出结果中的单标的覆盖项。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   当前只会导出非 HOLD 标的，因此 `recommended_action` 默认具有动作含义。
 */
export interface ParameterLabExportSymbolOverrideItem {
  instrument_id: string;
  recommended_action: string;
  recommended_profile: string | null;
  recommendation_mode: string | null;
  hard_sl_multiplier: number | null;
  break_even_trigger_multiplier: number | null;
  trailing_buffer_multiplier: number | null;
  take_profit_trigger_multiplier: number | null;
  confidence_score: number | null;
  source_method: string | null;
  reason_summary: string | null;
  direct_priced_lifecycles: number | null;
  provisional_priced_lifecycles: number | null;
  latest_pricing_trade_date: string | null;
}

/**
 * 用途：描述参数实验室导出的完整结构化清单。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   即使当前没有导出候选标的，也会返回空数组和摘要信息。
 */
export interface ParameterLabExportPayload {
  generated_at: string;
  strategy_name: string;
  portfolio_id: string | null;
  export_method: string;
  filters: Record<string, unknown>;
  summary: Record<string, unknown>;
  symbol_overrides: ParameterLabExportSymbolOverrideItem[];
}

/**
 * 用途：描述概览页中单个策略实例的聚合摘要。
 * 参数：
 *   无，类型仅用于编译期约束。
 * 返回值：
 *   无。
 * 异常/边界：
 *   收益字段允许为空，以兼容策略已建档但暂未形成分析样本的场景。
 */
export interface StrategyOverviewItem {
  strategy_name: string;
  portfolio_id: string;
  mode: string;
  enabled: boolean;
  account_id: string | null;
  tactic_id: string | null;
  latest_trade_date: string | null;
  realized_pnl_actual_cum: number | null;
  realized_pnl_raw_cum: number | null;
  proxy_priced_entry_notional: number | null;
  proxy_pnl_actual_sum: number | null;
  proxy_pnl_raw_sum: number | null;
  proxy_pnl_delta_sum: number | null;
  proxy_return_actual: number | null;
  proxy_return_raw: number | null;
  proxy_delta_bps: number | null;
  fee_drag_bps: number | null;
  tax_drag_bps: number | null;
  priced_coverage_ratio: number | null;
  priced_lifecycle_count: number;
  total_lifecycle_count: number;
  latest_tpsl_net_delta: number | null;
  total_tpsl_net_delta: number | null;
  tpsl_positive_event_count: number;
  tpsl_negative_event_count: number;
  open_position_count: number;
  latest_target_count: number;
  latest_buy_count: number;
  latest_sell_count: number;
}
