# insights 系统设计

## 1. 目标

`insights` 的核心目标，是把交易系统中的三条路径拆开分析：

1. 原始策略路径
   只看每日调仓策略本来应该如何建仓、持仓、调仓。
2. 实际执行路径
   看真实发生的 `STRAT` 策略单与 `TPSL` 风控单。
3. 干预归因路径
   分析 TPSL 对原始策略造成了哪些偏离，以及这些偏离是正向还是负向。

系统最终需要回答的问题包括：

- 哪些收益来自原始策略本身
- 哪些收益变化来自 TPSL 干预
- TPSL 是否降低了回撤
- TPSL 是否因为阈值过紧而提前止盈止损
- 哪类参数组合更适合当前策略

## 2. 当前业务事实

### 2.1 每日调仓逻辑

当前每日调仓逻辑可以概括为：

1. MySQL 策略表每日生成一批最新目标持仓列表
2. `daily_trading.py` 读取该批次列表
3. 再与当前组合真实持仓做差集
4. 生成原始 `buy_list` / `sell_list`
5. 最终通过 `TradeManager.submit_order_ewa()` 下单

因此，原始策略意图本质上是：

- 当日目标池
- 调仓前真实持仓
- 两者差集得到的原始买卖动作

### 2.2 TPSL 逻辑

TPSL 并不改变目标池，而是在持仓建立后持续监控价格路径，并在满足条件时发出退出动作。

目前已确认：

- `STRAT` 表示原始策略订单
- `TPSL` 表示风控触发的退出订单
- TPSL 的触发类型主要包括：
  - `SL`
  - `BE`
  - `TSL`

### 2.3 已验证的重要现象

以 `投顾策略1` 为例，已通过数据库核对确认：

- MySQL 目标池的相邻两批之间，原始策略层面仅有少量标的发生变化
- 但 PostgreSQL 中实际在 14:40 左右执行的 `STRAT` 订单，出现了更多买入动作
- 原因是部分标的在日内已被 TPSL 提前卖出，导致 14:40 的原始调仓阶段出现“缺仓回补”

这说明：

- 原始策略收益不能直接用真实成交替代
- 必须显式重建“未受 TPSL 干预的原始策略路径”

## 3. 系统总体架构

建议系统采用四层结构：

```text
MySQL 策略源 + PostgreSQL 交易事实 + 历史行情源
                ↓
          分析归因层
                ↓
          分析 API 服务
                ↓
              Web UI
```

### 3.1 数据源层

#### MySQL

职责：

- 提供每日调仓策略的目标持仓列表
- 作为原始策略意图来源

当前可用字段：

- `trade_date`
- `code`
- `name`
- `rank`
- `time_tag`

#### PostgreSQL

职责：

- 提供真实订单与成交事实
- 提供持仓状态与 TPSL 干预事实

核心表：

- `trading.strategy_portfolio`
- `trading.ord_order`
- `trading.exec_fill`
- `trading.pos_position_lot`
- `trading.pos_tp_sl_position_state`
- `trading.pos_tp_sl_exit_intent`

#### 历史行情源

职责：

- 提供反事实估值
- 支撑参数回放实验

建议后续接入：

- ClickHouse 历史 K 线
- 或等价的分钟线 / 日线行情库

### 3.2 分析归因层

职责：

- 把策略目标池、真实持仓、真实成交、TPSL 干预串成统一分析视图
- 产出原始策略收益、实际收益和干预偏差

### 3.3 分析 API 层

建议技术：

- `FastAPI`
- `SQLAlchemy` 或 `asyncpg`

职责：

- 向前端提供聚合分析结果
- 支持按策略、组合、日期区间、TPSL 类型钻取
- 为回放实验提供异步任务接口

### 3.4 Web UI 层

建议技术：

- `React`
- `TypeScript`
- `Vite`
- `ECharts`

职责：

- 提供收益曲线、回撤曲线、TPSL 归因图表
- 提供单标的、单仓位生命周期回放界面
- 提供参数实验室

## 4. 核心归因规则

## 4.1 原始目标池

对某策略某日，取 MySQL 中最新 `time_tag` 对应的全部标的集合，记为：

- `target_set(d)`

对上一批目标池记为：

- `target_set(d-1)`

## 4.2 原始调仓动作

在不考虑 TPSL 干预的前提下，原始策略动作定义为：

- 原始应买入：
  `target_set(d) - raw_holdings_before_rebalance(d)`
- 原始应卖出：
  `raw_holdings_before_rebalance(d) - target_set(d)`

这里最关键的是：

