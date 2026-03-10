# 标准化绩效指标与标的级参数实验室设计

## 1. 设计目标

本轮升级解决两个核心问题：

1. 不同策略资金规模不同，只看绝对 `pnl` 不公平
2. 当前参数实验室只给“策略级建议”，颗粒度不足以指导单标的调参

因此，下一阶段需要同时推进：

- 建立“标准化绩效指标”体系
- 把参数实验室升级为“标的级诊断 + 标的级建议”

## 1.1 当前落地状态

截至 `2026-03-09`，标准化绩效指标第一阶段已经在 `insights` 中完成系统级落地，当前状态如下：

- 后端接口已支持代理标准化字段：
  - 概览接口返回 `proxy_return_actual`、`proxy_return_raw`、`proxy_delta_bps`
  - 策略日度接口返回累计代理收益率、累计 `delta_bps`、覆盖率与成本拖累
  - 参数实验室策略级诊断返回标准化口径与金额口径双轨结果
- 前端页面已完成双轨展示：
  - 总览页默认主看 `bps`，副看金额
  - 策略详情页新增标准化绩效卡片
  - 参数实验室顶部同时展示单位资金净影响与金额差
- 当前仍处于第一阶段：
  - 分母基于 `fact_position_lifecycle` 的已补价名义本金
  - 尚未切换到正式净值回放口径

因此，这份文档当前既是设计说明，也是已上线第一阶段能力的定义文档。

## 2. 当前约束与已知边界

现有系统已经具备：

- `fact_position_lifecycle`
  - 可以拿到单次持仓的 `entry_price`、`entry_qty`、`pnl_actual`、`pnl_raw`、`pnl_delta`
- `fact_tpsl_intervention`
  - 可以拿到 `protected_pnl`、`missed_pnl`、`net_pnl_delta`
  - 可以识别“仍在目标池内被提前卖出”
- `fact_strategy_daily`
  - 已能稳定输出日度 `realized_pnl_actual_*`、`realized_pnl_raw_*`、`tpsl_net_delta`
- `fact_tpsl_counterfactual`
  - 已能承载“代理回放首版”结果，但当前仍是 `proxy_heuristic_v1`

当前仍然缺失：

- 可直接用于正式收益率计算的完整日度净值路径
- 可直接用于正式回撤计算的日度盯市净值
- 分标的的诊断表与建议表

这意味着标准化指标必须采用“两阶段方案”：

1. 先用现有生命周期数据产出“代理标准化指标”
2. 后续在完整盯市补齐后，再切换到正式收益率、回撤与风险调整收益指标

## 3. 标准化绩效指标设计

## 3.1 设计原则

所有标准化指标需要满足以下原则：

- 可横向比较：不同策略、不同资金体量之间仍可比较
- 可解释：能反映 TPSL 对收益、回撤和交易效率的真实影响
- 可分阶段落地：先做代理指标，再升级为正式净值指标
- 可下钻：策略级、标的级、参数档位级都使用同一套核心定义
- 保留绝对值：新版即使引入收益率、`bps` 与单位资金效率，也必须继续保留金额口径

### 3.1.1 双轨展示原则

新版绩效分析统一采用“双轨展示”：

- 绝对值轨
  - 回答“实际赚了多少钱、亏了多少钱、TPSL 影响了多少金额”
- 标准化轨
  - 回答“单位资金效率如何、不同策略之间是否公平可比”

这两类指标不互相替代，而是互为补充：

- 绝对值适合看业务体量与真实资金影响
- 标准化指标适合看横向比较与参数优劣

因此，后续 API、表结构与前端展示都应遵循：

- 不用标准化指标覆盖绝对值字段
- 不把绝对值字段重命名为收益率字段
- 策略页、详情页、参数实验室都同时保留金额与比例两套表达

## 3.2 第一阶段：基于生命周期的代理标准化指标

第一阶段只依赖现有事实表，不等待完整净值回放。

### 3.2.0 当前系统级落地范围

第一阶段代理标准化指标当前已落到以下系统层面：

