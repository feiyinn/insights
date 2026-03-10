# frontend

## 用途

`frontend` 是 `insights` 的首版 Web UI，当前聚焦以下分析视图：

- 多策略总览首页与当前组合上下文
- 实际路径 vs 原始路径的累计已实现收益对比
- TPSL 日度净影响与正负贡献摘要
- TPSL 干预明细表
- 持仓生命周期表
- 总览页筛选、排序与问题策略聚焦卡片
- 参数实验室：方案对比、敏感度诊断与建议档位

## 启动方式

先确保后端分析服务已启动在 `http://127.0.0.1:8018`，然后执行：

```bash
npm install --no-fund --no-audit --loglevel=error
npm run dev
```

默认开发地址：

```text
http://127.0.0.1:5173
```

默认页面采用轻量 hash 路由：

```text
#/                              策略总览首页
#/strategies/{strategy_name}?portfolio_id=...
#/strategies/{strategy_name}/lab?portfolio_id=...
```

## 构建命令

```bash
npm run build
```

## 环境变量

如需指定远端 API 地址，可设置：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8018
```

未设置时，开发模式会通过 Vite 代理转发 `/api` 请求。
