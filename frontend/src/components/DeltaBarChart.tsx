import { formatNumber, formatShortDate } from "../utils";

interface DeltaBarChartProps {
  labels: string[];
  values: number[];
}

/**
 * 用途：绘制按交易日聚合的 TPSL 净影响柱状图。
 * 参数：
 *   labels：柱体对应的日期标签。
 *   values：净影响数值列表。
 * 返回值：
 *   用于展示正负贡献的简洁柱状图组件。
 * 异常/边界：
 *   当无数据时回退为空态；当数值全为 0 时仍保留零轴以保证可读性。
 */
export function DeltaBarChart({ labels, values }: DeltaBarChartProps) {
  if (!values.length) {
    return (
      <section className="panel">
        <header className="panel-header">
          <div>
            <p className="eyebrow">TPSL 日度净影响</p>
            <h3>暂时没有可用样本</h3>
          </div>
        </header>
      </section>
    );
  }

  const peak = Math.max(...values.map((value) => Math.abs(value)), 1);

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <p className="eyebrow">TPSL 日度净影响</p>
          <h3>正负贡献条形图</h3>
        </div>
      </header>
      <div className="delta-bars">
        {values.map((value, index) => {
          const percentage = Math.min((Math.abs(value) / peak) * 100, 100);
          const tone = value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
          return (
            <div className="delta-row" key={`${labels[index]}-${index}`}>
              <span className="delta-label">{formatShortDate(labels[index])}</span>
              <div className="delta-track">
                <div className={`delta-fill ${tone}`} style={{ width: `${percentage}%` }} />
              </div>
              <span className={`delta-value ${tone}`}>{formatNumber(value)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
