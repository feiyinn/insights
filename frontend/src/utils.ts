/**
 * 用途：将 ISO 日期字符串格式化为简洁的月-日文本。
 * 参数：
 *   value：后端返回的日期或时间字符串。
 * 返回值：
 *   适合图表和表格展示的日期文本。
 * 异常/边界：
 *   当传入值为空或非法日期时，返回原始字符串，避免页面崩溃。
 */
export function formatShortDate(value: string | null): string {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/**
 * 用途：将 ISO 时间字符串格式化为简洁的月-日 时:分文本。
 * 参数：
 *   value：后端返回的时间字符串。
 * 返回值：
 *   适合时间线或表格展示的文本。
 * 异常/边界：
 *   当输入为空时返回 `--`，非法日期则回退原始字符串。
 */
export function formatDateTime(value: string | null): string {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${formatShortDate(value)} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/**
 * 用途：将数字格式化为两位小数，便于在卡片和表格中统一展示。
 * 参数：
 *   value：待格式化数值。
 *   fallback：值为空时的回退文本。
 * 返回值：
 *   经过千分位与小数位处理后的文本。
 * 异常/边界：
 *   `0` 会被正常展示，不会误判为空值。
 */
export function formatNumber(value: number | null | undefined, fallback = "--"): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback;
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(value);
}

/**
 * 用途：将比例值格式化为百分比文本。
 * 参数：
 *   value：0 到 1 之间的比例值。
 *   fallback：为空时的回退文本。
 * 返回值：
 *   带百分号的格式化字符串。
 * 异常/边界：
 *   当输入为空时返回回退文本，不会展示 `NaN%`。
 */
export function formatPercent(value: number | null | undefined, fallback = "--"): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback;
  }
  return `${(value * 100).toFixed(2)}%`;
}

/**
 * 用途：将相对倍数格式化为易读的 x 倍文本。
 * 参数：
 *   value：相对倍数。
 *   fallback：为空时的回退文本。
 * 返回值：
 *   形如 `1.08x` 的文本。
 * 异常/边界：
 *   当输入为空时返回回退文本。
 */
export function formatMultiplier(value: number | null | undefined, fallback = "--"): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback;
  }
  return `${value.toFixed(2)}x`;
}

/**
 * 用途：将 bps 数值格式化为便于比较的文本。
 * 参数：
 *   value：待格式化的 bps 数值。
 *   fallback：为空时的回退文本。
 * 返回值：
 *   形如 `12.34 bps` 的文本。
 * 异常/边界：
 *   当输入为空时返回回退文本，不会展示 `NaN bps`。
 */
export function formatBps(value: number | null | undefined, fallback = "--"): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback;
  }
  return `${formatNumber(value)} bps`;
}

/**
 * 用途：把收益率小数转换为 bps 数值。
 * 参数：
 *   value：例如 `0.0123` 形式的收益率小数。
 * 返回值：
 *   对应的 bps 数值；为空时返回 `null`。
 * 异常/边界：
 *   当输入为空或非法数字时返回 `null`，避免前端重复做空值判断。
 */
export function toBps(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return null;
  }
  return value * 10000;
}

/**
 * 用途：根据收益或贡献值返回适合强调语义的样式类名。
 * 参数：
 *   value：待判断的数值。
 * 返回值：
 *   `is-positive`、`is-negative` 或 `is-neutral`。
 * 异常/边界：
 *   空值统一视作中性。
 */
export function getValueTone(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "is-neutral";
  }
  if (value > 0) {
    return "is-positive";
  }
  if (value < 0) {
    return "is-negative";
  }
  return "is-neutral";
}
