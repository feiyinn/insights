import type {
  ParameterLabExportPayload,
  ParameterLabPayload,
  ParameterLabSymbolDetailItem,
  ParameterLabSymbolItem,
  PositionLifecycleItem,
  StrategyActionItem,
  StrategyDailyItem,
  StrategyDetailPayload,
  StrategyOverviewItem,
  StrategySummary,
  StrategyTargetItem,
  TpSlInterventionItem,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * 用途：统一发起前端到分析后端的 JSON 请求。
 * 参数：
 *   path：以 `/api` 开头的接口路径。
 * 返回值：
 *   解析后的泛型 JSON 数据。
 * 异常/边界：
 *   当接口返回非 2xx 状态时抛出异常，由调用方决定如何展示错误。
 */
async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`接口请求失败: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

/**
 * 用途：读取当前所有可分析策略。
 * 参数：
 *   无。
 * 返回值：
 *   策略摘要列表。
 * 异常/边界：
 *   网络异常会向上抛出，交由页面统一展示。
 */
export async function fetchStrategies(): Promise<StrategySummary[]> {
  return requestJson<StrategySummary[]>("/api/strategies");
}

/**
 * 用途：读取概览页使用的策略聚合摘要列表。
 * 参数：
 *   无。
 * 返回值：
 *   每个策略实例对应一条概览摘要。
 * 异常/边界：
 *   网络异常会向上抛出，由调用方统一处理。
 */
export async function fetchStrategyOverview(): Promise<StrategyOverviewItem[]> {
  return requestJson<StrategyOverviewItem[]>("/api/overview/strategies");
}

/**
 * 用途：并行读取某个策略的全部首版分析数据。
 * 参数：
 *   strategyName：策略名称。
 * 返回值：
 *   包含日度收益、TPSL 干预、生命周期、目标池和动作列表的聚合结果。
 * 异常/边界：
 *   任一子请求失败都会让整体请求失败，避免页面出现部分口径已更新、部分未更新的不一致状态。
 */
export async function fetchStrategyDetails(
  strategyName: string,
  portfolioId?: string | null,
): Promise<StrategyDetailPayload> {
  const encodedName = encodeURIComponent(strategyName);
  const portfolioQuery = (portfolioId?: string | null) =>
    portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : "";
  const [daily, interventions, lifecycles, targets, actions] = await Promise.all([
    requestJson<StrategyDailyItem[]>(`/api/strategies/${encodedName}/daily${portfolioQuery(portfolioId)}`),
    requestJson<TpSlInterventionItem[]>(`/api/strategies/${encodedName}/tpsl/interventions${portfolioQuery(portfolioId)}`),
    requestJson<PositionLifecycleItem[]>(`/api/strategies/${encodedName}/lifecycles${portfolioQuery(portfolioId)}`),
    requestJson<StrategyTargetItem[]>(`/api/strategies/${encodedName}/targets/latest`),
    requestJson<StrategyActionItem[]>(`/api/strategies/${encodedName}/actions/latest`),
  ]);

  return {
    daily,
    interventions,
    lifecycles,
    targets,
    actions,
  };
}

/**
 * 用途：读取某个策略实例的参数实验室聚合数据。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：可选组合 ID。
 * 返回值：
 *   参数实验室页面所需的方案对比、诊断摘要与建议档位。
 * 异常/边界：
 *   当尚无历史回放结果时，接口仍会返回默认基线方案，前端无需额外兜底。
 */
export async function fetchParameterLab(
  strategyName: string,
  portfolioId?: string | null,
): Promise<ParameterLabPayload> {
  const encodedName = encodeURIComponent(strategyName);
  const portfolioQuery = portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : "";
  return requestJson<ParameterLabPayload>(`/api/strategies/${encodedName}/parameter-lab${portfolioQuery}`);
}

/**
 * 用途：读取某个策略的标的级参数实验室摘要列表。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：可选组合 ID。
 *   onlyActionable：是否只返回非 HOLD 的标的。
 * 返回值：
 *   标的级诊断与建议摘要列表。
 * 异常/边界：
 *   当后端尚未生成标的级事实表时，接口会返回空数组。
 */
export async function fetchParameterLabSymbols(
  strategyName: string,
  portfolioId?: string | null,
  onlyActionable?: boolean,
): Promise<ParameterLabSymbolItem[]> {
  const encodedName = encodeURIComponent(strategyName);
  const searchParams = new URLSearchParams();
  if (portfolioId) {
    searchParams.set("portfolio_id", portfolioId);
  }
  if (onlyActionable) {
    searchParams.set("only_actionable", "true");
  }
  const query = searchParams.toString();
  return requestJson<ParameterLabSymbolItem[]>(
    `/api/strategies/${encodedName}/parameter-lab/symbols${query ? `?${query}` : ""}`,
  );
}

/**
 * 用途：读取某个策略某个标的的参数实验室详情。
 * 参数：
 *   strategyName：策略名称。
 *   instrumentId：标的代码。
 *   portfolioId：可选组合 ID。
 * 返回值：
 *   单标的的完整诊断与建议详情。
 * 异常/边界：
 *   当标的不存在时，调用方会收到接口异常。
 */
export async function fetchParameterLabSymbolDetail(
  strategyName: string,
  instrumentId: string,
  portfolioId?: string | null,
): Promise<ParameterLabSymbolDetailItem> {
  const encodedName = encodeURIComponent(strategyName);
  const encodedInstrument = encodeURIComponent(instrumentId);
  const portfolioQuery = portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : "";
  return requestJson<ParameterLabSymbolDetailItem>(
    `/api/strategies/${encodedName}/parameter-lab/symbols/${encodedInstrument}${portfolioQuery}`,
  );
}

/**
 * 用途：读取某个策略在当前筛选条件下的结构化导出清单。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：可选组合 ID。
 *   onlyActionable：是否只导出非 HOLD 标的。
 *   actionFilter：建议动作筛选。
 *   pricingFilter：补价来源筛选。
 *   modeFilter：建议模式筛选。
 * 返回值：
 *   可供下游系统消费的结构化导出对象。
 * 异常/边界：
 *   当后端暂无标的级结果时，仍会返回空的 `symbol_overrides`。
 */
export async function fetchParameterLabExport(
  strategyName: string,
  portfolioId?: string | null,
  onlyActionable?: boolean,
  actionFilter?: string,
  pricingFilter?: string,
  modeFilter?: string,
): Promise<ParameterLabExportPayload> {
  const encodedName = encodeURIComponent(strategyName);
  const searchParams = new URLSearchParams();
  if (portfolioId) {
    searchParams.set("portfolio_id", portfolioId);
  }
  if (onlyActionable) {
    searchParams.set("only_actionable", "true");
  }
  if (actionFilter && actionFilter !== "ALL") {
    searchParams.set("recommended_action", actionFilter);
  }
  if (pricingFilter && pricingFilter !== "ALL") {
    searchParams.set("pricing_filter", pricingFilter);
  }
  if (modeFilter && modeFilter !== "ALL") {
    searchParams.set("mode_filter", modeFilter);
  }
  const query = searchParams.toString();
  return requestJson<ParameterLabExportPayload>(
    `/api/strategies/${encodedName}/parameter-lab/export${query ? `?${query}` : ""}`,
  );
}
