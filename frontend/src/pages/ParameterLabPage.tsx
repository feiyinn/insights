import { useEffect, useState } from "react";

import { fetchParameterLabExport, fetchParameterLabSymbolDetail, fetchParameterLabSymbols } from "../api";
import type {
  ParameterLabExportPayload,
  ParameterLabPayload,
  ParameterLabScenarioItem,
  ParameterLabSymbolDetailItem,
  ParameterLabSymbolItem,
  ParameterProfileSuggestionItem,
  StrategyOverviewItem,
} from "../types";
import { formatBps, formatMultiplier, formatNumber, formatPercent, getValueTone } from "../utils";

interface DraftProfileState {
  hardSlMultiplier: number;
  breakEvenTriggerMultiplier: number;
  trailingBufferMultiplier: number;
  takeProfitTriggerMultiplier: number;
}

interface ParameterLabPageProps {
  strategyName: string;
  portfolioId: string | null;
  overviewItem: StrategyOverviewItem | null;
  payload: ParameterLabPayload | null;
  isLoading: boolean;
  error: string | null;
  onBackToDetail: () => void;
}

type SymbolActionFilter = "ALL" | "HOLD" | "LOOSEN" | "TIGHTEN" | "CUSTOM";
type SymbolPricingFilter = "ALL" | "HAS_PROVISIONAL" | "DIRECT_ONLY";
type SymbolModeFilter = "ALL" | "LOW_SAMPLE_TRIAL" | "LOW_SAMPLE_NEEDS_PRICING" | "REGULAR";
type ExportCopyState = "IDLE" | "COPIED" | "FAILED";

/**
 * 用途：根据敏感度信号返回更直观的中文标签。
 * 参数：
 *   signal：后端返回的敏感度枚举。
 * 返回值：
 *   更适合页面展示的中文说明。
 * 异常/边界：
 *   未识别的信号统一回退为“待观察”。
 */
function getSensitivityLabel(signal: string): string {
  if (signal === "HIGH") {
    return "偏敏感";
  }
  if (signal === "DEFENSIVE") {
    return "偏防守";
  }
  if (signal === "BALANCED") {
    return "相对平衡";
  }
  return "待观察";
}

/**
 * 用途：把标的级诊断标签转换为中文展示文案。
 * 参数：
 *   label：后端返回的诊断标签。
 * 返回值：
 *   面向用户的中文标签。
 * 异常/边界：
 *   未识别标签统一回退为原始值，避免信息丢失。
 */
function getDiagnosisLabel(label: string): string {
  if (label === "OVER_SENSITIVE") {
    return "偏敏感";
  }
  if (label === "PROTECTIVE") {
    return "保护有效";
  }
  if (label === "BALANCED") {
    return "相对平衡";
  }
  if (label === "LOW_SAMPLE") {
    return "样本不足";
  }
  if (label === "MIXED") {
    return "信号混合";
  }
  return label;
}

/**
 * 用途：把建议动作转换为更直观的中文文本。
 * 参数：
 *   action：后端返回的建议动作。
 * 返回值：
 *   中文动作说明。
 * 异常/边界：
 *   空值统一回退为“保持观察”。
 */
function getActionLabel(action: string | null): string {
  if (action === "LOOSEN") {
    return "建议放宽";
  }
  if (action === "TIGHTEN") {
    return "轻微收紧";
  }
  if (action === "CUSTOM") {
    return "人工复核";
  }
  return "保持观察";
}

/**
 * 用途：根据建议动作返回适合当前语义的胶囊样式类名。
 * 参数：
 *   action：后端返回的建议动作。
 * 返回值：
 *   页面上用于强调建议动作的样式类名。
 * 异常/边界：
 *   未知动作统一回退为 `pill-hold`。
 */
function getActionPillClass(action: string | null): string {
  if (action === "LOOSEN" || action === "CUSTOM") {
    return "pill-alert";
  }
  if (action === "TIGHTEN") {
    return "pill-sell";
  }
  return "pill-hold";
}

/**
 * 用途：根据诊断标签返回适合页面展示的胶囊样式类名。
 * 参数：
 *   label：标的级诊断标签。
 * 返回值：
 *   页面胶囊样式类名。
 * 异常/边界：
 *   未知标签统一回退为 `pill-hold`。
 */
function getDiagnosisPillClass(label: string): string {
  if (label === "OVER_SENSITIVE" || label === "MIXED") {
    return "pill-alert";
  }
  if (label === "PROTECTIVE") {
    return "pill-buy";
  }
  return "pill-hold";
}

/**
 * 用途：根据置信度返回更适合阅读的中文等级。
 * 参数：
 *   confidence：0 到 1 之间的置信度数值。
 * 返回值：
 *   “高置信 / 中置信 / 低置信 / 待补样本”。
 * 异常/边界：
 *   空值统一视为待补样本。
 */
function getConfidenceLabel(confidence: number | null): string {
  if (confidence === null) {
    return "待补样本";
  }
  if (confidence >= 0.75) {
    return "高置信";
  }
  if (confidence >= 0.45) {
    return "中置信";
  }
  return "低置信";
}

/**
 * 用途：从宽松结构的 payload 中安全读取对象字段。
 * 参数：
 *   payload：后端返回的扩展载荷。
 *   key：目标字段名。
 * 返回值：
 *   若字段存在且为对象，则返回该对象；否则返回空对象。
 * 异常/边界：
 *   该函数只做运行时兜底，不负责校验对象内部字段是否齐全。
 */
function getPayloadObject(payload: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = payload[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

/**
 * 用途：从宽松结构的 payload 中安全读取数字字段。
 * 参数：
 *   payload：后端返回的扩展载荷。
 *   key：目标字段名。
 * 返回值：
 *   数字值，或 `null`。
 * 异常/边界：
 *   字段不存在、类型不是数字时统一返回 `null`。
 */
function getPayloadNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" ? value : null;
}

/**
 * 用途：从宽松结构的 payload 中安全读取字符串字段。
 * 参数：
 *   payload：后端返回的扩展载荷。
 *   key：目标字段名。
 * 返回值：
 *   字符串值，或 `null`。
 * 异常/边界：
 *   字段不存在或不是字符串时返回 `null`。
 */
function getPayloadString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" ? value : null;
}

