# backend

## 用途

`backend` 是 `insights` 项目的分析 API 服务，负责：

- 连接 PostgreSQL `insights` schema
- 提供策略维表、日度分析、TPSL 干预分析接口
- 后续承接 MySQL 目标池同步与分析任务调度

## 启动前准备

1. 使用 `uv` 安装依赖
2. 配置环境变量，参考：
   [.env.example](/Users/yinfei/MyProjects/insights/.env.example)
3. 若需要反事实补价，请额外配置 ClickHouse：
   - `INSIGHTS_CLICKHOUSE_HOST`
   - `INSIGHTS_CLICKHOUSE_PORT`
   - `INSIGHTS_CLICKHOUSE_USER`
   - `INSIGHTS_CLICKHOUSE_PASSWORD`
   - `INSIGHTS_CLICKHOUSE_DATABASE`
   - `INSIGHTS_CLICKHOUSE_SECURE`
4. 若需要从 MySQL 同步目标池，请配置：
   - `INSIGHTS_MYSQL_DSN`
   - `INSIGHTS_MYSQL_SCHEMA`
   - `INSIGHTS_MYSQL_MIN_TRADE_DATE`

## 建议启动命令

```bash
uv run uvicorn backend.app.main:app --reload
```

## 同步分析基础数据

```bash
uv run python -m backend.app.jobs.sync_strategy_data
```

该命令会执行：

- 从 MySQL 同步策略目标池到 `insights.fact_strategy_target`
- 重建原始调仓动作到 `insights.fact_strategy_action_raw`
- 当前默认只同步 `INSIGHTS_MYSQL_MIN_TRADE_DATE` 及之后的目标池数据
- 同步时会按策略全量刷新 `fact_strategy_target` 与 `fact_strategy_action_raw`，自动清掉旧的历史快照
- 更新 `insights.etl_job_run` 运行记录

## 同步真实执行与 TPSL 干预事实

```bash
uv run python -m backend.app.jobs.sync_execution_facts
```

该命令会执行：

- 从 `trading.ord_order + trading.exec_fill` 同步真实执行到 `insights.fact_order_execution`
- 从 `trading.pos_tp_sl_exit_intent` 同步 TPSL 干预到 `insights.fact_tpsl_intervention`
- 结合 `insights.fact_strategy_target` 标注下一次原始目标池是否仍继续持有该标的

## 同步持仓生命周期与策略日度分析

```bash
uv run python -m backend.app.jobs.sync_performance_facts
```

该命令会执行：

- 从 `trading.pos_position_lot` 重建单次开仓到退出的生命周期，写入 `insights.fact_position_lifecycle`
- 将 TPSL 实际退出与原始目标池卖出时点拼接到同一生命周期上
- 若已配置 ClickHouse，则用 `cnstock.kline_1m` 为原始路径补价，并计算 `pnl_raw / pnl_delta`
- 同步 TPSL 干预的 `protected_pnl / missed_pnl / net_pnl_delta`
- 按交易日聚合已实现收益、TPSL 退出次数、回补买入次数、持仓开平状态与 TPSL 净影响，写入 `insights.fact_strategy_daily`

## 同步参数实验室代理回放结果

```bash
uv run python -m backend.app.jobs.sync_counterfactual_facts
```

该命令会执行：

- 基于 `fact_strategy_daily` 的 `raw_daily + tpsl_positive_delta + tpsl_negative_delta` 拆解生成首版代理实验曲线
- 写入 `insights.fact_tpsl_counterfactual`
- 为参数实验室提供 `raw_baseline`、`current_live`、`balanced_guard`、`loose_guard`、`tight_guard` 等对照方案
- 在 `result_payload.method` 中明确标注为 `proxy_heuristic_v1`，避免与未来的分钟级真实回放混淆

## 当前可用接口

- `GET /api/health`
- `GET /api/overview/strategies`
- `GET /api/strategies`
- `GET /api/strategies/{strategy_name}/targets/latest`
- `GET /api/strategies/{strategy_name}/actions/latest`
- `GET /api/strategies/{strategy_name}/tpsl/interventions`
- `GET /api/strategies/{strategy_name}/tpsl/summary`
- `GET /api/strategies/{strategy_name}/lifecycles`
- `GET /api/strategies/{strategy_name}/daily`
- `GET /api/strategies/{strategy_name}/parameter-lab`

其中以下接口支持可选查询参数 `portfolio_id`，用于在同名策略实例之间进一步过滤：

- `GET /api/strategies/{strategy_name}/tpsl/interventions?portfolio_id=...`
- `GET /api/strategies/{strategy_name}/tpsl/summary?portfolio_id=...`
- `GET /api/strategies/{strategy_name}/lifecycles?portfolio_id=...`
- `GET /api/strategies/{strategy_name}/daily?portfolio_id=...`
- `GET /api/strategies/{strategy_name}/parameter-lab?portfolio_id=...`

## 当前口径说明

- `fact_position_lifecycle` 中的 `exit_ts_raw` 已优先贴合真实调仓执行窗口估算
- 已配置 ClickHouse 时，`exit_price_raw / pnl_raw / pnl_delta` 会基于 `cnstock.kline_1m` 的 `vwap` 优先补价
- `fact_tpsl_intervention` 已输出单次干预的 `protected_pnl / missed_pnl / net_pnl_delta`
- `fact_strategy_daily` 已输出日度 `raw` 已实现收益与 TPSL 净影响；`nav_* / return_* / drawdown_*` 将在接入完整净值回放后补齐
- `fact_tpsl_counterfactual` 当前是“代理回放首版”，用于先支撑参数实验室；未来仍建议补上完整分钟级历史回放