- 数据接口
  - `GET /api/overview/strategies`
  - `GET /api/strategies/{strategy_name}/daily`
  - `GET /api/strategies/{strategy_name}/parameter-lab`
- 页面展示
  - 总览页策略矩阵
  - 策略详情页标准化绩效卡片
  - 参数实验室顶部策略级摘要

当前已经稳定输出并展示的核心字段包括：

- 策略级
  - `proxy_return_actual`
  - `proxy_return_raw`
  - `proxy_delta_bps`
  - `fee_drag_bps`
  - `tax_drag_bps`
  - `priced_coverage_ratio`
- 日度累计
  - `proxy_return_actual_cum`
  - `proxy_return_raw_cum`
  - `proxy_delta_bps_cum`
  - `fee_drag_bps_cum`
  - `tax_drag_bps_cum`
  - `proxy_priced_coverage_ratio_cum`
- 参数实验室策略级诊断
  - `proxy_return_actual`
  - `proxy_return_raw`
  - `proxy_delta_bps`

当前 UI 展示约定为：

- 主值优先显示标准化指标
  - 如 `bps`、收益效率、成本拖累
- 副值继续显示绝对金额
  - 如累计收益金额、TPSL 金额净影响

### 3.2.1 统一分母

对于已完成补价的生命周期，定义：

- `entry_notional = entry_price * entry_qty`
- `priced_entry_notional = Σ entry_notional`

这里的 `priced_entry_notional` 是第一阶段最稳定、最可落地的统一分母。

它的优点是：

- 现有 `fact_position_lifecycle` 已经具备
- 不依赖组合总资产快照
- 可以同时用于策略级聚合和标的级聚合

它的限制是：

- 它是“已成交生命周期名义本金”，不是严格意义上的组合净值分母
- 更适合做横向比较和诊断，不应被误写成正式净值收益率

### 3.2.2 策略级代理指标

对于一个策略窗口 `W`，先在所有 `pnl_raw` 已补价的生命周期上计算：

- `proxy_return_actual = Σ pnl_actual / Σ priced_entry_notional`
- `proxy_return_raw = Σ pnl_raw / Σ priced_entry_notional`
- `proxy_delta_return = Σ pnl_delta / Σ priced_entry_notional`
- `proxy_delta_bps = 10000 * proxy_delta_return`

补充效率指标：

- `pnl_per_10k_turnover = 10000 * Σ realized_pnl_actual / Σ turnover_actual`
- `fee_drag_bps = 10000 * Σ fee_total / Σ turnover_actual`
- `tax_drag_bps = 10000 * Σ tax_total / Σ turnover_actual`
- `priced_coverage_ratio = priced_lifecycle_count / total_lifecycle_count`

同时保留绝对值指标：

- `pnl_actual_sum = Σ pnl_actual`
- `pnl_raw_sum = Σ pnl_raw`
- `pnl_delta_sum = Σ pnl_delta`
- `tpsl_positive_pnl_sum = Σ protected_pnl`
- `tpsl_negative_pnl_sum = Σ missed_pnl`

补充行为指标：

- `win_rate_actual_proxy = count(pnl_actual > 0) / priced_lifecycle_count`
- `win_rate_raw_proxy = count(pnl_raw > 0) / priced_lifecycle_count`
- `avg_hold_minutes_actual`
- `avg_hold_minutes_raw`
- `hold_gap_ratio = (avg_hold_minutes_actual - avg_hold_minutes_raw) / avg_hold_minutes_raw`

这套口径适合回答：

- TPSL 在单位名义本金上的净影响到底是正还是负
- 某个策略是不是只是“赚得多”，还是“单位资金效率更高”
- 某个策略的 TPSL 是否带来了更高的交易摩擦

### 3.2.3 标的级代理指标

对于单个标的 `symbol`，在窗口 `W` 上复用同样定义：

- `symbol_proxy_return_actual = Σ symbol.pnl_actual / Σ symbol.priced_entry_notional`
- `symbol_proxy_return_raw = Σ symbol.pnl_raw / Σ symbol.priced_entry_notional`
- `symbol_delta_bps = 10000 * Σ symbol.pnl_delta / Σ symbol.priced_entry_notional`

