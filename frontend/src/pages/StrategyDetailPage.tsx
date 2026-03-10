import { DeltaBarChart } from "../components/DeltaBarChart";
import { LineCompareChart } from "../components/LineCompareChart";
import type { StrategyDetailPayload, StrategyOverviewItem } from "../types";
import { formatBps, formatDateTime, formatNumber, formatPercent, getValueTone, toBps } from "../utils";

interface OverviewCard {
  label: string;
  value: number | null;
  helper: string;
}

interface StandardizedOverviewCard {
  label: string;
  value: number | null;
  helper: string;
}

interface ActionSummary {
  buyCount: number;
  sellCount: number;
  holdCount: number;
}

interface LifecycleSummary {
  totalCount: number;
  tpslCount: number;
  pricedRawCount: number;
  positiveDeltaCount: number;
  negativeDeltaCount: number;
}

interface StrategyDetailPageProps {
  strategyName: string;
  portfolioId: string | null;
  overviewItem: StrategyOverviewItem | null;
  detail: StrategyDetailPayload | null;
  isLoading: boolean;
  error: string | null;
  onBack: () => void;
}

/**
 * 用途：根据策略详情构建顶部 KPI 卡片。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   适合详情页展示的概览卡片列表。
 * 异常/边界：
 *   当缺失日度样本时返回空数组，由页面展示空态。
 */
function buildOverviewCards(detail: StrategyDetailPayload): OverviewCard[] {
  const latestDaily = detail.daily.at(-1);
  if (!latestDaily) {
    return [];
  }

  return [
    {
      label: "实际累计已实现收益",
      value: latestDaily.realized_pnl_actual_cum,
      helper: "真实执行路径下已兑现的累计收益",
    },
    {
      label: "原始累计已实现收益",
      value: latestDaily.realized_pnl_raw_cum,
      helper: "按原始调仓退出时点估算的累计收益",
    },
    {
      label: "最近一日 TPSL 净影响",
      value: latestDaily.tpsl_net_delta,
      helper: "最近交易日内 TPSL 的正负贡献合计",
    },
    {
      label: "最近一日 TPSL 退出次数",
      value: latestDaily.tpsl_exit_count,
      helper: "当日被 TPSL 主动触发的退出次数",
    },
  ];
}

/**
 * 用途：提炼当前详情页顶部的结论文本。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   面向分析者的简洁结论文案。
 * 异常/边界：
 *   样本不足时返回中性文本。
 */
function buildHeadlineInsight(detail: StrategyDetailPayload): string {
  const latestDaily = detail.daily.at(-1);
  if (!latestDaily) {
    return "当前还没有足够的日度样本，先完成同步后再判断 TPSL 的收益贡献方向。";
  }

  if ((latestDaily.proxy_delta_bps_cum ?? 0) > 0) {
    return "当前在标准化口径下，TPSL 更偏向正向保护，说明单位资金上锁住的收益大于错失的后续上涨。";
  }
  if ((latestDaily.proxy_delta_bps_cum ?? 0) < 0) {
    return "当前在标准化口径下，TPSL 的负贡献更明显，参数可能偏敏感，值得继续放宽止盈止损阈值。";
  }
  return "当前在标准化口径下，TPSL 的影响比较中性，建议继续看单笔干预明细再做判断。";
}

/**
 * 用途：根据策略详情构建标准化绩效卡片。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   适合详情页展示的标准化绩效卡片列表。
 * 异常/边界：
 *   当缺失日度样本时返回空数组，由页面展示空态。
 */
function buildStandardizedCards(detail: StrategyDetailPayload): StandardizedOverviewCard[] {
  const latestDaily = detail.daily.at(-1);
  if (!latestDaily) {
    return [];
  }

  const actualMinusRawAmount =
    latestDaily.realized_pnl_actual_cum !== null && latestDaily.realized_pnl_raw_cum !== null
      ? latestDaily.realized_pnl_actual_cum - latestDaily.realized_pnl_raw_cum
      : null;

  return [
    {
      label: "实际收益效率",
      value: toBps(latestDaily.proxy_return_actual_cum),
      helper: `累计金额 ${formatNumber(latestDaily.realized_pnl_actual_cum)}，覆盖 ${formatPercent(latestDaily.proxy_priced_coverage_ratio_cum)}`,
    },
    {
      label: "原始收益效率",
      value: toBps(latestDaily.proxy_return_raw_cum),
      helper: `累计金额 ${formatNumber(latestDaily.realized_pnl_raw_cum)}，可和当前实际路径公平比较`,
    },
    {
      label: "TPSL 单位资金净影响",
      value: latestDaily.proxy_delta_bps_cum,
      helper: `金额差 ${formatNumber(actualMinusRawAmount)}，正值代表单位资金层面的净保护`,
    },
    {
      label: "交易成本拖累",
      value: latestDaily.fee_drag_bps_cum,
      helper: `税拖 ${formatBps(latestDaily.tax_drag_bps_cum)}，越低代表单位成交成本越可控`,
    },
  ];
}

