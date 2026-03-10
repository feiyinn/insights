import { startTransition, useEffect, useState } from "react";

import { fetchParameterLab, fetchStrategyDetails, fetchStrategyOverview } from "./api";
import { OverviewPage } from "./pages/OverviewPage";
import { ParameterLabPage } from "./pages/ParameterLabPage";
import { StrategyDetailPage } from "./pages/StrategyDetailPage";
import { buildParameterLabHash, buildStrategyDetailHash, parseRouteFromHash, type AppRoute } from "./router";
import type { ParameterLabPayload, StrategyDetailPayload, StrategyOverviewItem } from "./types";

/**
 * 用途：将浏览器当前地址同步为应用内部路由状态。
 * 参数：
 *   setRoute：用于更新路由状态的 React 状态设置函数。
 * 返回值：
 *   无。
 * 异常/边界：
 *   当 hash 为空或非法时会自动回退到概览页，避免页面进入不可恢复的空状态。
 */
function syncRouteFromLocation(setRoute: (route: AppRoute) => void) {
  startTransition(() => {
    setRoute(parseRouteFromHash(window.location.hash));
  });
}

/**
 * 用途：渲染 insights 前端根组件。
 * 参数：
 *   无，页面内部自行维护轻量路由和数据加载状态。
 * 返回值：
 *   含概览页与详情页双页面结构的完整应用。
 * 异常/边界：
 *   当接口请求失败时，会把错误信息显式展示在页面中，避免静默异常。
 */