- `raw_holdings_before_rebalance(d)` 不能直接使用实际持仓
- 需要使用“未被 TPSL 干预时应当保留的持仓路径”重建

## 4.3 卖出归因分类

系统中每笔卖出应归入以下类别之一：

### A. 原始调仓卖出

满足条件：

- 标的在下一批目标池中不存在
- 且卖出动作符合原始策略差集逻辑

### B. TPSL 提前卖出

满足条件：

- 标的在下一批目标池中仍然存在
- 但在下一次调仓前被 TPSL 卖出

这是分析“TPSL 是否过敏”的核心类别。

### C. TPSL 提前执行原始卖出

满足条件：

- 标的在下一批目标池中不存在
- 但在正式调仓前已被 TPSL 卖出

这种情况应理解为：

- TPSL 改变了卖出时点
- 但不一定改变最终方向

### D. 策略回补买入

满足条件：

- 标的本来应继续持有
- 但因日内 TPSL 先卖出
- 到调仓时因仍在目标池中被重新买回

这种情况很重要，因为它常常意味着：

- TPSL 造成了额外交易成本
- TPSL 可能带来了无效干预

## 5. 分析数据模型

建议在 PostgreSQL 中新增 `analytics` schema，沉淀分析结果。

### 5.1 `analytics.dim_strategy`

用途：

- 策略与组合映射

建议字段：

- `strategy_name`
- `portfolio_id`
- `mode`
- `enabled`
- `created_at`
- `updated_at`

### 5.2 `analytics.fact_strategy_target`

用途：

- 保存 MySQL 每日目标池快照

建议字段：

- `trade_date`
- `strategy_name`
- `batch_time_tag`
- `instrument_id`
- `rank`
- `instrument_name`
- `is_latest_batch`

### 5.3 `analytics.fact_strategy_action_raw`

用途：

- 保存原始策略层面的每日调仓动作

建议字段：

- `trade_date`
- `strategy_name`
- `portfolio_id`
- `instrument_id`
- `action_type`
  - `BUY`
  - `SELL`
  - `HOLD`
- `reason_type`
  - `NEW_ENTRY`
  - `REMOVE_FROM_TARGET`
  - `CONTINUE_HOLD`
- `before_in_target`
- `after_in_target`
- `before_rank`
- `after_rank`
- `batch_time_tag`

### 5.4 `analytics.fact_order_execution`

用途：

- 统一真实订单与成交

建议字段：

- `order_id`
- `exec_id`
- `portfolio_id`
- `strategy_name`
- `instrument_id`
- `trade_ts`
- `side`
- `qty`
- `price`
- `fee`
- `tax`
- `source_type`
  - `STRAT`
  - `TPSL`
- `tactic_id`
- `client_order_id`

### 5.5 `analytics.fact_tpsl_intervention`

用途：

- 保存 TPSL 干预事实

建议字段：

- `intent_id`
- `portfolio_id`
- `strategy_name`
- `instrument_id`
- `position_state_id`
- `level_type`
- `level_index`
- `trigger_ts`
- `fill_ts`
- `filled_qty`
- `fill_price`
- `trigger_reason`
- `parent_order_id`
- `is_pre_rebalance_exit`
- `next_rebalance_trade_date`
- `next_target_still_holding`

### 5.6 `analytics.fact_position_lifecycle`

用途：

- 以单次持仓生命周期为粒度做收益与干预分析

建议字段：

- `lifecycle_id`
- `portfolio_id`
- `strategy_name`
- `instrument_id`
- `entry_ts`
- `entry_price`
- `entry_qty`
- `exit_ts_actual`
- `exit_price_actual`
- `exit_reason_actual`
  - `TPSL_SL`
  - `TPSL_BE`
  - `TPSL_TSL`
  - `RAW_REBALANCE`
  - `OPEN`
- `exit_ts_raw`
- `exit_price_raw`
- `exit_reason_raw`
- `holding_minutes_actual`
- `holding_minutes_raw`
- `pnl_actual`
- `pnl_raw`
- `pnl_delta`
- `max_favorable_excursion`
- `max_adverse_excursion`

### 5.7 `analytics.fact_strategy_daily`

用途：

- 保存策略日度收益与归因结果

建议字段：

- `trade_date`
- `strategy_name`
- `portfolio_id`
- `nav_actual`
- `nav_raw`
- `daily_return_actual`
- `daily_return_raw`
- `cum_return_actual`
- `cum_return_raw`
- `drawdown_actual`
- `drawdown_raw`
- `turnover_actual`
- `tpsl_exit_count`
- `tpsl_reentry_count`
- `tpsl_positive_delta`
- `tpsl_negative_delta`
- `tpsl_net_delta`