这使得我们可以在同一策略内部比较：

- 哪些标的是 TPSL 的正贡献来源
- 哪些标的是 TPSL 的主要负贡献来源
- 哪些标的应该放宽，哪些标的应该保持，哪些标的可以略收紧

### 3.2.4 第一阶段的展示要求

第一阶段前端与 API 应同时展示：

- 绝对收益金额
- 代理收益率
- `bps`
- 覆盖率

建议展示关系如下：

- 主指标
  - 策略横向比较默认显示 `proxy_delta_bps` 或 `proxy_return_actual`
- 副指标
  - 同时显示 `pnl_actual_sum`、`pnl_delta_sum`
- 明细表
  - 每行同时展示“金额列”和“比例列”

并明确标注：

- `method = lifecycle_notional_proxy_v1`
- “该收益率为名义本金代理口径，不等于正式组合净值收益率”

这样可以避免前端把代理指标误当成正式收益率。

## 3.3 第二阶段：基于日度盯市的正式标准化指标

当接入完整日度盯市后，应正式填充 `fact_strategy_daily` 中已经预留的字段：

- `nav_actual`
- `nav_raw`
- `daily_return_actual`
- `daily_return_raw`
- `cum_return_actual`
- `cum_return_raw`
- `drawdown_actual`
- `drawdown_raw`

### 3.3.1 正式日度收益率

定义：

- `daily_return_actual = (nav_actual_t / nav_actual_t-1) - 1`
- `daily_return_raw = (nav_raw_t / nav_raw_t-1) - 1`
- `cum_return_actual = Π(1 + daily_return_actual) - 1`
- `cum_return_raw = Π(1 + daily_return_raw) - 1`

### 3.3.2 正式回撤指标

定义：

- `max_drawdown_actual = max(peak(nav_actual) - nav_actual) / peak(nav_actual)`
- `max_drawdown_raw = max(peak(nav_raw) - nav_raw) / peak(nav_raw)`
- `drawdown_improvement_ratio = (max_drawdown_raw - max_drawdown_actual) / max_drawdown_raw`

### 3.3.3 风险调整收益

建议至少补齐以下正式指标：

- 年化收益
- 年化波动
- `Sharpe`
- `Calmar`
- `delta_information_ratio`

其中：

- `delta_information_ratio`
  - 用日度 `actual_return - raw_return` 序列计算
  - 用于描述 TPSL 带来的超额收益是否稳定

### 3.3.4 与现有表的兼容策略

当前 `fact_tpsl_counterfactual.cum_return` 实际承载的是“代理累计收益金额”，语义并不干净。

建议下一阶段统一为：

- `cum_pnl`
  - 存绝对金额
- `cum_return`
  - 只存标准化收益率
- `max_drawdown`
  - 只存正式回撤
- `sharpe`
  - 只存正式风险调整收益

在正式切换前，API 可以同时返回：

- `cum_pnl`
- `proxy_return`
- `proxy_delta_bps`
- `method`
- `pnl_delta`
- `max_drawdown_amount`（若能提供）
- `max_drawdown_ratio`（若能提供）

避免继续把“金额”塞进 `cum_return` 语义里。

## 4. 标的级参数实验室设计

## 4.1 基本分析单元

标的级参数实验室的最小分析单元定义为：

- `strategy_name`
- `portfolio_id`
- `instrument_id`
- `date_from`
- `date_to`

也就是说，建议不直接做“全局某只股票”的统一建议，而是做“某策略某组合下某只股票”的建议。

这样更符合真实交易逻辑，因为：

- 同一标的在不同策略中的建仓节奏不同
- 同一标的在不同策略中的持有时长不同
- 同一标的在不同策略中的 TPSL 表现可能完全相反

## 4.2 诊断指标定义

建议在标的级诊断中至少计算以下指标。

### 4.2.1 样本量与覆盖率

- `total_lifecycles`
- `closed_lifecycles`
- `priced_lifecycles`
- `priced_coverage_ratio = priced_lifecycles / total_lifecycles`
- `tpsl_intervention_count`

### 4.2.2 收益影响