/**
 * 用途：提取累计收益比较图所需的数据点。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   按交易日顺序排列的双曲线点数据。
 * 异常/边界：
 *   `raw` 路径局部仍可能为空，图表会自动跳过空点。
 */
function buildChartPoints(detail: StrategyDetailPayload) {
  return detail.daily.map((item) => ({
    label: item.trade_date,
    actual: item.realized_pnl_actual_cum,
    raw: item.realized_pnl_raw_cum,
  }));
}

/**
 * 用途：提取 TPSL 日度净影响柱状图数据。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   日期与净影响数值列表。
 * 异常/边界：
 *   无。
 */
function buildDeltaSeries(detail: StrategyDetailPayload) {
  return {
    labels: detail.daily.map((item) => item.trade_date),
    values: detail.daily.map((item) => item.tpsl_net_delta),
  };
}

/**
 * 用途：汇总单笔干预的正负贡献数量。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   用于摘要卡的聚合统计对象。
 * 异常/边界：
 *   无干预时各值回退为 0。
 */
function summarizeInterventions(detail: StrategyDetailPayload) {
  return detail.interventions.reduce(
    (summary, intervention) => {
      const delta = intervention.net_pnl_delta ?? 0;
      if (delta > 0) {
        summary.positiveCount += 1;
      } else if (delta < 0) {
        summary.negativeCount += 1;
      } else {
        summary.pendingCount += 1;
      }
      summary.netTotal += delta;
      return summary;
    },
    {
      positiveCount: 0,
      negativeCount: 0,
      pendingCount: 0,
      netTotal: 0,
    },
  );
}

/**
 * 用途：汇总最新原始动作中的买卖保持数量。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   BUY、SELL、HOLD 三类动作的数量统计。
 * 异常/边界：
 *   当动作列表为空时，各值回退为 0。
 */
function summarizeActions(detail: StrategyDetailPayload): ActionSummary {
  return detail.actions.reduce(
    (summary, action) => {
      if (action.action_type === "BUY") {
        summary.buyCount += 1;
      } else if (action.action_type === "SELL") {
        summary.sellCount += 1;
      } else if (action.action_type === "HOLD") {
        summary.holdCount += 1;
      }
      return summary;
    },
    {
      buyCount: 0,
      sellCount: 0,
      holdCount: 0,
    },
  );
}

/**
 * 用途：汇总生命周期样本的补价覆盖率与 TPSL 干预情况。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   生命周期覆盖率与正负偏差数量的摘要对象。
 * 异常/边界：
 *   当样本为空时，各项统计回退为 0。
 */
function summarizeLifecycles(detail: StrategyDetailPayload): LifecycleSummary {
  return detail.lifecycles.reduce(
    (summary, lifecycle) => {
      summary.totalCount += 1;
      if (lifecycle.tpsl_intervened) {
        summary.tpslCount += 1;
      }
      if (lifecycle.exit_price_raw !== null) {
        summary.pricedRawCount += 1;
      }
      if ((lifecycle.pnl_delta ?? 0) > 0) {
        summary.positiveDeltaCount += 1;
      } else if ((lifecycle.pnl_delta ?? 0) < 0) {
        summary.negativeDeltaCount += 1;
      }
      return summary;
    },
    {
      totalCount: 0,
      tpslCount: 0,
      pricedRawCount: 0,
      positiveDeltaCount: 0,
      negativeDeltaCount: 0,
    },
  );
}

/**
 * 用途：按归因分类聚合 TPSL 干预事件数量。
 * 参数：
 *   detail：已加载的策略详情数据。
 * 返回值：
 *   按数量倒序排列的分类统计列表。
 * 异常/边界：
 *   分类缺失时归入“未分类”，避免聚合时丢样本。
 */
function summarizeClassification(detail: StrategyDetailPayload) {
  const countMap = new Map<string, number>();
  for (const intervention of detail.interventions) {
    const classification = intervention.classification || "未分类";
    countMap.set(classification, (countMap.get(classification) ?? 0) + 1);
  }
  return [...countMap.entries()]
    .map(([classification, count]) => ({ classification, count }))
    .sort((left, right) => right.count - left.count);
}