### 5.8 `analytics.fact_tpsl_counterfactual`

用途：

- 保存参数回放结果

建议字段：

- `experiment_id`
- `strategy_name`
- `portfolio_id`
- `param_profile`
- `date_from`
- `date_to`
- `cum_return`
- `max_drawdown`
- `sharpe`
- `win_rate`
- `trade_count`
- `tpsl_trigger_count`
- `avg_hold_minutes`
- `net_delta_vs_baseline`

## 6. 核心指标

### 6.1 策略层指标

- 累计收益
- 日收益
- 最大回撤
- 换手率
- 手续费占比
- 胜率
- 平均持仓时长

### 6.2 TPSL 效果指标

- TPSL 触发次数
- 各类型触发占比
- TPSL 净增益
- TPSL 保护收益
- TPSL 错失收益
- TPSL 回补次数
- TPSL 过敏率

### 6.3 关键定义

#### TPSL 保护收益

对于止损类退出，比较：

- 实际退出价格
- 退出后窗口期最低价

估算避免的额外损失。

#### TPSL 错失收益

对于止盈/保本/跟踪止损退出，比较：

- 实际退出价格
- 退出后窗口期最高价

估算提前卖出导致的上涨收益损失。

#### TPSL 净增益

定义为：

- `TPSL 保护收益 - TPSL 错失收益`

#### TPSL 过敏率

定义为：

- TPSL 卖出后，在短时间窗口内价格恢复并显著高于退出价的事件占比

建议窗口：

- `30m`
- `1d`
- `next_rebalance`

## 7. Web UI 设计

## 7.1 页面一：策略总览

目标：

- 快速查看各策略整体表现

模块：

- 策略列表卡片
- 实际收益曲线
- 原始收益曲线
- TPSL 净增益排行
- 回撤与换手概览

核心图表：

- `原始收益 vs 实际收益` 双线图
- `TPSL 净增益` 柱状图
- `触发次数按 level_type 分布` 堆叠图

## 7.2 页面二：策略归因分析

目标：

- 直接回答“TPSL 是帮助还是拖累”

模块：

- 时间区间选择器
- 原始策略收益与实际收益对比
- TPSL 增益分解
- 回撤改善对比

核心图表：

- `cum_return_raw` 与 `cum_return_actual`
- `drawdown_raw` 与 `drawdown_actual`
- `tpsl_net_delta` 时间序列

## 7.3 页面三：TPSL 效果分析

目标：

- 分析 `SL / BE / TSL / TP` 哪类规则最好，哪类最敏感

模块：

- 规则类型分布
- 每类规则的净增益
- 每类规则的错失收益
- 每类规则的保护收益

核心图表：

- `level_type` 维度的瀑布图
- `触发后收益路径` 箱线图
- `退出后未来价格分布` 小提琴图

## 7.4 页面四：持仓生命周期

目标：

- 针对单只标的、单次持仓做精细复盘

展示内容：

- 开仓时间、价格、数量
- TPSL 触发点
- 实际退出点
- 原始策略预期退出点
- 退出后价格继续走势

核心图表：

- K 线图 + 事件标记
- 生命周期时间线

## 7.5 页面五：参数实验室

目标：

- 调整 TPSL 参数，做历史回放比较

支持参数：

- `hard_sl.target_mult`
- `be.min_profit_mult`
- `trailing_bps`
- `atr_enabled`
- `atr_period`
- `atr_distance`

输出：

- 收益
- 回撤
- 触发次数
- 过敏率
- 与基线差值

## 8. API 设计

建议 API 分组如下：

### 8.1 策略概览

- `GET /api/strategies`
- `GET /api/strategies/{strategy_name}/summary`
- `GET /api/strategies/{strategy_name}/daily-performance`

### 8.2 TPSL 分析

- `GET /api/strategies/{strategy_name}/tpsl/summary`
- `GET /api/strategies/{strategy_name}/tpsl/events`
- `GET /api/strategies/{strategy_name}/tpsl/by-level`

### 8.3 生命周期分析

- `GET /api/strategies/{strategy_name}/lifecycles`
- `GET /api/lifecycles/{lifecycle_id}`

### 8.4 回放实验

- `POST /api/experiments`
- `GET /api/experiments/{experiment_id}`
- `GET /api/experiments/{experiment_id}/result`

## 9. 计算流程设计

## 9.1 每日批处理

建议每日调度一条分析任务：