- `pnl_actual_sum`
- `pnl_raw_sum`
- `pnl_delta_sum`
- `delta_bps = 10000 * pnl_delta_sum / priced_entry_notional`
- `return_actual_bps = 10000 * pnl_actual_sum / priced_entry_notional`
- `return_raw_bps = 10000 * pnl_raw_sum / priced_entry_notional`

### 4.2.3 TPSL 行为诊断

- `positive_intervention_count`
  - `net_pnl_delta > 0`
- `negative_intervention_count`
  - `net_pnl_delta < 0`
- `still_in_target_intervention_count`
  - `classification = PRE_REBALANCE_EXIT_STILL_IN_TARGET`
- `removed_from_target_intervention_count`
  - `classification = PRE_REBALANCE_EXIT_REMOVED_FROM_TARGET`
- `no_next_target_intervention_count`
  - `classification = INTRADAY_EXIT_NO_NEXT_TARGET`
- `reentry_count`
  - TPSL 卖出后，下一次原始调仓又买回的次数

### 4.2.4 误杀率与保护效率

建议定义：

- `misfire_count = still_in_target_intervention_count`
- `misfire_rate = misfire_count / tpsl_intervention_count`
- `protected_pnl_sum = Σ protected_pnl`
- `missed_pnl_sum = Σ missed_pnl`
- `protection_efficiency = protected_pnl_sum / (protected_pnl_sum + missed_pnl_sum)`

解释：

- `misfire_rate` 越高，越像是“风控过敏”
- `protection_efficiency` 越高，越说明 TPSL 在这个标的上更像是在保护收益

### 4.2.5 持仓行为差异

- `avg_hold_minutes_actual`
- `avg_hold_minutes_raw`
- `hold_gap_ratio = (avg_hold_minutes_actual - avg_hold_minutes_raw) / avg_hold_minutes_raw`

若：

- `hold_gap_ratio` 很负
- `misfire_rate` 很高
- `delta_bps` 又显著为负

则说明该标的更可能存在“被过早甩出”的问题。

## 4.3 诊断标签与推荐动作

### 4.3.1 诊断标签

建议统一输出以下标签：

- `LOW_SAMPLE`
- `OVER_SENSITIVE`
- `BALANCED`
- `PROTECTIVE`
- `MIXED`

建议判定顺序如下：

1. `LOW_SAMPLE`
   - `priced_lifecycles < 5` 或 `tpsl_intervention_count < 3`
2. `OVER_SENSITIVE`
   - `delta_bps <= -25`
   - 且 `misfire_rate >= 0.5`
3. `PROTECTIVE`
   - `delta_bps >= 15`
   - 且 `protection_efficiency >= 0.6`
   - 且 `misfire_rate <= 0.35`
4. `BALANCED`
   - `abs(delta_bps) < 15`
   - 且 `misfire_rate < 0.5`
5. 其它归为 `MIXED`

阈值并不是最终生产阈值，但足够支撑第一版标的级实验室。

### 4.3.2 推荐动作

建议动作枚举：

- `HOLD`
- `LOOSEN`
- `TIGHTEN`
- `CUSTOM`

对应关系建议为：

- `LOW_SAMPLE -> HOLD`
- `OVER_SENSITIVE -> LOOSEN`
- `PROTECTIVE -> HOLD` 或轻微 `TIGHTEN`
- `BALANCED -> HOLD`
- `MIXED -> CUSTOM`

### 4.3.3 参数偏移量生成

第一版仍然建议用启发式生成，不直接伪装成真实分钟级回放。

定义严重度：

- `severity_score`
  - 由 `delta_bps`、`misfire_rate`、`reentry_count`、`hold_gap_ratio` 组合得到
  - 归一化到 `[0, 1]`

对于 `LOOSEN`：

- `hard_sl_multiplier = 1 + 0.15 * severity_score`
- `break_even_trigger_multiplier = 1 + 0.20 * severity_score`
- `trailing_buffer_multiplier = 1 + 0.25 * severity_score`
- `take_profit_trigger_multiplier = 1 + 0.10 * severity_score`

对于 `TIGHTEN`：