/**
 * 用途：把建议 payload 中的模式字段转换为更直观的中文标签。
 * 参数：
 *   mode：建议 payload 中的模式字段。
 * 返回值：
 *   中文说明。
 * 异常/边界：
 *   未识别模式统一回退为“常规启发式建议”。
 */
function getRecommendationModeLabel(mode: string | null): string {
  if (mode === "LOW_SAMPLE_TRIAL") {
    return "低样本试验建议";
  }
  if (mode === "LOW_SAMPLE_NEEDS_PRICING") {
    return "待补价复核";
  }
  return "常规启发式建议";
}

/**
 * 用途：把补价来源筛选值转换为中文展示文案。
 * 参数：
 *   pricingFilter：当前补价来源筛选值。
 * 返回值：
 *   页面上更易理解的中文标签。
 * 异常/边界：
 *   未识别值统一回退为“全部补价来源”。
 */
function getPricingFilterLabel(pricingFilter: SymbolPricingFilter): string {
  if (pricingFilter === "HAS_PROVISIONAL") {
    return "含临时盯市";
  }
  if (pricingFilter === "DIRECT_ONLY") {
    return "仅直接补价";
  }
  return "全部补价来源";
}

/**
 * 用途：把建议模式筛选值转换为中文展示文案。
 * 参数：
 *   modeFilter：当前建议模式筛选值。
 * 返回值：
 *   页面上更易理解的中文标签。
 * 异常/边界：
 *   未识别值统一回退为“全部建议模式”。
 */
function getModeFilterLabel(modeFilter: SymbolModeFilter): string {
  if (modeFilter === "LOW_SAMPLE_TRIAL") {
    return "低样本试验建议";
  }
  if (modeFilter === "LOW_SAMPLE_NEEDS_PRICING") {
    return "待补价复核";
  }
  if (modeFilter === "REGULAR") {
    return "常规启发式建议";
  }
  return "全部建议模式";
}

/**
 * 用途：生成参数实验室导出文件名。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：组合 ID。
 * 返回值：
 *   适合下载 JSON 文件的文件名。
 * 异常/边界：
 *   文件名中的特殊字符会被替换为下划线，避免浏览器下载时报错。
 */
function buildExportFileName(strategyName: string, portfolioId: string | null, generatedAt: string | null): string {
  const normalizedStrategy = strategyName.replace(/[^a-zA-Z0-9\u4e00-\u9fa5_-]/g, "_");
  const normalizedPortfolio = (portfolioId ?? "all").replace(/[^a-zA-Z0-9_-]/g, "_");
  const normalizedTimestamp = (generatedAt ?? new Date().toISOString())
    .replace(/[:.]/g, "-")
    .replace("T", "_")
    .replace("Z", "");
  return `${normalizedStrategy}_${normalizedPortfolio}_symbol_overrides_${normalizedTimestamp}.json`;
}

/**
 * 用途：判断单个标的是否满足当前筛选条件。
 * 参数：
 *   item：标的级摘要项。
 *   actionFilter：建议动作筛选。
 *   pricingFilter：补价来源筛选。
 *   modeFilter：建议模式筛选。
 * 返回值：
 *   是否命中筛选条件。
 * 异常/边界：
 *   空值字段统一按“无额外说明”处理，避免把缺失值误判为命中某类筛选。
 */
function matchesSymbolFilters(
  item: ParameterLabSymbolItem,
  actionFilter: SymbolActionFilter,
  pricingFilter: SymbolPricingFilter,
  modeFilter: SymbolModeFilter,
): boolean {
  if (actionFilter !== "ALL" && (item.recommended_action ?? "HOLD") !== actionFilter) {
    return false;
  }

  const provisionalCount = item.provisional_priced_lifecycles ?? 0;
  const directCount = item.direct_priced_lifecycles ?? 0;
  if (pricingFilter === "HAS_PROVISIONAL" && provisionalCount <= 0) {
    return false;
  }
  if (pricingFilter === "DIRECT_ONLY" && (provisionalCount > 0 || directCount <= 0)) {
    return false;
  }

  const recommendationMode = item.recommendation_mode;
  if (modeFilter === "LOW_SAMPLE_TRIAL" && recommendationMode !== "LOW_SAMPLE_TRIAL") {
    return false;
  }
  if (modeFilter === "LOW_SAMPLE_NEEDS_PRICING" && recommendationMode !== "LOW_SAMPLE_NEEDS_PRICING") {
    return false;
  }
  if (modeFilter === "REGULAR" && recommendationMode !== null) {
    return false;
  }

  return true;
}

/**
 * 用途：根据草案参数与当前策略诊断结果生成实验提示。
 * 参数：
 *   draft：前端本地维护的参数草案。
 *   signal：后端返回的敏感度信号。
 * 返回值：
 *   面向用户的简洁实验提示文案。
 * 异常/边界：
 *   这里只做方向性提示，不会伪装成真实回放结果。
 */
function buildDraftHint(draft: DraftProfileState, signal: string): string {
  const averageMultiplier =
    (draft.hardSlMultiplier +
      draft.breakEvenTriggerMultiplier +
      draft.trailingBufferMultiplier +
      draft.takeProfitTriggerMultiplier) /
    4;

  if (signal === "HIGH" && averageMultiplier > 1.05) {
    return "这组草案整体偏放宽，和当前“偏敏感”的诊断方向一致，适合优先作为第一批实验档位。";
  }
  if (signal === "DEFENSIVE" && averageMultiplier < 0.98) {
    return "这组草案整体偏收紧，适合验证当前正向保护是否还能继续提升回撤控制。";
  }
  if (averageMultiplier > 1.03) {
    return "这组草案会提升持仓容忍度，更适合检验是否存在提前止盈止损的问题。";
  }
  if (averageMultiplier < 0.98) {
    return "这组草案会提升风控灵敏度，更适合检验回撤是否还能进一步压缩。";
  }
  return "这组草案接近当前实盘参数，适合作为中心对照组或微调试验。";
}

