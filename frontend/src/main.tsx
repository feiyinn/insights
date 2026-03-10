import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

/**
 * 用途：挂载 insights 前端单页应用。
 * 参数：
 *   无，入口节点固定为 `#root`。
 * 返回值：
 *   无。
 * 异常/边界：
 *   若页面缺失 `#root`，React 会抛出初始化异常，帮助尽早暴露集成问题。
 */
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
