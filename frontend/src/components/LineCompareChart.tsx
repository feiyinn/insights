import { useId } from "react";

import { formatNumber, formatShortDate } from "../utils";

interface ChartPoint {
  label: string;
  actual: number | null;
  raw: number | null;
}

interface LineCompareChartProps {
  title: string;
  points: ChartPoint[];
}

/**
 * 用途：绘制“实际路径 vs 原始路径”的双线对比图。
 * 参数：
 *   title：图表标题。
 *   points：按时间顺序排列的收益点数据。
 * 返回值：
 *   用于仪表板展示的 SVG 折线图组件。
 * 异常/边界：
 *   当有效点数不足两条时会回退为空态提示，避免生成无意义图形。
 */
export function LineCompareChart({ title, points }: LineCompareChartProps) {
  const gradientId = useId();
  const width = 720;
  const height = 260;
  const paddingX = 24;
  const paddingTop = 24;
  const paddingBottom = 38;
  const chartWidth = width - paddingX * 2;
  const chartHeight = height - paddingTop - paddingBottom;

  const actualSeries = points
    .map((point, index) => ({ index, value: point.actual }))
    .filter((point): point is { index: number; value: number } => point.value !== null);
  const rawSeries = points
    .map((point, index) => ({ index, value: point.raw }))
    .filter((point): point is { index: number; value: number } => point.value !== null);

  const mergedValues = [...actualSeries.map((point) => point.value), ...rawSeries.map((point) => point.value)];
  if (mergedValues.length < 2 || points.length < 2) {
    return (
      <section className="panel chart-panel">
        <header className="panel-header">
          <div>
            <p className="eyebrow">收益比较</p>
            <h3>{title}</h3>
          </div>
        </header>
        <div className="empty-state">当前样本不足，暂时还画不出可比较的收益曲线。</div>
      </section>
    );
  }

  const minValue = Math.min(...mergedValues);
  const maxValue = Math.max(...mergedValues);
  const safeMax = maxValue === minValue ? maxValue + 1 : maxValue;
  const yAt = (value: number) => paddingTop + chartHeight - ((value - minValue) / (safeMax - minValue)) * chartHeight;
  const xAt = (index: number) => paddingX + (index / (points.length - 1)) * chartWidth;

  const buildPath = (series: Array<{ index: number; value: number }>) =>
    series
      .map((point, seriesIndex) => `${seriesIndex === 0 ? "M" : "L"} ${xAt(point.index).toFixed(2)} ${yAt(point.value).toFixed(2)}`)
      .join(" ");

  const actualPath = buildPath(actualSeries);
  const rawPath = buildPath(rawSeries);
  const areaPath = `${actualPath} L ${xAt(actualSeries.at(-1)?.index ?? 0).toFixed(2)} ${(paddingTop + chartHeight).toFixed(2)} L ${xAt(actualSeries[0]?.index ?? 0).toFixed(2)} ${(paddingTop + chartHeight).toFixed(2)} Z`;
  const yTicks = [minValue, (minValue + safeMax) / 2, safeMax];

  return (
    <section className="panel chart-panel">
      <header className="panel-header">
        <div>
          <p className="eyebrow">收益比较</p>
          <h3>{title}</h3>
        </div>
        <div className="chart-legend">
          <span><i className="legend-dot actual" /> 实际路径</span>
          <span><i className="legend-dot raw" /> 原始路径</span>
        </div>
      </header>
      <svg viewBox={`0 0 ${width} ${height}`} className="compare-chart" role="img" aria-label={title}>
        <defs>
          <linearGradient id={gradientId} x1="0%" x2="0%" y1="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 125, 78, 0.32)" />
            <stop offset="100%" stopColor="rgba(255, 125, 78, 0)" />
          </linearGradient>
        </defs>
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={paddingX}
              x2={width - paddingX}
              y1={yAt(tick)}
              y2={yAt(tick)}
              className="chart-grid"
            />
            <text x={paddingX} y={yAt(tick) - 6} className="chart-label">
              {formatNumber(tick)}
            </text>
          </g>
        ))}
        <path d={areaPath} fill={`url(#${gradientId})`} />
        <path d={rawPath} className="chart-line raw" />
        <path d={actualPath} className="chart-line actual" />
        {points.map((point, index) => (
          <text key={`${point.label}-${index}`} x={xAt(index)} y={height - 10} textAnchor="middle" className="chart-axis-label">
            {formatShortDate(point.label)}
          </text>
        ))}
      </svg>
    </section>
  );
}