/**
 * 用途：渲染单个方案卡片。
 * 参数：
 *   scenario：实验场景数据。
 * 返回值：
 *   参数实验室中的方案卡片节点。
 * 异常/边界：
 *   部分指标为空时展示为 `--`，避免误导用户认为数据已回放完成。
 */
function ScenarioCard({ scenario }: { scenario: ParameterLabScenarioItem }) {
  return (
    <article className="panel scenario-card">
      <div className="scenario-card-head">
        <div>
          <p className="eyebrow">{scenario.source_type}</p>
          <h3>{scenario.display_name}</h3>
          <p className="spotlight-helper">{scenario.param_profile}</p>
        </div>
        <span className={`pill ${scenario.source_type === "COUNTERFACTUAL" ? "pill-hold" : "pill-alert"}`}>
          {scenario.source_type === "COUNTERFACTUAL" ? "回放结果" : "当前样本"}
        </span>
      </div>

      <div className="scenario-metric-grid">
        <div>
          <span>累计收益</span>
          <strong className={getValueTone(scenario.cum_pnl)}>{formatNumber(scenario.cum_pnl)}</strong>
        </div>
        <div>
          <span>相对基线</span>
          <strong className={getValueTone(scenario.net_delta_vs_baseline)}>{formatNumber(scenario.net_delta_vs_baseline)}</strong>
        </div>
        <div>
          <span>TPSL 触发次数</span>
          <strong>{formatNumber(scenario.tpsl_trigger_count)}</strong>
        </div>
        <div>
          <span>平均持有分钟</span>
          <strong>{formatNumber(scenario.avg_hold_minutes)}</strong>
        </div>
      </div>

      <p className="spotlight-helper">{scenario.note ?? "当前场景暂无补充说明。"}</p>
    </article>
  );
}

/**
 * 用途：渲染参数建议卡片。
 * 参数：
 *   profile：后端返回的推荐档位。
 * 返回值：
 *   单个建议参数档位卡片。
 * 异常/边界：
 *   所有参数均按相对倍数展示，避免误读为绝对生产配置。
 */
function SuggestionCard({ profile }: { profile: ParameterProfileSuggestionItem }) {
  return (
    <article className="panel suggestion-card">
      <div className="scenario-card-head">
        <div>
          <p className="eyebrow">建议档位</p>
          <h3>{profile.profile_name}</h3>
        </div>
        <span className="pill pill-hold">{profile.stance}</span>
      </div>

      <div className="scenario-metric-grid">
        <div>
          <span>硬止损倍数</span>
          <strong>{formatMultiplier(profile.hard_sl_multiplier)}</strong>
        </div>
        <div>
          <span>保本触发倍数</span>
          <strong>{formatMultiplier(profile.break_even_trigger_multiplier)}</strong>
        </div>
        <div>
          <span>跟踪止损倍数</span>
          <strong>{formatMultiplier(profile.trailing_buffer_multiplier)}</strong>
        </div>
        <div>
          <span>止盈触发倍数</span>
          <strong>{formatMultiplier(profile.take_profit_trigger_multiplier)}</strong>
        </div>
      </div>

      <p className="spotlight-helper">{profile.rationale}</p>
    </article>
  );
}

/**
 * 用途：渲染标的级详情卡片。
 * 参数：
 *   detail：当前选中的单标的详情。
 *   isLoading：是否正在加载详情。
 *   error：详情错误信息。
 * 返回值：
 *   标的级参数建议详情节点。
 * 异常/边界：
 *   当尚未选择标的时返回引导态；当加载失败时返回错误态。
 */