1. 拉取 MySQL 最新目标池
2. 写入 `analytics.fact_strategy_target`
3. 重建原始策略动作
4. 读取 PostgreSQL 真实订单、成交、TPSL intent
5. 生成归因结果
6. 更新日度分析表

## 9.2 生命周期重建

核心思路：

1. 以 `STRAT BUY` 建立生命周期入口
2. 若后续被 TPSL 卖出，则标记为实际退出
3. 若下一次调仓目标池中仍有该标的，则说明 TPSL 提前改变了持仓路径
4. 需要用下一次调仓价或历史行情补足原始退出估值

## 9.3 反事实估值

为了计算 `pnl_raw`，建议分两阶段：

### 阶段一：近似估值

先用以下价格近似：

- 下一次原始调仓成交价
- 若无下一次成交，则用下一次调仓时点市场价格
- 若仍无，则用日线收盘价

### 阶段二：精确回放

接入历史分钟线后，按原始策略持仓路径做精确回放。

## 10. 第一阶段 MVP 范围

建议先做不依赖历史行情回放的 MVP：

### MVP 包含

- 策略列表与组合映射
- MySQL 目标池快照同步
- PostgreSQL 真实交易与 TPSL 事件同步
- 原始策略动作重建
- 实际收益与原始收益近似对比
- TPSL 干预分类
- Web UI 总览页与归因页

### MVP 不包含

- 参数回放引擎
- 历史分钟线精确模拟
- 自动参数搜索

## 11. 第二阶段扩展

### 二期能力

- 接入历史行情
- 精确反事实回放
- 参数实验室
- 自动寻找更优 TPSL 参数区间

### 三期能力

- 多策略对比
- 多 profile 对比
- 规则敏感性自动诊断
- 参数推荐系统

## 12. 当前开发建议

建议按以下顺序推进：

1. 初始化 `insights` 项目骨架
2. 建立 PostgreSQL `analytics` schema
3. 实现 MySQL 目标池同步脚本
4. 实现原始动作重建逻辑
5. 实现 `STRAT / TPSL` 归因逻辑
6. 先做后端 API
7. 再做前端看板

## 13. 已有事实对设计的直接支撑

当前数据库已经支持以下关键分析能力：

- 能从 MySQL 读取每日目标池
- 能从 PostgreSQL 区分 `STRAT` 与 `TPSL`
- 能识别 TPSL 类型
- 能识别某些标的“原始策略仍想持有，但已被 TPSL 卖出”

这意味着：

- 本项目已经具备进入开发阶段的条件
- 真正需要逐步补齐的，是“反事实价格估值”和“参数回放”能力

## 14. 下一阶段升级设计

围绕“不同资金规模策略的公平比较”和“标的级 TPSL 建议”这两个目标，已补充专项设计文档：

- [`标准化绩效指标与标的级参数实验室设计`](./standardized_metrics_symbol_lab_design.md)

本轮设计重点明确了：

- 标准化绩效指标分为两阶段推进：
  - 第一阶段先基于 `fact_position_lifecycle` 计算“名义本金代理收益率 / bps”
  - 第二阶段在接入完整日度盯市后，正式填充 `fact_strategy_daily` 中已有的 `return / drawdown / nav` 字段
- 参数实验室从“策略级建议”升级为“标的级诊断 + 标的级建议”
- 新增两张分析事实表：
  - `insights.fact_symbol_tpsl_diagnostics`
  - `insights.fact_symbol_tpsl_recommendation`
- 对应 SQL 草案位于：
  - [`sql/004_add_symbol_tpsl_tables.sql`](../sql/004_add_symbol_tpsl_tables.sql)

执行顺序建议为：

1. 先落地 `fact_symbol_tpsl_diagnostics`
2. 再基于诊断结果生成 `fact_symbol_tpsl_recommendation`
3. 然后扩展参数实验室 API 与前端页面
4. 最后再考虑把建议结果下沉到 `treasure-code` 的下单侧参数覆盖

当前进度补充：

- 标准化绩效指标第一阶段已完成系统级落地：
  - 总览页、策略详情页、参数实验室已支持“双轨展示”
  - 后端接口已输出 `proxy_return_* / proxy_delta_bps / fee_drag_bps / priced_coverage_ratio` 等字段
- 标的级参数实验室已完成：
  - 诊断表
  - 建议表
  - 前端详情与导出闭环
- 尚未完成的部分主要是标准化绩效第二阶段：
  - 完整净值回放
  - 正式 `nav / return / drawdown / risk-adjusted return` 指标