- `hard_sl_multiplier = 1 - 0.08 * severity_score`
- `break_even_trigger_multiplier = 1 - 0.06 * severity_score`
- `trailing_buffer_multiplier = 1 - 0.10 * severity_score`
- `take_profit_trigger_multiplier = 1 - 0.04 * severity_score`

并建议统一做边界裁剪：

- 放宽下限：`1.00`
- 放宽上限：`1.30`
- 收紧下限：`0.85`
- 收紧上限：`1.00`

## 4.4 置信度设计

标的级建议必须带置信度，避免少样本误导。

建议：

- `sample_quality_score`
  - 由 `priced_lifecycles`、`tpsl_intervention_count`、`priced_coverage_ratio` 组合得到
- `confidence_score`
  - 在 `sample_quality_score` 基础上，再乘以时间新鲜度与数据完整度系数

第一版可以使用如下简单规则：

- 样本分：
  - `min(1, priced_lifecycles / 12) * 0.5`
  - `+ min(1, tpsl_intervention_count / 8) * 0.3`
  - `+ priced_coverage_ratio * 0.2`
- 新鲜度修正：
  - 最近 10 个交易日内仍有样本：乘 `1.0`
  - 最近 20 个交易日内有样本：乘 `0.85`
  - 更久以前：乘 `0.7`

最终输出：

- `confidence_score ∈ [0, 1]`

前端展示时建议区间化：

- `>= 0.75`：高置信
- `0.45 ~ 0.75`：中置信
- `< 0.45`：低置信

## 5. 新分析表设计

## 5.1 `insights.fact_symbol_tpsl_diagnostics`

用途：

- 存储某策略某组合某标的在一个分析窗口内的诊断聚合结果

一行的核心语义是：

- “这个标的在这段时间里，TPSL 到底是保护收益，还是误杀趋势”

建议字段分组：

- 维度字段
  - `strategy_name`
  - `portfolio_id`
  - `instrument_id`
  - `date_from`
  - `date_to`
  - `as_of_date`
  - `analysis_run_id`
- 样本字段
  - `total_lifecycles`
  - `priced_lifecycles`
  - `tpsl_intervention_count`
  - `priced_entry_notional`
- 绩效字段
  - `pnl_actual_sum`
  - `pnl_raw_sum`
  - `pnl_delta_sum`
  - `return_actual_bps`
  - `return_raw_bps`
  - `delta_bps`
- 行为字段
  - `misfire_rate`
  - `protection_efficiency`
  - `reentry_count`
  - `avg_hold_minutes_actual`
  - `avg_hold_minutes_raw`
- 结论字段
  - `diagnosis_label`
  - `sample_quality_score`
  - `confidence_score`
  - `diagnostic_payload`

## 5.2 `insights.fact_symbol_tpsl_recommendation`

用途：

- 存储标的级参数建议结果

一行的核心语义是：

- “基于当前诊断，这个标的下一步更适合放宽、收紧还是保持”

建议字段分组：

- 维度字段
  - `strategy_name`
  - `portfolio_id`
  - `instrument_id`
  - `date_from`
  - `date_to`
  - `as_of_date`
  - `recommendation_run_id`
- 方法字段
  - `source_method`
  - `recommended_action`
  - `recommended_profile`
- 参数字段
  - `hard_sl_multiplier`
  - `break_even_trigger_multiplier`
  - `trailing_buffer_multiplier`
  - `take_profit_trigger_multiplier`
- 解释字段
  - `expected_delta_bps`
  - `expected_misfire_rate`
  - `expected_protection_efficiency`
  - `confidence_score`
  - `priority_score`
  - `reason_summary`
  - `recommendation_payload`

## 6. API 与前端演进建议

## 6.1 API

建议保留现有策略级入口：

- `GET /api/strategies/{strategy_name}/parameter-lab`

并新增两个标的级接口：

- `GET /api/strategies/{strategy_name}/parameter-lab/symbols`
- `GET /api/strategies/{strategy_name}/parameter-lab/symbols/{instrument_id}`

列表接口建议支持：