function SymbolDetailCard({
  detail,
  isLoading,
  error,
}: {
  detail: ParameterLabSymbolDetailItem | null;
  isLoading: boolean;
  error: string | null;
}) {
  if (error) {
    return <div className="error-banner">{error}</div>;
  }
  if (isLoading) {
    return <div className="loading-card">正在加载标的级建议详情…</div>;
  }
  if (!detail) {
    return <div className="empty-state">从左侧先选一个标的，就能看到更细的 TPSL 行为诊断与建议倍数。</div>;
  }

  const pricingPayload = getPayloadObject(detail.diagnostic_payload, "pricing");
  const recommendationBasis = getPayloadObject(detail.recommendation_payload, "basis");
  const directPricedLifecycles = getPayloadNumber(pricingPayload, "direct_priced_lifecycles");
  const provisionalPricedLifecycles = getPayloadNumber(pricingPayload, "provisional_priced_lifecycles");
  const latestTradeDate = getPayloadString(pricingPayload, "latest_trade_date");
  const recommendationMode = getRecommendationModeLabel(getPayloadString(detail.recommendation_payload, "mode"));
  const severityScore = getPayloadNumber(detail.recommendation_payload, "severity_score");

  return (
    <div className="symbol-detail-stack">
      <div className="scenario-card-head">
        <div>
          <p className="eyebrow">标的级建议</p>
          <h3>{detail.instrument_id}</h3>
          <p className="spotlight-helper">
            样本窗口：{detail.date_from} 到 {detail.date_to}
          </p>
        </div>
        <div className="symbol-pill-stack">
          <span className={`pill ${getDiagnosisPillClass(detail.diagnosis_label)}`}>{getDiagnosisLabel(detail.diagnosis_label)}</span>
          <span className={`pill ${getActionPillClass(detail.recommended_action)}`}>{getActionLabel(detail.recommended_action)}</span>
        </div>
      </div>

      <p className="spotlight-helper">
        {detail.reason_summary ?? "当前还没有形成明确建议，先继续观察更多标的级样本。"}
      </p>

      <div className="explain-grid">
        <article className="explain-card">
          <span>建议模式</span>
          <strong>{recommendationMode}</strong>
          <small>
            方法：{detail.source_method ?? "symbol_proxy_heuristic_v1"}
            {severityScore !== null ? ` · 严重度 ${formatPercent(severityScore)}` : ""}
          </small>
        </article>
        <article className="explain-card">
          <span>补价构成</span>
          <strong>
            直接补价 {formatNumber(directPricedLifecycles, "--")} / 临时盯市 {formatNumber(provisionalPricedLifecycles, "--")}
          </strong>
          <small>{latestTradeDate ? `临时盯市截止 ${latestTradeDate}` : "当前未使用临时盯市补价"}</small>
        </article>
      </div>

      <div className="scenario-metric-grid">
        <div>
          <span>净影响</span>
          <strong className={getValueTone(detail.delta_bps)}>{formatBps(detail.delta_bps)}</strong>
        </div>
        <div>
          <span>金额影响</span>
          <strong className={getValueTone(detail.pnl_delta_sum)}>{formatNumber(detail.pnl_delta_sum)}</strong>
        </div>
        <div>
          <span>误杀率</span>
          <strong>{formatPercent(detail.misfire_rate)}</strong>
        </div>
        <div>
          <span>保护效率</span>
          <strong>{formatPercent(detail.protection_efficiency)}</strong>
        </div>
        <div>
          <span>实际收益效率</span>
          <strong>{formatBps(detail.return_actual_bps)}</strong>
        </div>
        <div>
          <span>原始基线效率</span>
          <strong>{formatBps(detail.return_raw_bps)}</strong>
        </div>
      </div>

      <div className="summary-stack">
        <div className="summary-row">
          <span>建议档位</span>
          <strong>{detail.recommended_profile ?? "symbol_hold"}</strong>
        </div>
        <div className="summary-row">
          <span>置信度</span>
          <strong>{getConfidenceLabel(detail.confidence_score)} · {formatPercent(detail.confidence_score)}</strong>
        </div>
        <div className="summary-row">
          <span>生命周期覆盖</span>
          <strong>
            {detail.priced_lifecycles}/{detail.total_lifecycles} · {formatPercent(detail.priced_coverage_ratio)}
          </strong>
        </div>
        <div className="summary-row">
          <span>TPSL 干预 / 回补</span>
          <strong>
            {detail.tpsl_intervention_count} / {detail.reentry_count}
          </strong>
        </div>
        <div className="summary-row">
          <span>实际持有偏差</span>
          <strong className={getValueTone(detail.hold_gap_ratio)}>{formatPercent(detail.hold_gap_ratio)}</strong>
        </div>
      </div>

      <div className="summary-stack">
        <div className="summary-row">
          <span>建议依据</span>
          <strong>
            净影响 {formatBps(getPayloadNumber(recommendationBasis, "delta_bps"))} / 误杀率{" "}
            {formatPercent(getPayloadNumber(recommendationBasis, "misfire_rate"))}
          </strong>
        </div>
        <div className="summary-row">
          <span>回补与持有信号</span>
          <strong>
            回补 {formatNumber(getPayloadNumber(recommendationBasis, "reentry_count"))} / 持有偏差{" "}
            {formatPercent(getPayloadNumber(recommendationBasis, "hold_gap_ratio"))}
          </strong>
        </div>
      </div>

      <div className="draft-form-grid">
        <div className="field-card">
          <span>硬止损倍数</span>
          <strong>{formatMultiplier(detail.hard_sl_multiplier)}</strong>
        </div>
        <div className="field-card">
          <span>保本触发倍数</span>
          <strong>{formatMultiplier(detail.break_even_trigger_multiplier)}</strong>
        </div>
        <div className="field-card">
          <span>跟踪止损倍数</span>
          <strong>{formatMultiplier(detail.trailing_buffer_multiplier)}</strong>
        </div>
        <div className="field-card">
          <span>止盈触发倍数</span>
          <strong>{formatMultiplier(detail.take_profit_trigger_multiplier)}</strong>
        </div>
      </div>

      <div className="summary-row highlight">
        <span>预估改善方向</span>
        <strong>
          {formatBps(detail.expected_delta_bps)} / 误杀率 {formatPercent(detail.expected_misfire_rate)} / 保护效率{" "}
          {formatPercent(detail.expected_protection_efficiency)}
        </strong>
      </div>
    </div>
  );
}

/**
 * 用途：渲染参数实验室页面。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：组合 ID。
 *   overviewItem：首页中的策略摘要。
 *   payload：后端返回的参数实验室聚合载荷。
 *   isLoading：是否正在加载。
 *   error：错误信息。
 *   onBackToDetail：返回策略详情页的回调。
 * 返回值：
 *   包含实验场景、诊断摘要、建议档位、自定义草案与标的级实验室的完整页面。
 * 异常/边界：
 *   当暂无回放结果时，页面仍可使用基线场景和建议档位完成分析。
 */