export default function App() {
  const [route, setRoute] = useState<AppRoute>(() => parseRouteFromHash(window.location.hash));
  const [overviewItems, setOverviewItems] = useState<StrategyOverviewItem[]>([]);
  const [detail, setDetail] = useState<StrategyDetailPayload | null>(null);
  const [parameterLab, setParameterLab] = useState<ParameterLabPayload | null>(null);
  const [isOverviewLoading, setIsOverviewLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isParameterLabLoading, setIsParameterLabLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [parameterLabError, setParameterLabError] = useState<string | null>(null);

  useEffect(() => {
    const onHashChange = () => syncRouteFromLocation(setRoute);
    window.addEventListener("hashchange", onHashChange);

    if (!window.location.hash) {
      window.location.hash = "#/";
    } else {
      onHashChange();
    }

    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    /**
     * 用途：加载首页所需的策略聚合摘要。
     * 参数：
     *   无。
     * 返回值：
     *   无。
     * 异常/边界：
     *   失败时仅更新错误状态，不会强制打断当前详情页浏览。
     */
    async function loadOverview() {
      setIsOverviewLoading(true);
      try {
        const result = await fetchStrategyOverview();
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setOverviewItems(result);
          setOverviewError(null);
        });
      } catch (loadError) {
        if (!cancelled) {
          setOverviewError(loadError instanceof Error ? loadError.message : "策略概览加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsOverviewLoading(false);
        }
      }
    }

    loadOverview();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (route.name !== "detail") {
      return;
    }

    const { strategyName, portfolioId } = route;
    let cancelled = false;
    setIsDetailLoading(true);

    /**
     * 用途：加载当前详情页所需的单策略明细数据。
     * 参数：
     *   无。
     * 返回值：
     *   无。
     * 异常/边界：
     *   切换路由时会中断旧请求的结果写入，避免串页。
     */
    async function loadDetail() {
      try {
        const result = await fetchStrategyDetails(strategyName, portfolioId);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setDetail(result);
          setDetailError(null);
        });
      } catch (loadError) {
        if (!cancelled) {
          setDetailError(loadError instanceof Error ? loadError.message : "策略详情加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsDetailLoading(false);
        }
      }
    }

    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [route]);

  useEffect(() => {
    if (route.name !== "parameterLab") {
      return;
    }

    const { strategyName, portfolioId } = route;
    let cancelled = false;
    setIsParameterLabLoading(true);

    /**
     * 用途：加载当前参数实验室页面所需的聚合数据。
     * 参数：
     *   无。
     * 返回值：
     *   无。
     * 异常/边界：
     *   切换到其他路由时会中断旧请求结果写入，避免实验室页串数据。
     */
    async function loadParameterLab() {
      try {
        const result = await fetchParameterLab(strategyName, portfolioId);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setParameterLab(result);
          setParameterLabError(null);
        });
      } catch (loadError) {
        if (!cancelled) {
          setParameterLabError(loadError instanceof Error ? loadError.message : "参数实验室加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsParameterLabLoading(false);
        }
      }
    }

    loadParameterLab();
    return () => {
      cancelled = true;
    };
  }, [route]);

  /**
   * 用途：跳转到指定策略实例详情页。
   * 参数：
   *   strategyName：策略名称。
   *   portfolioId：组合 ID。
   * 返回值：
   *   无。
   * 异常/边界：
   *   通过 hash 导航实现，因此无需额外前端路由依赖。
   */
  function openStrategy(strategyName: string, portfolioId: string) {
    window.location.hash = buildStrategyDetailHash(strategyName, portfolioId);
  }

  /**
   * 用途：跳转到指定策略实例的参数实验室页面。
   * 参数：
   *   strategyName：策略名称。
   *   portfolioId：组合 ID。
   * 返回值：
   *   无。
   * 异常/边界：
   *   通过 hash 导航实现，因此无需额外路由库。
   */
  function openParameterLab(strategyName: string, portfolioId: string) {
    window.location.hash = buildParameterLabHash(strategyName, portfolioId);
  }

  /**
   * 用途：返回概览首页。
   * 参数：
   *   无。
   * 返回值：
   *   无。
   * 异常/边界：
   *   会同步清理详情页错误状态，避免返回首页后残留错误提示。
   */
  function goToOverview() {
    startTransition(() => {
      setDetailError(null);
      setParameterLabError(null);
    });
    window.location.hash = "#/";
  }

  const selectedOverviewItem =
    route.name !== "overview"
      ? overviewItems.find(
          (item) =>
            item.strategy_name === route.strategyName &&
            (route.portfolioId ? item.portfolio_id === route.portfolioId : true),
        ) ?? null
      : null;

  const currentPortfolioId = route.name === "overview" ? null : route.portfolioId ?? selectedOverviewItem?.portfolio_id ?? null;

  return (
    <div className="app-shell">
      <div className="background-orb orb-a" />
      <div className="background-orb orb-b" />

      <aside className="sidebar">
        <div className="sidebar-section brand-card">
          <p className="brand-kicker">insights</p>
          <h1>交易绩效分析台</h1>
          <p className="brand-copy">先从总览页看策略矩阵，再下钻到单策略详情页分析 TPSL 是否帮了收益，还是提前打断了趋势。</p>
        </div>

        <div className="sidebar-section compact-panel">
          <div className="section-title-row">
            <h2>页面导航</h2>
            <span className="section-meta">{route.name === "overview" ? "总览" : "详情"}</span>
          </div>
          <div className="nav-stack">
            <button
              className={`nav-button ${route.name === "overview" ? "active" : ""}`}
              type="button"
              onClick={goToOverview}
            >
              策略总览首页
            </button>
            {route.name !== "overview" && currentPortfolioId ? (
              <button
                className={`nav-button ${route.name === "detail" ? "active" : ""}`}
                type="button"
                onClick={() => openStrategy(route.strategyName, currentPortfolioId)}
              >
                策略详情页
              </button>
            ) : null}
            {route.name !== "overview" && currentPortfolioId ? (
              <button
                className={`nav-button ${route.name === "parameterLab" ? "active" : ""}`}
                type="button"
                onClick={() => openParameterLab(route.strategyName, currentPortfolioId)}
              >
                参数实验室
              </button>
            ) : null}
            {route.name !== "overview" ? (
              <div className="nav-current-card">
                <span>当前页面</span>
                <strong>{route.strategyName}</strong>
                <small>{currentPortfolioId ?? "--"}</small>
              </div>
            ) : null}
          </div>
        </div>

        <div className="sidebar-section compact-panel">
          <div className="section-title-row">
            <h2>快速切换</h2>
            <span className="section-meta">{overviewItems.length} 个实例</span>
          </div>
          {isOverviewLoading ? <div className="loading-card">正在加载概览目录…</div> : null}
          {overviewError ? <div className="error-banner">{overviewError}</div> : null}
          <div className="strategy-list">
            {overviewItems.map((item) => {
              const isActive =
                route.name !== "overview" &&
                route.strategyName === item.strategy_name &&
                route.portfolioId === item.portfolio_id;
              const openTarget = () => {
                if (route.name === "parameterLab") {
                  openParameterLab(item.strategy_name, item.portfolio_id);
                  return;
                }
                openStrategy(item.strategy_name, item.portfolio_id);
              };
              return (
                <button
                  key={`${item.strategy_name}-${item.portfolio_id}`}
                  className={`strategy-chip ${isActive ? "active" : ""}`}
                  type="button"
                  onClick={openTarget}
                >
                  <span className="strategy-chip-title">{item.strategy_name}</span>
                  <span className="strategy-chip-meta">
                    {item.portfolio_id} · {item.mode}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </aside>

      {route.name === "overview" ? (
        <OverviewPage
          items={overviewItems}
          isLoading={isOverviewLoading}
          onOpenStrategy={openStrategy}
        />
      ) : route.name === "detail" ? (
        <StrategyDetailPage
          strategyName={route.strategyName}
          portfolioId={route.portfolioId}
          overviewItem={selectedOverviewItem}
          detail={detail}
          isLoading={isDetailLoading}
          error={detailError}
          onBack={goToOverview}
        />
      ) : (
        <ParameterLabPage
          strategyName={route.strategyName}
          portfolioId={route.portfolioId}
          overviewItem={selectedOverviewItem}
          payload={parameterLab}
          isLoading={isParameterLabLoading}
          error={parameterLabError}
          onBackToDetail={() => {
            if (currentPortfolioId) {
              openStrategy(route.strategyName, currentPortfolioId);
            }
          }}
        />
      )}
    </div>
  );
}
