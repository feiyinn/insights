import { useDeferredValue, useState } from "react";

import type { StrategyOverviewItem } from "../types";
import { formatBps, formatShortDate, formatNumber, formatPercent, getValueTone, toBps } from "../utils";

type ModeFilter = "ALL" | "SIMU" | "LIVE";
type ImpactFilter = "ALL" | "POSITIVE" | "NEGATIVE" | "NEUTRAL";
type SortKey = "PROXY_ACTUAL_DESC" | "PROXY_DELTA_DESC" | "ACTUAL_DESC" | "RAW_DESC" | "DELTA_DESC" | "LATEST_DESC";

interface OverviewPageProps {
  items: StrategyOverviewItem[];
  isLoading: boolean;
  onOpenStrategy: (strategyName: string, portfolioId: string) => void;
}

interface SpotlightCard {
  title: string;
  helper: string;
  item: StrategyOverviewItem | null;
  value: number | null;
  secondaryValue: number | null;
  secondaryLabel: string;
}

/**
 * 用途：计算概览页顶部所需的全局摘要指标。
 * 参数：
 *   items：策略概览列表。
 * 返回值：
 *   汇总后的总收益、总净影响和策略数量等统计值。
 * 异常/边界：
 *   当列表为空时，各数值回退为 0，避免页面出现 NaN。
 */
function summarizeOverview(items: StrategyOverviewItem[]) {
  const summary = items.reduce(
    (summary, item) => {
      summary.strategyCount += 1;
      summary.actualTotal += item.realized_pnl_actual_cum ?? 0;
      summary.rawTotal += item.realized_pnl_raw_cum ?? 0;
      summary.netDeltaTotal += item.total_tpsl_net_delta ?? 0;
      summary.openPositions += item.open_position_count;
      summary.proxyPricedEntryNotional += item.proxy_priced_entry_notional ?? 0;
      summary.proxyActualPnlTotal += item.proxy_pnl_actual_sum ?? 0;
      summary.proxyRawPnlTotal += item.proxy_pnl_raw_sum ?? 0;
      summary.proxyDeltaPnlTotal += item.proxy_pnl_delta_sum ?? 0;
      return summary;
    },
    {
      strategyCount: 0,
      actualTotal: 0,
      rawTotal: 0,
      netDeltaTotal: 0,
      openPositions: 0,
      proxyPricedEntryNotional: 0,
      proxyActualPnlTotal: 0,
      proxyRawPnlTotal: 0,
      proxyDeltaPnlTotal: 0,
    },
  );
  return {
    ...summary,
    weightedProxyReturnActual:
      summary.proxyPricedEntryNotional > 0 ? summary.proxyActualPnlTotal / summary.proxyPricedEntryNotional : null,
    weightedProxyReturnRaw:
      summary.proxyPricedEntryNotional > 0 ? summary.proxyRawPnlTotal / summary.proxyPricedEntryNotional : null,
    weightedProxyDeltaBps:
      summary.proxyPricedEntryNotional > 0 ? (summary.proxyDeltaPnlTotal / summary.proxyPricedEntryNotional) * 10000 : null,
  };
}

/**
 * 用途：根据当前筛选条件过滤策略概览列表。
 * 参数：
 *   items：原始策略概览列表。
 *   searchKeyword：策略名或组合 ID 搜索关键字。
 *   modeFilter：模式筛选条件。
 *   impactFilter：TPSL 影响方向筛选条件。
 * 返回值：
 *   通过全部筛选条件后的策略列表。
 * 异常/边界：
 *   搜索关键字为空时不做文本过滤；空值净影响会归为中性。
 */
function filterOverviewItems(
  items: StrategyOverviewItem[],
  searchKeyword: string,
  modeFilter: ModeFilter,
  impactFilter: ImpactFilter,
) {
  const normalizedKeyword = searchKeyword.trim().toLowerCase();

  return items.filter((item) => {
    const matchesKeyword =
      !normalizedKeyword ||
      item.strategy_name.toLowerCase().includes(normalizedKeyword) ||
      item.portfolio_id.toLowerCase().includes(normalizedKeyword);

    const matchesMode = modeFilter === "ALL" || item.mode.toUpperCase() === modeFilter;
    const netDelta = item.proxy_delta_bps ?? item.total_tpsl_net_delta ?? 0;
    const matchesImpact =
      impactFilter === "ALL" ||
      (impactFilter === "POSITIVE" && netDelta > 0) ||
      (impactFilter === "NEGATIVE" && netDelta < 0) ||
      (impactFilter === "NEUTRAL" && netDelta === 0);

    return matchesKeyword && matchesMode && matchesImpact;
  });
}