export function ParameterLabPage({
  strategyName,
  portfolioId,
  overviewItem,
  payload,
  isLoading,
  error,
  onBackToDetail,
}: ParameterLabPageProps) {
  const [draft, setDraft] = useState<DraftProfileState>({
    hardSlMultiplier: 1.0,
    breakEvenTriggerMultiplier: 1.0,
    trailingBufferMultiplier: 1.0,
    takeProfitTriggerMultiplier: 1.0,
  });
  const [symbolItems, setSymbolItems] = useState<ParameterLabSymbolItem[]>([]);
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ParameterLabSymbolDetailItem | null>(null);
  const [onlyActionable, setOnlyActionable] = useState(false);
  const [actionFilter, setActionFilter] = useState<SymbolActionFilter>("ALL");
  const [pricingFilter, setPricingFilter] = useState<SymbolPricingFilter>("ALL");
  const [modeFilter, setModeFilter] = useState<SymbolModeFilter>("ALL");
  const [isSymbolsLoading, setIsSymbolsLoading] = useState(false);
  const [isSymbolDetailLoading, setIsSymbolDetailLoading] = useState(false);
  const [isExportLoading, setIsExportLoading] = useState(false);
  const [symbolsError, setSymbolsError] = useState<string | null>(null);
  const [symbolDetailError, setSymbolDetailError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportPayload, setExportPayload] = useState<ParameterLabExportPayload | null>(null);
  const [copyState, setCopyState] = useState<ExportCopyState>("IDLE");

  const filteredSymbolItems = symbolItems.filter((item) =>
    matchesSymbolFilters(item, actionFilter, pricingFilter, modeFilter),
  );
  const actionableSymbolCount = symbolItems.filter((item) => (item.recommended_action ?? "HOLD") !== "HOLD").length;
  const loosenSymbolCount = symbolItems.filter((item) => item.recommended_action === "LOOSEN").length;
  const provisionalPricingSymbolCount = symbolItems.filter((item) => (item.provisional_priced_lifecycles ?? 0) > 0).length;
  const lowSampleTrialCount = symbolItems.filter((item) => item.recommendation_mode === "LOW_SAMPLE_TRIAL").length;
  const confidenceSamples = symbolItems.filter((item) => item.confidence_score !== null);
  const averageSymbolConfidence =
    confidenceSamples.length > 0
      ? confidenceSamples.reduce((sum, item) => sum + (item.confidence_score ?? 0), 0) / confidenceSamples.length
      : null;
  const exportSummary = exportPayload?.summary ?? {};
  const exportOverrideCount = getPayloadNumber(exportSummary, "exported_overrides");
  const exportFilteredCount = getPayloadNumber(exportSummary, "filtered_symbols");
  const exportProvisionalCount = getPayloadNumber(exportSummary, "provisional_pricing_symbols");
  const exportAverageConfidence = getPayloadNumber(exportSummary, "average_confidence_score");
  const exportPreview = exportPayload ? JSON.stringify(exportPayload, null, 2) : "";

  useEffect(() => {
    let cancelled = false;
    setIsSymbolsLoading(true);
    setSymbolsError(null);

    /**
     * 用途：加载当前策略的标的级参数实验室摘要列表。
     * 参数：
     *   无。
     * 返回值：
     *   无。
     * 异常/边界：
     *   当后端尚未生成标的级事实表时，会把错误展示在页面局部区域，不影响策略级实验室使用。
     */
    async function loadSymbols() {
      try {
        const result = await fetchParameterLabSymbols(strategyName, portfolioId, onlyActionable);
        if (cancelled) {
          return;
        }
        setSymbolItems(result);
        setSymbolsError(null);
        setSelectedInstrumentId((current) => {
          const nextFilteredItems = result.filter((item) =>
            matchesSymbolFilters(item, actionFilter, pricingFilter, modeFilter),
          );
          if (current && nextFilteredItems.some((item) => item.instrument_id === current)) {
            return current;
          }
          return nextFilteredItems[0]?.instrument_id ?? null;
        });
        if (result.length === 0) {
          setSelectedDetail(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          setSymbolItems([]);
          setSelectedInstrumentId(null);
          setSelectedDetail(null);
          setSymbolsError(loadError instanceof Error ? loadError.message : "标的级参数实验室加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsSymbolsLoading(false);
        }
      }
    }

    loadSymbols();
    return () => {
      cancelled = true;
    };
  }, [strategyName, portfolioId, onlyActionable, actionFilter, pricingFilter, modeFilter]);

  useEffect(() => {
    if (filteredSymbolItems.length === 0) {
      setSelectedInstrumentId(null);
      setSelectedDetail(null);
      return;
    }
    if (!selectedInstrumentId || !filteredSymbolItems.some((item) => item.instrument_id === selectedInstrumentId)) {
      setSelectedInstrumentId(filteredSymbolItems[0]?.instrument_id ?? null);
    }
  }, [filteredSymbolItems, selectedInstrumentId]);

  useEffect(() => {
    if (!selectedInstrumentId) {
      setSelectedDetail(null);
      setSymbolDetailError(null);
      return;
    }

    const instrumentId = selectedInstrumentId;
    let cancelled = false;
    setIsSymbolDetailLoading(true);
    setSymbolDetailError(null);

    /**
     * 用途：加载当前选中标的的参数实验室详情。
     * 参数：
     *   无。
     * 返回值：
     *   无。
     * 异常/边界：
     *   切换标的时会中断旧请求结果写入，避免详情卡串页。
     */
    async function loadSymbolDetail() {
      try {
        const result = await fetchParameterLabSymbolDetail(strategyName, instrumentId, portfolioId);
        if (cancelled) {
          return;
        }
        setSelectedDetail(result);
        setSymbolDetailError(null);
      } catch (loadError) {
        if (!cancelled) {
          setSelectedDetail(null);
          setSymbolDetailError(loadError instanceof Error ? loadError.message : "标的详情加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsSymbolDetailLoading(false);
        }
      }
    }

    loadSymbolDetail();
    return () => {
      cancelled = true;
    };
  }, [strategyName, portfolioId, selectedInstrumentId]);

  useEffect(() => {
    let cancelled = false;
    setIsExportLoading(true);
    setExportError(null);
    setCopyState("IDLE");

    /**
     * 用途：按当前页面筛选条件加载结构化导出结果。
     * 参数：
     *   无。
     * 返回值：
     *   无。
     * 异常/边界：
     *   当标的级事实表尚未生成时，接口会返回空导出结果，不阻断页面其余功能。
     */
    async function loadExportPayload() {
      try {
        const result = await fetchParameterLabExport(
          strategyName,
          portfolioId,
          onlyActionable,
          actionFilter,
          pricingFilter,
          modeFilter,
        );
        if (cancelled) {
          return;
        }
        setExportPayload(result);
        setExportError(null);
      } catch (loadError) {
        if (!cancelled) {
          setExportPayload(null);
          setExportError(loadError instanceof Error ? loadError.message : "导出清单加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsExportLoading(false);
        }
      }
    }

    loadExportPayload();
    return () => {
      cancelled = true;
    };
  }, [strategyName, portfolioId, onlyActionable, actionFilter, pricingFilter, modeFilter]);

  /**
   * 用途：把当前导出 JSON 复制到系统剪贴板。
   * 参数：
   *   无。
   * 返回值：
   *   无。
   * 异常/边界：
   *   当浏览器不支持剪贴板接口或复制失败时，会把状态切换为失败提示。
   */
  async function handleCopyExport(): Promise<void> {
    if (!exportPreview || !navigator.clipboard) {
      setCopyState("FAILED");
      return;
    }
    try {
      await navigator.clipboard.writeText(exportPreview);
      setCopyState("COPIED");
    } catch {
      setCopyState("FAILED");
    }
  }

  /**
   * 用途：把当前导出 JSON 下载为本地文件。
   * 参数：
   *   无。
   * 返回值：
   *   无。
   * 异常/边界：
   *   当当前没有导出结果时直接返回，不触发空文件下载。
   */
  function handleDownloadExport(): void {
    if (!exportPayload || !exportPreview) {
      return;
    }
    const blob = new Blob([exportPreview], { type: "application/json;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = buildExportFileName(strategyName, portfolioId, exportPayload.generated_at);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }

  return (
    <main className="main-content">
      <section className="hero panel">
        <div>
          <button className="back-link" type="button" onClick={onBackToDetail}>
            返回策略详情
          </button>
          <p className="eyebrow">参数实验室</p>
          <h2>{strategyName}</h2>
          <p className="hero-copy">
            {payload
              ? payload.summary
              : "正在加载参数实验室，请稍等片刻。"}
          </p>
        </div>
        <div className="hero-meta">
          <span>组合：{portfolioId ?? overviewItem?.portfolio_id ?? "--"}</span>
          <span>模式：{overviewItem?.mode ?? "--"}</span>
          <span>
            样本区间：
            {payload?.date_from ?? "--"} 到 {payload?.date_to ?? "--"}
          </span>
        </div>
      </section>

      {error ? <section className="panel error-banner">{error}</section> : null}
      {isLoading ? <section className="panel loading-card">正在准备参数实验室数据…</section> : null}

      {payload ? (
        <>
          <section className="card-grid">
            <article className="metric-card panel">
              <p className="metric-label">敏感度信号</p>
              <strong className="metric-value">{getSensitivityLabel(payload.sensitivity_signal)}</strong>
              <small>结合实际路径、原始基线与干预分类后给出的当前判断</small>
            </article>
            <article className="metric-card panel">
              <p className="metric-label">TPSL 单位资金净影响</p>
              <strong className={`metric-value ${getValueTone(payload.diagnostics.proxy_delta_bps)}`}>
                {formatBps(payload.diagnostics.proxy_delta_bps)}
              </strong>
              <small>
                实际收益效率{" "}
                {formatBps(
                  payload.diagnostics.proxy_return_actual === null ? null : payload.diagnostics.proxy_return_actual * 10000,
                )}{" "}
                / 原始收益效率{" "}
                {formatBps(
                  payload.diagnostics.proxy_return_raw === null ? null : payload.diagnostics.proxy_return_raw * 10000,
                )}
              </small>
            </article>
            <article className="metric-card panel">
              <p className="metric-label">实际相对原始金额差</p>
              <strong className={`metric-value ${getValueTone(payload.diagnostics.actual_minus_raw_pnl)}`}>
                {formatNumber(payload.diagnostics.actual_minus_raw_pnl)}
              </strong>
              <small>继续保留金额口径，回答“真实赚了多少钱、TPSL 影响了多少金额”</small>
            </article>
            <article className="metric-card panel">
              <p className="metric-label">仍在目标池内的干预占比</p>
              <strong className="metric-value">
                {formatPercent(
                  payload.diagnostics.total_interventions
                    ? payload.diagnostics.still_in_target_interventions / payload.diagnostics.total_interventions
                    : null,
                )}
              </strong>
              <small>这个占比越高，越值得警惕“风控过敏、提前打断趋势”的问题</small>
            </article>
            <article className="metric-card panel">
              <p className="metric-label">原始路径补价覆盖率</p>
              <strong className="metric-value">{formatPercent(payload.diagnostics.priced_coverage_ratio)}</strong>
              <small>覆盖率越高，实验判断越稳；当前回放结果数量也会更可信</small>
            </article>
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">方案对比</p>
                <h3>当前实际路径、原始基线与历史实验结果</h3>
              </div>
              <span className="section-meta">
                {payload.has_counterfactual_results ? "已接入历史实验结果" : "当前仅有默认基线场景"}
              </span>
            </header>
            <div className="scenario-grid">
              {payload.scenarios.map((scenario) => (
                <ScenarioCard key={scenario.scenario_key} scenario={scenario} />
              ))}
            </div>
          </section>

          <section className="two-column">
            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">诊断拆解</p>
                  <h3>为什么建议这样调参</h3>
                </div>
              </header>
              <div className="summary-stack">
                <div className="summary-row">
                  <span>总干预数</span>
                  <strong>{payload.diagnostics.total_interventions}</strong>
                </div>
                <div className="summary-row">
                  <span>正贡献干预</span>
                  <strong className="is-positive">{payload.diagnostics.positive_interventions}</strong>
                </div>
                <div className="summary-row">
                  <span>负贡献干预</span>
                  <strong className="is-negative">{payload.diagnostics.negative_interventions}</strong>
                </div>
                <div className="summary-row">
                  <span>仍在目标池内被卖出</span>
                  <strong>{payload.diagnostics.still_in_target_interventions}</strong>
                </div>
                <div className="summary-row">
                  <span>下一次本来也会卖</span>
                  <strong>{payload.diagnostics.removed_from_target_interventions}</strong>
                </div>
                <div className="summary-row">
                  <span>无下一批目标池样本</span>
                  <strong>{payload.diagnostics.no_next_target_interventions}</strong>
                </div>
              </div>
            </section>

            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">自定义草案</p>
                  <h3>先记录你想试的相对倍数</h3>
                </div>
                <span className="section-meta">当前页面只做草案比较，不直接触发回放</span>
              </header>
              <div className="draft-form-grid">
                <label className="field-card">
                  <span>硬止损倍数</span>
                  <input
                    className="field-input"
                    type="number"
                    step="0.01"
                    value={draft.hardSlMultiplier}
                    onChange={(event) => setDraft((current) => ({ ...current, hardSlMultiplier: Number(event.target.value) }))}
                  />
                </label>
                <label className="field-card">
                  <span>保本触发倍数</span>
                  <input
                    className="field-input"
                    type="number"
                    step="0.01"
                    value={draft.breakEvenTriggerMultiplier}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, breakEvenTriggerMultiplier: Number(event.target.value) }))
                    }
                  />
                </label>
                <label className="field-card">
                  <span>跟踪止损倍数</span>
                  <input
                    className="field-input"
                    type="number"
                    step="0.01"
                    value={draft.trailingBufferMultiplier}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, trailingBufferMultiplier: Number(event.target.value) }))
                    }
                  />
                </label>
                <label className="field-card">
                  <span>止盈触发倍数</span>
                  <input
                    className="field-input"
                    type="number"
                    step="0.01"
                    value={draft.takeProfitTriggerMultiplier}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, takeProfitTriggerMultiplier: Number(event.target.value) }))
                    }
                  />
                </label>
              </div>
              <div className="summary-row highlight">
                <span>草案提示</span>
                <strong>{buildDraftHint(draft, payload.sensitivity_signal)}</strong>
              </div>
            </section>
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">建议试验档位</p>
                <h3>优先做哪几组参数对照</h3>
              </div>
            </header>
            <div className="scenario-grid">
              {payload.suggested_profiles.map((profile) => (
                <SuggestionCard key={profile.profile_name} profile={profile} />
              ))}
            </div>
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">标的级总览</p>
                <h3>先看这一轮最值得处理的标的群</h3>
              </div>
              <span className="section-meta">
                当前策略共 {symbolItems.length} 个标的样本
              </span>
            </header>
            <div className="card-grid">
              <article className="metric-card panel">
                <p className="metric-label">需动作标的</p>
                <strong className="metric-value">{actionableSymbolCount}</strong>
                <small>非 `HOLD` 的标的数量，适合作为本轮参数实验的第一优先级</small>
              </article>
              <article className="metric-card panel">
                <p className="metric-label">试验性放宽候选</p>
                <strong className="metric-value is-negative">{loosenSymbolCount}</strong>
                <small>低样本但已出现明显负向净影响与高误杀率的标的</small>
              </article>
              <article className="metric-card panel">
                <p className="metric-label">含临时盯市补价</p>
                <strong className="metric-value">{provisionalPricingSymbolCount}</strong>
                <small>这部分标的用了 ClickHouse 最新日线临时估值，复核时要额外关注解释卡</small>
              </article>
              <article className="metric-card panel">
                <p className="metric-label">低样本试验建议</p>
                <strong className="metric-value">{lowSampleTrialCount}</strong>
                <small>
                  平均置信度 {formatPercent(averageSymbolConfidence)}，更适合先小步实验，再观察增量样本变化
                </small>
              </article>
            </div>
          </section>

          <section className="two-column">
            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">标的级诊断</p>
                  <h3>先找出真正需要调的标的</h3>
                </div>
                <div className="filter-stack">
                  <label className="toggle-chip">
                    <input
                      type="checkbox"
                      checked={onlyActionable}
                      onChange={(event) => setOnlyActionable(event.target.checked)}
                    />
                    <span>仅看需要动作</span>
                  </label>
                  <select className="filter-select" value={actionFilter} onChange={(event) => setActionFilter(event.target.value as SymbolActionFilter)}>
                    <option value="ALL">全部动作</option>
                    <option value="LOOSEN">建议放宽</option>
                    <option value="CUSTOM">人工复核</option>
                    <option value="HOLD">保持观察</option>
                    <option value="TIGHTEN">轻微收紧</option>
                  </select>
                  <select className="filter-select" value={pricingFilter} onChange={(event) => setPricingFilter(event.target.value as SymbolPricingFilter)}>
                    <option value="ALL">全部补价来源</option>
                    <option value="HAS_PROVISIONAL">含临时盯市</option>
                    <option value="DIRECT_ONLY">仅直接补价</option>
                  </select>
                  <select className="filter-select" value={modeFilter} onChange={(event) => setModeFilter(event.target.value as SymbolModeFilter)}>
                    <option value="ALL">全部建议模式</option>
                    <option value="LOW_SAMPLE_TRIAL">低样本试验建议</option>
                    <option value="LOW_SAMPLE_NEEDS_PRICING">待补价复核</option>
                    <option value="REGULAR">常规启发式建议</option>
                  </select>
                </div>
              </header>

              {symbolsError ? <div className="error-banner">{symbolsError}</div> : null}
              {isSymbolsLoading ? <div className="loading-card">正在加载标的级诊断列表…</div> : null}
              {!isSymbolsLoading && !symbolsError && symbolItems.length === 0 ? (
                <div className="empty-state">当前还没有标的级诊断结果，可以先执行一次 `sync_symbol_tpsl_facts` 再回来查看。</div>
              ) : null}

              {!isSymbolsLoading && !symbolsError && symbolItems.length > 0 && filteredSymbolItems.length === 0 ? (
                <div className="empty-state">当前筛选条件下没有命中的标的，可以放宽筛选条件再看。</div>
              ) : null}

              {!isSymbolsLoading && !symbolsError && filteredSymbolItems.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table symbol-data-table">
                    <thead>
                      <tr>
                        <th>标的</th>
                        <th>诊断</th>
                        <th>净影响</th>
                        <th>金额影响</th>
                        <th>误杀率</th>
                        <th>保护效率</th>
                        <th>建议动作</th>
                        <th>置信度</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSymbolItems.map((item) => {
                        const isSelected = item.instrument_id === selectedInstrumentId;
                        return (
                          <tr key={item.instrument_id} className={isSelected ? "is-selected" : ""}>
                            <td>
                              <button
                                className="text-link-button"
                                type="button"
                                onClick={() => setSelectedInstrumentId(item.instrument_id)}
                              >
                                {item.instrument_id}
                              </button>
                              <small>
                                {item.priced_lifecycles}/{item.total_lifecycles} 生命周期
                              </small>
                            </td>
                            <td>
                              <span className={`pill ${getDiagnosisPillClass(item.diagnosis_label)}`}>
                                {getDiagnosisLabel(item.diagnosis_label)}
                              </span>
                            </td>
                            <td className={getValueTone(item.delta_bps)}>{formatBps(item.delta_bps)}</td>
                            <td className={getValueTone(item.pnl_delta_sum)}>{formatNumber(item.pnl_delta_sum)}</td>
                            <td>{formatPercent(item.misfire_rate)}</td>
                            <td>{formatPercent(item.protection_efficiency)}</td>
                            <td>
                              <span className={`pill ${getActionPillClass(item.recommended_action)}`}>
                                {getActionLabel(item.recommended_action)}
                              </span>
                            </td>
                            <td>
                              <strong>{getConfidenceLabel(item.confidence_score)}</strong>
                              <small>{formatPercent(item.confidence_score)}</small>
                              <small>
                                直接 {formatNumber(item.direct_priced_lifecycles, "--")} / 临时 {formatNumber(item.provisional_priced_lifecycles, "--")}
                              </small>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>

            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">标的级详情</p>
                  <h3>看清这只标的为什么被建议调整</h3>
                </div>
                <span className="section-meta">
                  {selectedInstrumentId ?? "尚未选择标的"}
                </span>
              </header>
              <SymbolDetailCard detail={selectedDetail} isLoading={isSymbolDetailLoading} error={symbolDetailError} />
            </section>
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">建议导出</p>
                <h3>把当前筛选结果整理成可下游消费的结构化清单</h3>
              </div>
              <span className="section-meta">
                {exportPayload ? `${exportPayload.export_method} · ${exportPayload.generated_at}` : "尚未生成导出快照"}
              </span>
            </header>

            {exportError ? <div className="error-banner">{exportError}</div> : null}
            {isExportLoading ? <div className="loading-card">正在生成当前筛选条件下的导出 JSON…</div> : null}

            {!isExportLoading && !exportError ? (
              <div className="export-layout">
                <div className="export-stack">
                  <div className="card-grid">
                    <article className="metric-card panel">
                      <p className="metric-label">导出覆盖项</p>
                      <strong className="metric-value">{formatNumber(exportOverrideCount, "0")}</strong>
                      <small>真正会进入 `symbol_overrides` 的非 `HOLD` 标的数量</small>
                    </article>
                    <article className="metric-card panel">
                      <p className="metric-label">当前筛中样本</p>
                      <strong className="metric-value">{formatNumber(exportFilteredCount, "0")}</strong>
                      <small>已经应用动作、补价来源、建议模式和“仅看需要动作”后的结果</small>
                    </article>
                    <article className="metric-card panel">
                      <p className="metric-label">含临时盯市样本</p>
                      <strong className="metric-value">{formatNumber(exportProvisionalCount, "0")}</strong>
                      <small>这部分建议含 ClickHouse 临时盯市补价，接入下游前建议再做一次人工复核</small>
                    </article>
                    <article className="metric-card panel">
                      <p className="metric-label">平均置信度</p>
                      <strong className="metric-value">{formatPercent(exportAverageConfidence)}</strong>
                      <small>导出清单内样本的平均置信度，可作为是否先小范围灰度的参考</small>
                    </article>
                  </div>

                  <div className="summary-stack">
                    <div className="summary-row">
                      <span>动作筛选</span>
                      <strong>{actionFilter === "ALL" ? "全部动作" : getActionLabel(actionFilter)}</strong>
                    </div>
                    <div className="summary-row">
                      <span>补价来源筛选</span>
                      <strong>{getPricingFilterLabel(pricingFilter)}</strong>
                    </div>
                    <div className="summary-row">
                      <span>建议模式筛选</span>
                      <strong>{getModeFilterLabel(modeFilter)}</strong>
                    </div>
                    <div className="summary-row">
                      <span>仅看需要动作</span>
                      <strong>{onlyActionable ? "是" : "否"}</strong>
                    </div>
                  </div>

                  <div className="export-actions">
                    <button className="action-button" type="button" onClick={handleCopyExport} disabled={!exportPayload}>
                      {copyState === "COPIED" ? "已复制 JSON" : copyState === "FAILED" ? "复制失败，请重试" : "复制 JSON"}
                    </button>
                    <button
                      className="action-button action-button-secondary"
                      type="button"
                      onClick={handleDownloadExport}
                      disabled={!exportPayload}
                    >
                      下载 JSON
                    </button>
                  </div>
                </div>

                <div className="export-preview-panel">
                  <p className="eyebrow">JSON 预览</p>
                  {exportPayload ? (
                    <pre className="export-preview">{exportPreview}</pre>
                  ) : (
                    <div className="empty-state">当前还没有可预览的导出结果。</div>
                  )}
                </div>
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </main>
  );
}
