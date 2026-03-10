# insights

`insights` 是一个独立的交易分析项目，用于分析每日调仓策略的收益表现，以及 TPSL 风险控制对策略收益、回撤和交易路径的影响。

当前阶段的目标不是做交易执行，而是做交易分析与策略归因，重点回答以下问题：

- 每日调仓策略原始上应当获得怎样的收益表现
- 实际在 TPSL 干预后，收益和回撤发生了怎样的变化
- TPSL 是在保护收益，还是因为过于敏感而提前止盈止损
- 应该如何调整 TPSL 参数，减少无效干预

## 项目定位

- 独立项目，不挂载在原有 `treasure-code` 仓库中
- 面向内部研究与分析使用
- 以 Web UI 为主，配套分析 API 与数据归因层

## 当前已确认的数据来源

- PostgreSQL：
  存放真实订单、成交、持仓、TPSL 状态、TPSL intent 等交易事实数据
- MySQL：
  存放每日调仓策略的目标持仓列表，表名即策略名
- 历史行情源：
  后续用于反事实回放和参数实验

## 已验证的重要业务事实

- 每日调仓目标池来自 MySQL 策略表
- `daily_trading.py` 通过“目标池 - 当前持仓”的差集生成原始调仓动作
- PostgreSQL 中可以明确区分：
  - `STRAT`：策略原始交易单
  - `TPSL`：风控退出单
- TPSL 会提前改变原始持仓路径，因此不能只看实际成交，必须引入“原始策略路径”

## 规划目录

```text
insights/
├── README.md
├── docs/
│   └── system_design.md
├── backend/
├── frontend/
└── sql/
```

## 当前输出

- 详细设计文档：
  [docs/system_design.md](/Users/yinfei/MyProjects/insights/docs/system_design.md)
- 测试前检查清单与测试操作手册：
  [docs/testing_guide.md](/Users/yinfei/MyProjects/insights/docs/testing_guide.md)
- PostgreSQL 分析 schema：
  `insights`
- 已落地的核心分析表：
  `dim_strategy`、`fact_strategy_target`、`fact_strategy_action_raw`、`fact_order_execution`、`fact_tpsl_intervention`、`fact_position_lifecycle`、`fact_strategy_daily`
- 已落地的前端首版分析台：
  [frontend/README.md](/Users/yinfei/MyProjects/insights/frontend/README.md)
- 已可直接使用的首版分析 API：
  - `GET /api/overview/strategies`
  - `GET /api/strategies`
  - `GET /api/strategies/{strategy_name}/targets/latest`
  - `GET /api/strategies/{strategy_name}/actions/latest`
  - `GET /api/strategies/{strategy_name}/tpsl/interventions`
  - `GET /api/strategies/{strategy_name}/tpsl/summary`
  - `GET /api/strategies/{strategy_name}/lifecycles`
  - `GET /api/strategies/{strategy_name}/daily`
  - `GET /api/strategies/{strategy_name}/parameter-lab`

## 当前阶段说明

目前系统已经具备“原始目标池 + 真实执行 + TPSL 干预 + 持仓生命周期 + 日度聚合”的首版数据链路。

现阶段已经可以稳定回答：

- 哪些持仓是被 TPSL 提前卖出的
- 哪些 TPSL 卖出在下一次调仓时本来就会卖
- 每个策略每天发生了多少次 TPSL 退出与回补买入
- 实际路径的日度已实现收益与累计已实现收益
- 已有原始退出时点的仓位，在分钟线补价后对应的 `pnl_raw / pnl_delta`
- TPSL 在单次干预与日度聚合层面的 `protected_pnl / missed_pnl / net_pnl_delta`
- 参数实验室中的“当前实际执行 vs 原始未干预基线”默认场景对比
- 基于真实干预分布生成的 TPSL 敏感度诊断与建议试验档位

仍待下一阶段补齐的部分：

- `nav_raw / nav_actual`
- 尚未出现原始退出时点的持仓，其原始路径仍待继续持有或等待后续批次
- 完整的持仓中途持有收益、回撤与净值回放
- TPSL 参数实验与更长区间的反事实收益测算

这部分需要接入历史行情源做补价与回放，目前 ClickHouse 中已经确认有可用的 `cnstock.kline_1m` 与 `cnstock.kline_1d`。