/**
 * 用途：按照用户选择的排序规则对策略概览列表排序。
 * 参数：
 *   items：待排序的策略概览列表。
 *   sortKey：排序方式。
 * 返回值：
 *   新的排序后列表，不会修改原数组。
 * 异常/边界：
 *   空值统一按 0 参与排序，避免界面在字段未补齐时抖动。
 */
function sortOverviewItems(items: StrategyOverviewItem[], sortKey: SortKey) {
  const sortedItems = [...items];
  sortedItems.sort((left, right) => {
    if (sortKey === "PROXY_ACTUAL_DESC") {
      return (right.proxy_return_actual ?? 0) - (left.proxy_return_actual ?? 0);
    }
    if (sortKey === "PROXY_DELTA_DESC") {
      return (right.proxy_delta_bps ?? 0) - (left.proxy_delta_bps ?? 0);
    }
    if (sortKey === "ACTUAL_DESC") {
      return (right.realized_pnl_actual_cum ?? 0) - (left.realized_pnl_actual_cum ?? 0);
    }
    if (sortKey === "RAW_DESC") {
      return (right.realized_pnl_raw_cum ?? 0) - (left.realized_pnl_raw_cum ?? 0);
    }
    if (sortKey === "DELTA_DESC") {
      return (right.total_tpsl_net_delta ?? 0) - (left.total_tpsl_net_delta ?? 0);
    }
    return (right.latest_trade_date ?? "").localeCompare(left.latest_trade_date ?? "");
  });
  return sortedItems;
}

/**
 * 用途：生成总览页顶部的聚焦卡片，帮助快速定位最值得分析的策略。
 * 参数：
 *   items：已完成筛选和排序的策略列表。
 * 返回值：
 *   最强实际收益、最受益于 TPSL、最受伤于 TPSL 三张聚焦卡片。
 * 异常/边界：
 *   当列表为空时，卡片内容回退为空态。
 */
function buildSpotlightCards(items: StrategyOverviewItem[]): SpotlightCard[] {
  const bestActual = [...items].sort((left, right) => (right.proxy_return_actual ?? 0) - (left.proxy_return_actual ?? 0))[0] ?? null;
  const bestDelta = [...items].sort((left, right) => (right.proxy_delta_bps ?? 0) - (left.proxy_delta_bps ?? 0))[0] ?? null;
  const worstDelta = [...items].sort((left, right) => (left.proxy_delta_bps ?? 0) - (right.proxy_delta_bps ?? 0))[0] ?? null;

  return [
    {
      title: "效率领先策略",
      helper: "先看单位资金效率最高的实例，再结合金额判断业务体量。",
      item: bestActual,
      value: toBps(bestActual?.proxy_return_actual),
      secondaryValue: bestActual?.realized_pnl_actual_cum ?? null,
      secondaryLabel: "累计收益",
    },
    {
      title: "TPSL 标准化正贡献最强",
      helper: "更像在单位资金口径上稳定保护收益，可优先研究其规则配置。",
      item: bestDelta,
      value: bestDelta?.proxy_delta_bps ?? null,
      secondaryValue: bestDelta?.total_tpsl_net_delta ?? null,
      secondaryLabel: "金额净影响",
    },
    {
      title: "TPSL 标准化负贡献最明显",
      helper: "更像在单位资金口径上被过早打断，优先排查是否过敏。",
      item: worstDelta,
      value: worstDelta?.proxy_delta_bps ?? null,
      secondaryValue: worstDelta?.total_tpsl_net_delta ?? null,
      secondaryLabel: "金额净影响",
    },
  ];
}

/**
 * 用途：渲染策略总览首页。
 * 参数：
 *   items：策略概览数据。
 *   isLoading：是否正在加载。
 *   onOpenStrategy：点击策略卡片时的跳转回调。
 * 返回值：
 *   展示总览摘要和策略卡片矩阵的页面组件。
 * 异常/边界：
 *   当列表为空时会展示空态提示，避免出现空白页。
 */
