/**
 * 用途：定义 insights 前端开发与构建配置。
 * 参数：
 *   无，Vite 会在启动时自动读取本配置。
 * 返回值：
 *   适用于 React 单页应用的 Vite 配置对象。
 * 异常/边界：
 *   当前开发代理仅覆盖 `/api`，若后端前缀变化需同步调整。
 */
declare const _default: import("vite").UserConfig;
export default _default;