- `portfolio_id`
- `diagnosis_label`
- `recommended_action`
- `only_actionable`
- `sort_by=priority_score|delta_bps|misfire_rate|confidence_score`

所有绩效型接口建议统一返回两类字段：

- 绝对值字段
  - `cum_pnl`
  - `pnl_delta`
  - `protected_pnl_sum`
  - `missed_pnl_sum`
- 标准化字段
  - `proxy_return`
  - `delta_bps`
  - `unit_capital_efficiency`
  - `drawdown_improvement_ratio`

这样前端可以自由决定：

- 总览卡片主打比例、副显金额
- 详情页图表切换金额视图或比例视图
- 参数实验室同时回答“金额影响”和“效率变化”

## 6.2 前端页面

当前参数实验室页面建议升级为三层结构：

1. 顶部仍保留策略级摘要
2. 中间新增“标的级诊断表”
3. 右侧或下方新增“单标的建议详情卡”

标的级表格建议至少展示：

- 标的代码
- 诊断标签
- `delta_bps`
- `pnl_delta_sum`
- 误杀率
- 保护效率
- 建议动作
- 置信度

点开单标的后再展示：

- 建议倍数
- 原因摘要
- 绝对收益影响
- 标准化收益影响
- 干预类型分布
- 生命周期统计
- 近期样本窗口

策略级页面与总览页也建议统一采用：

- 默认看标准化指标
  - 便于跨策略公平比较
- 辅助看绝对金额
  - 便于判断业务体量与真实资金影响
- 图表切换
  - `金额`
  - `收益率 / bps`

## 7. ETL 计算流程建议

建议新增两个批任务，顺序执行：

1. `sync_symbol_tpsl_diagnostics`
   - 从 `fact_position_lifecycle`
   - `fact_tpsl_intervention`
   - `fact_strategy_daily`
   - `fact_strategy_action_raw`
   - 聚合写入 `fact_symbol_tpsl_diagnostics`
2. `sync_symbol_tpsl_recommendations`
   - 从 `fact_symbol_tpsl_diagnostics`
   - 基于启发式规则写入 `fact_symbol_tpsl_recommendation`

建议在 `etl_job_run` 中分别记录：

- 窗口区间
- 策略数
- 标的数
- 可操作建议数
- 低样本标的数

## 8. 对 `treasure-code` 的未来改造方向

本阶段先不改 `treasure-code`，只在 `insights` 侧把建议算出来、展示出来。

后续如果要让建议真正落地到下单链路，建议演进为：

### 8.1 下单参数结构

从当前的“只传 `profile_id`”升级为：

- 默认策略参数
- 标的级覆盖参数

建议抽象为：

```json
{
  "profile_id": "balanced_guard",
  "symbol_overrides": [
    {
      "instrument_id": "600519.SH",
      "hard_sl_multiplier": 1.12,
      "break_even_trigger_multiplier": 1.18,
      "trailing_buffer_multiplier": 1.20,
      "take_profit_trigger_multiplier": 1.06,
      "confidence_score": 0.82,
      "source_method": "symbol_proxy_heuristic_v1"
    }
  ]
}
```

### 8.2 生效优先级

建议优先级：

1. 标的级覆盖
2. 策略默认 profile
3. 系统全局默认值

### 8.3 安全门槛

建议只有在以下条件满足时才允许自动应用：

- `confidence_score >= 0.75`
- 最近窗口仍有足够样本
- 建议未过期
- 建议动作不是 `LOW_SAMPLE`

并且必须保留：

- 回滚开关
- 审计日志
- 实际使用参数快照

## 9. 推荐落地顺序

建议按下面顺序推进，风险最低：

1. 先用现有生命周期数据产出代理标准化指标
2. 落地 `fact_symbol_tpsl_diagnostics`
3. 落地 `fact_symbol_tpsl_recommendation`
4. 扩展参数实验室 API 与前端页面
5. 再考虑 `treasure-code` 的标的级参数覆盖

这样做的好处是：

- 不会阻塞当前已上线的策略级页面
- 先把“看见问题”和“提出建议”做好
- 等建议体系稳定后，再把它接进真实下单执行链路