/**
 * 用途：渲染单策略详情页。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：组合 ID。
 *   overviewItem：首页摘要中对应的策略实例。
 *   detail：明细数据。
 *   isLoading：是否正在加载。
 *   error：错误信息。
 *   onBack：返回首页回调。
 * 返回值：
 *   包含收益曲线、TPSL 明细和生命周期的详情页组件。
 * 异常/边界：
 *   当接口失败时会在页面中显式展示错误信息。
 */
export function StrategyDetailPage({
  strategyName,
  portfolioId,
  overviewItem,
  detail,
  isLoading,
  error,
  onBack,
}: StrategyDetailPageProps) {
  const cards = detail ? buildOverviewCards(detail) : [];
  const standardizedCards = detail ? buildStandardizedCards(detail) : [];
  const chartPoints = detail ? buildChartPoints(detail) : [];
  const deltaSeries = detail ? buildDeltaSeries(detail) : { labels: [], values: [] };
  const interventionSummary = detail ? summarizeInterventions(detail) : null;
  const actionSummary = detail ? summarizeActions(detail) : null;
  const lifecycleSummary = detail ? summarizeLifecycles(detail) : null;
  const classificationSummary = detail ? summarizeClassification(detail) : [];

  return (
    <main className="main-content">
      <section className="hero panel">
        <div>
          <button className="back-link" type="button" onClick={onBack}>
            返回策略总览
          </button>
          <p className="eyebrow">策略详情</p>
          <h2>{strategyName}</h2>
          <p className="hero-copy">{detail ? buildHeadlineInsight(detail) : "正在加载策略详情，请稍等片刻。"}</p>
        </div>
        <div className="hero-meta">
          <span>组合：{portfolioId ?? overviewItem?.portfolio_id ?? "--"}</span>
          <span>模式：{overviewItem?.mode ?? "--"}</span>
          <span>最新交易日：{overviewItem?.latest_trade_date ?? "--"}</span>
        </div>
      </section>

      {error ? <section className="panel error-banner">{error}</section> : null}
      {isLoading ? <section className="panel loading-card">正在同步策略详情…</section> : null}

      {detail ? (
        <>
          <section className="card-grid">
            {cards.map((card) => (
              <article className="metric-card panel" key={card.label}>
                <p className="metric-label">{card.label}</p>
                <strong className={`metric-value ${getValueTone(card.value)}`}>{formatNumber(card.value)}</strong>
                <small>{card.helper}</small>
              </article>
            ))}
          </section>

          <section className="card-grid">
            {standardizedCards.map((card) => (
              <article className="metric-card panel" key={card.label}>
                <p className="metric-label">{card.label}</p>
                <strong className={`metric-value ${getValueTone(card.value)}`}>{formatBps(card.value)}</strong>
                <small>{card.helper}</small>
              </article>
            ))}
          </section>

          <LineCompareChart title="累计已实现收益对比" points={chartPoints} />

          <section className="two-column">
            <DeltaBarChart labels={deltaSeries.labels} values={deltaSeries.values} />

            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">TPSL 归因摘要</p>
                  <h3>单笔干预贡献分布</h3>
                </div>
              </header>
              {interventionSummary ? (
                <div className="summary-stack">
                  <div className="summary-row">
                    <span>正贡献干预</span>
                    <strong className="is-positive">{interventionSummary.positiveCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>负贡献干预</span>
                    <strong className="is-negative">{interventionSummary.negativeCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>待补价干预</span>
                    <strong>{interventionSummary.pendingCount}</strong>
                  </div>
                  <div className="summary-row highlight">
                    <span>累计净影响</span>
                    <strong className={getValueTone(interventionSummary.netTotal)}>
                      {formatNumber(interventionSummary.netTotal)}
                    </strong>
                  </div>
                </div>
              ) : (
                <div className="empty-state">当前还没有足够的 TPSL 干预样本。</div>
              )}
            </section>
          </section>

          <section className="detail-subgrid">
            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">路径覆盖</p>
                  <h3>原始路径与实际路径样本状态</h3>
                </div>
              </header>
              {lifecycleSummary ? (
                <div className="summary-stack">
                  <div className="summary-row">
                    <span>生命周期样本</span>
                    <strong>{lifecycleSummary.totalCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>TPSL 干预仓位</span>
                    <strong>{lifecycleSummary.tpslCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>原始路径已补价</span>
                    <strong>{lifecycleSummary.pricedRawCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>正偏差样本</span>
                    <strong className="is-positive">{lifecycleSummary.positiveDeltaCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>负偏差样本</span>
                    <strong className="is-negative">{lifecycleSummary.negativeDeltaCount}</strong>
                  </div>
                </div>
              ) : (
                <div className="empty-state">当前还没有可用的生命周期样本。</div>
              )}
            </section>

            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">原始调仓摘要</p>
                  <h3>最新批次动作拆解</h3>
                </div>
              </header>
              {actionSummary ? (
                <div className="summary-stack">
                  <div className="summary-row">
                    <span>买入动作</span>
                    <strong className="is-positive">{actionSummary.buyCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>卖出动作</span>
                    <strong className="is-negative">{actionSummary.sellCount}</strong>
                  </div>
                  <div className="summary-row">
                    <span>继续持有</span>
                    <strong>{actionSummary.holdCount}</strong>
                  </div>
                  <div className="summary-row highlight">
                    <span>目标池总数</span>
                    <strong>{detail.targets.length}</strong>
                  </div>
                </div>
              ) : (
                <div className="empty-state">当前还没有可用的调仓动作样本。</div>
              )}
            </section>
          </section>

          <section className="detail-subgrid">
            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">最新目标池</p>
                  <h3>本轮调仓应持有标的</h3>
                </div>
                <span className="section-meta">{detail.targets.length} 只</span>
              </header>
              <div className="token-grid">
                {detail.targets.map((target) => (
                  <span className="token" key={target.instrument_id}>
                    {target.instrument_id}
                  </span>
                ))}
              </div>
            </section>

            <section className="panel">
              <header className="panel-header">
                <div>
                  <p className="eyebrow">最新原始动作</p>
                  <h3>目标池差分结果</h3>
                </div>
                <span className="section-meta">{detail.actions.length} 条</span>
              </header>
              <div className="action-list">
                {detail.actions.slice(0, 12).map((action) => (
                  <div className="action-item" key={`${action.instrument_id}-${action.action_type}-${action.reason_type}`}>
                    <span className={`pill pill-${action.action_type.toLowerCase()}`}>{action.action_type}</span>
                    <strong>{action.instrument_id}</strong>
                    <small>{action.reason_type}</small>
                  </div>
                ))}
              </div>
            </section>
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">归因分类分布</p>
                <h3>TPSL 干预更常出现在哪类场景</h3>
              </div>
              <span className="section-meta">{classificationSummary.length} 类</span>
            </header>
            {classificationSummary.length ? (
              <div className="classification-grid">
                {classificationSummary.map((item) => (
                  <div className="classification-card" key={item.classification}>
                    <span>{item.classification}</span>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">当前还没有足够的归因分类样本。</div>
            )}
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">TPSL 干预明细</p>
                <h3>最近 20 条事件</h3>
              </div>
            </header>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>标的</th>
                    <th>触发类型</th>
                    <th>触发时间</th>
                    <th>归因分类</th>
                    <th>保护收益</th>
                    <th>错失收益</th>
                    <th>净影响</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.interventions.slice(0, 20).map((item) => (
                    <tr key={item.intent_id}>
                      <td>{item.instrument_id}</td>
                      <td>{item.level_type}</td>
                      <td>{formatDateTime(item.fill_ts)}</td>
                      <td>{item.classification}</td>
                      <td className="is-positive">{formatNumber(item.protected_pnl)}</td>
                      <td className="is-negative">{formatNumber(item.missed_pnl)}</td>
                      <td className={getValueTone(item.net_pnl_delta)}>{formatNumber(item.net_pnl_delta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">持仓生命周期</p>
                <h3>最近 16 条开仓到退出路径</h3>
              </div>
            </header>
            <div className="table-wrap">
              <table className="data-table lifecycle-table">
                <thead>
                  <tr>
                    <th>标的</th>
                    <th>开仓时间</th>
                    <th>实际退出</th>
                    <th>原始退出</th>
                    <th>实际收益</th>
                    <th>原始收益</th>
                    <th>偏差</th>
                    <th>TPSL</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.lifecycles.slice(0, 16).map((item) => (
                    <tr key={`${item.instrument_id}-${item.entry_ts}`}>
                      <td>{item.instrument_id}</td>
                      <td>{formatDateTime(item.entry_ts)}</td>
                      <td>
                        <div>{formatDateTime(item.exit_ts_actual)}</div>
                        <small>{item.exit_reason_actual ?? "--"}</small>
                      </td>
                      <td>
                        <div>{formatDateTime(item.exit_ts_raw)}</div>
                        <small>{item.exit_reason_raw ?? item.raw_path_status}</small>
                      </td>
                      <td className={getValueTone(item.pnl_actual)}>{formatNumber(item.pnl_actual)}</td>
                      <td className={getValueTone(item.pnl_raw)}>{formatNumber(item.pnl_raw)}</td>
                      <td className={getValueTone(item.pnl_delta)}>{formatNumber(item.pnl_delta)}</td>
                      <td>
                        <span className={`pill ${item.tpsl_intervened ? "pill-alert" : "pill-hold"}`}>
                          {item.tpsl_intervened ? "已干预" : "未干预"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
