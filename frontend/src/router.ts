export type AppRoute =
  | {
      name: "overview";
    }
  | {
      name: "detail";
      strategyName: string;
      portfolioId: string | null;
    }
  | {
      name: "parameterLab";
      strategyName: string;
      portfolioId: string | null;
    };

/**
 * 用途：解析当前浏览器 hash，得到前端页面路由状态。
 * 参数：
 *   hash：浏览器地址栏中的 hash 字符串。
 * 返回值：
 *   规范化后的概览页或详情页路由对象。
 * 异常/边界：
 *   当 hash 为空或格式不合法时，统一回退到概览页。
 */
export function parseRouteFromHash(hash: string): AppRoute {
  const normalized = hash.replace(/^#/, "");
  if (!normalized || normalized === "/" || normalized === "") {
    return { name: "overview" };
  }

  const labMatch = normalized.match(/^\/strategies\/([^/?]+)\/lab(?:\?(.*))?$/);
  if (labMatch) {
    const strategyName = decodeURIComponent(labMatch[1]);
    const searchParams = new URLSearchParams(labMatch[2] ?? "");
    return {
      name: "parameterLab",
      strategyName,
      portfolioId: searchParams.get("portfolio_id"),
    };
  }

  const detailMatch = normalized.match(/^\/strategies\/([^?]+)(?:\?(.*))?$/);
  if (!detailMatch) {
    return { name: "overview" };
  }

  const strategyName = decodeURIComponent(detailMatch[1]);
  const searchParams = new URLSearchParams(detailMatch[2] ?? "");
  return {
    name: "detail",
    strategyName,
    portfolioId: searchParams.get("portfolio_id"),
  };
}

/**
 * 用途：生成策略详情页对应的 hash 地址。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：可选组合 ID。
 * 返回值：
 *   可直接写入 `window.location.hash` 的地址字符串。
 * 异常/边界：
 *   当 `portfolioId` 为空时，仅输出策略名，不附带查询参数。
 */
export function buildStrategyDetailHash(strategyName: string, portfolioId: string | null): string {
  const base = `#/strategies/${encodeURIComponent(strategyName)}`;
  if (!portfolioId) {
    return base;
  }
  const searchParams = new URLSearchParams({ portfolio_id: portfolioId });
  return `${base}?${searchParams.toString()}`;
}

/**
 * 用途：生成参数实验室页面对应的 hash 地址。
 * 参数：
 *   strategyName：策略名称。
 *   portfolioId：可选组合 ID。
 * 返回值：
 *   可直接写入 `window.location.hash` 的实验室页面地址。
 * 异常/边界：
 *   当 `portfolioId` 为空时，仅输出策略名，不附带查询参数。
 */
export function buildParameterLabHash(strategyName: string, portfolioId: string | null): string {
  const base = `#/strategies/${encodeURIComponent(strategyName)}/lab`;
  if (!portfolioId) {
    return base;
  }
  const searchParams = new URLSearchParams({ portfolio_id: portfolioId });
  return `${base}?${searchParams.toString()}`;
}