export function OverviewPage({ items, isLoading, onOpenStrategy }: OverviewPageProps) {
  const [searchKeyword, setSearchKeyword] = useState("");
  const [modeFilter, setModeFilter] = useState<ModeFilter>("ALL");
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>("ALL");
  const [sortKey, setSortKey] = useState<SortKey>("PROXY_ACTUAL_DESC");
  const deferredSearchKeyword = useDeferredValue(searchKeyword);
  const filteredItems = sortOverviewItems(
    filterOverviewItems(items, deferredSearchKeyword, modeFilter, impactFilter),
    sortKey,
  );
  const summary = summarizeOverview(filteredItems);
  const spotlightCards = buildSpotlightCards(filteredItems);

  return (
    <main className="main-content">
      <section className="hero panel">
        <div>
          <p className="eyebrow">总览首页</p>
          <h2>每日调仓与 TPSL 全局视图</h2>
          <p className="hero-copy">先看每个策略实例当前是“被 TPSL 帮了一把”，还是“被提前打断了节奏”，再钻到单策略详情页里看生命周期细节。</p>
        </div>
        <div className="hero-meta">
          <span>策略实例：{summary.strategyCount}</span>
          <span>当前持仓：{summary.openPositions}</span>
          <span>首页口径：累计已实现收益 + TPSL 净影响</span>
        </div>
      </section>

      <section className="panel overview-controls-panel">
        <header className="panel-header">
          <div>
            <p className="eyebrow">筛选与排序</p>
            <h3>先缩小问题范围，再深入单策略详情页</h3>
          </div>
          <span className="section-meta">
            当前显示 {filteredItems.length} / {items.length}
          </span>
        </header>

        <div className="overview-controls-grid">
          <label className="field-card">
            <span>搜索策略或组合</span>
            <input
              className="field-input"
              type="search"
              placeholder="输入策略名或 portfolio_id"
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
            />
          </label>

          <label className="field-card">
            <span>模式筛选</span>
            <select className="field-input" value={modeFilter} onChange={(event) => setModeFilter(event.target.value as ModeFilter)}>
              <option value="ALL">全部模式</option>
              <option value="SIMU">仅 SIMU</option>
              <option value="LIVE">仅 LIVE</option>
            </select>
          </label>

          <label className="field-card">
            <span>TPSL 影响方向</span>
            <select
              className="field-input"
              value={impactFilter}
              onChange={(event) => setImpactFilter(event.target.value as ImpactFilter)}
            >
              <option value="ALL">全部方向</option>
              <option value="POSITIVE">净正贡献</option>
              <option value="NEGATIVE">净负贡献</option>
              <option value="NEUTRAL">中性</option>
            </select>
          </label>

          <label className="field-card">
            <span>排序方式</span>
            <select className="field-input" value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
              <option value="PROXY_ACTUAL_DESC">按实际收益效率</option>
              <option value="PROXY_DELTA_DESC">按 TPSL 净影响(bps)</option>
              <option value="ACTUAL_DESC">按实际累计收益</option>
              <option value="RAW_DESC">按原始累计收益</option>
              <option value="DELTA_DESC">按 TPSL 净影响</option>
              <option value="LATEST_DESC">按最新交易日</option>
            </select>
          </label>
        </div>
      </section>

      <section className="card-grid">
        <article className="metric-card panel">
          <p className="metric-label">策略实例数</p>
          <strong className="metric-value">{summary.strategyCount}</strong>
          <small>已进入分析口径、且已有日度数据的策略组合数量</small>
        </article>
        <article className="metric-card panel">
          <p className="metric-label">实际收益效率</p>
          <strong className={`metric-value ${getValueTone(toBps(summary.weightedProxyReturnActual))}`}>
            {formatBps(toBps(summary.weightedProxyReturnActual))}
          </strong>
          <small>金额合计 {formatNumber(summary.actualTotal)}，按已补价生命周期名义本金加权</small>
        </article>
        <article className="metric-card panel">
          <p className="metric-label">原始收益效率</p>
          <strong className={`metric-value ${getValueTone(toBps(summary.weightedProxyReturnRaw))}`}>
            {formatBps(toBps(summary.weightedProxyReturnRaw))}
          </strong>
          <small>金额合计 {formatNumber(summary.rawTotal)}，用于和当前实际路径做公平比较</small>
        </article>
        <article className="metric-card panel">
          <p className="metric-label">TPSL 标准化净影响</p>
          <strong className={`metric-value ${getValueTone(summary.weightedProxyDeltaBps)}`}>
            {formatBps(summary.weightedProxyDeltaBps)}
          </strong>
          <small>金额合计 {formatNumber(summary.netDeltaTotal)}，正值代表整体保护收益更多</small>
        </article>
      </section>

      <section className="overview-grid spotlight-grid">
        {spotlightCards.map((card) => (
          <article className="panel spotlight-card" key={card.title}>
            <p className="eyebrow">{card.title}</p>
            {card.item ? (
              <>
                <h3>{card.item.strategy_name}</h3>
                <p className="spotlight-subtitle">{card.item.portfolio_id}</p>
                <strong className={`metric-value ${getValueTone(card.value)}`}>{formatBps(card.value)}</strong>
                <p className="spotlight-helper">
                  {card.secondaryLabel} {formatNumber(card.secondaryValue)}
                </p>
                <p className="spotlight-helper">{card.helper}</p>
                <button
                  className="text-link-button"
                  type="button"
                  onClick={() => onOpenStrategy(card.item!.strategy_name, card.item!.portfolio_id)}
                >
                  查看该策略详情
                </button>
              </>
            ) : (
              <div className="empty-state">当前筛选条件下暂无可聚焦的策略。</div>
            )}
          </article>
        ))}
      </section>

      <section className="panel overview-panel">
        <header className="panel-header">
          <div>
            <p className="eyebrow">策略矩阵</p>
            <h3>点击任一策略进入详情页</h3>
          </div>
          <span className="section-meta">{filteredItems.length} 个可分析实例</span>
        </header>

        {isLoading ? <div className="loading-card">正在加载概览数据…</div> : null}
        {!isLoading && !filteredItems.length ? <div className="empty-state">当前筛选条件下没有可展示的策略概览数据。</div> : null}

        <div className="overview-grid">
          {filteredItems.map((item) => (
            <button
              key={`${item.strategy_name}-${item.portfolio_id}`}
              className="overview-card"
              type="button"
              onClick={() => onOpenStrategy(item.strategy_name, item.portfolio_id)}
            >
              <div className="overview-card-head">
                <div>
                  <p className="overview-card-title">{item.strategy_name}</p>
                  <span className="overview-card-subtitle">{item.portfolio_id}</span>
                </div>
                <span className={`pill ${item.enabled ? "pill-hold" : "pill-alert"}`}>{item.mode}</span>
              </div>

              <div className="overview-metrics">
                <div>
                  <span>实际收益效率</span>
                  <strong className={getValueTone(toBps(item.proxy_return_actual))}>{formatBps(toBps(item.proxy_return_actual))}</strong>
                  <small>金额 {formatNumber(item.realized_pnl_actual_cum)}</small>
                </div>
                <div>
                  <span>原始收益效率</span>
                  <strong className={getValueTone(toBps(item.proxy_return_raw))}>{formatBps(toBps(item.proxy_return_raw))}</strong>
                  <small>金额 {formatNumber(item.realized_pnl_raw_cum)}</small>
                </div>
                <div>
                  <span>TPSL 净影响</span>
                  <strong className={getValueTone(item.proxy_delta_bps)}>{formatBps(item.proxy_delta_bps)}</strong>
                  <small>金额 {formatNumber(item.total_tpsl_net_delta)}</small>
                </div>
              </div>

              <div className="overview-stats-row">
                <span>最新交易日 {formatShortDate(item.latest_trade_date)}</span>
                <span>覆盖 {formatPercent(item.priced_coverage_ratio)}</span>
                <span>目标池 {item.latest_target_count}</span>
                <span>买 {item.latest_buy_count}</span>
                <span>卖 {item.latest_sell_count}</span>
              </div>

              <div className="overview-foot">
                <span className="is-positive">正贡献 {item.tpsl_positive_event_count}</span>
                <span className="is-negative">负贡献 {item.tpsl_negative_event_count}</span>
                <span>费拖 {formatBps(item.fee_drag_bps)}</span>
                <span>税拖 {formatBps(item.tax_drag_bps)}</span>
                <span>持仓中 {item.open_position_count}</span>
              </div>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}
