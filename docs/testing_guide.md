# 测试前检查清单与测试操作手册

本文档用于指导 `insights` 项目的测试准备、数据同步、服务启动、页面访问与功能验证。

当前文档以 `2026-03-01` 之后的数据为测试口径，原因是：

- MySQL 目标池同步已明确限制为 `2026-03-01` 及之后
- 更早的数据在 PostgreSQL 与 ClickHouse 中没有完整配套事实
- 继续保留更早历史会干扰原始路径与参数实验室的分析结果

## 一、测试前检查清单

建议在正式测试前按下面顺序检查。

### 1. 环境与依赖检查

- 确认项目目录存在：
  `/Users/yinfei/MyProjects/insights`
- 确认 Python 依赖已安装：
  使用 `uv` 管理，不使用 `pip`
- 确认前端依赖已安装：
  `frontend/node_modules` 若不存在，先执行一次 `npm install`

### 2. 数据源检查

- PostgreSQL 可访问：
  `trading_db`
- MySQL 可访问：
  `ww.inode.fun:13306 / CB_HISTORY`
- ClickHouse 可访问：
  `treasure-code-simu:8123 / cnstock`

### 3. 配置检查

测试时建议至少确认这些变量：

- `INSIGHTS_POSTGRES_DSN`
- `INSIGHTS_MYSQL_DSN`
- `INSIGHTS_MYSQL_SCHEMA`
- `INSIGHTS_MYSQL_MIN_TRADE_DATE`
- `INSIGHTS_CLICKHOUSE_HOST`
- `INSIGHTS_CLICKHOUSE_PORT`
- `INSIGHTS_CLICKHOUSE_USER`
- `INSIGHTS_CLICKHOUSE_PASSWORD`
- `INSIGHTS_CLICKHOUSE_DATABASE`
- `INSIGHTS_CLICKHOUSE_SECURE`

当前建议值如下：

```bash
INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db'
INSIGHTS_MYSQL_DSN='mysql://stock:stockshare@ww.inode.fun:13306/CB_HISTORY'
INSIGHTS_MYSQL_SCHEMA='CB_HISTORY'
INSIGHTS_MYSQL_MIN_TRADE_DATE='2026-03-01'
INSIGHTS_CLICKHOUSE_HOST='treasure-code-simu'
INSIGHTS_CLICKHOUSE_PORT='8123'
INSIGHTS_CLICKHOUSE_USER='stock'
INSIGHTS_CLICKHOUSE_PASSWORD='stock4share'
INSIGHTS_CLICKHOUSE_DATABASE='cnstock'
INSIGHTS_CLICKHOUSE_SECURE='false'
```

### 4. PostgreSQL 分析表检查

测试前建议确认 `insights` schema 至少存在这些表：

- `dim_strategy`
- `fact_strategy_target`
- `fact_strategy_action_raw`
- `fact_order_execution`
- `fact_tpsl_intervention`
- `fact_position_lifecycle`
- `fact_strategy_daily`
- `fact_tpsl_counterfactual`
- `fact_symbol_tpsl_diagnostics`
- `fact_symbol_tpsl_recommendation`
- `etl_job_run`

### 5. 旧进程与端口检查

推荐固定端口：

- 后端：`8018`
- 前端：`5173`

若后端启动时报 `Address already in use`，先检查占用端口的进程：

```bash
lsof -nP -iTCP:8018
```

若确认是旧的 `insights` 后端进程，可执行：

```bash
kill <PID>
```

### 6. 数据时间边界检查

本项目当前测试口径要求：

- MySQL 目标池数据仅保留 `2026-03-01` 及之后
- PostgreSQL 中 `fact_strategy_target` 与 `fact_strategy_action_raw` 不应再保留更早日期的数据

## 二、推荐测试启动顺序

建议每次测试前按下面顺序执行。

### 1. 刷新 MySQL 目标池与原始动作

```bash
cd /Users/yinfei/MyProjects/insights

INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
INSIGHTS_MYSQL_DSN='mysql://stock:stockshare@ww.inode.fun:13306/CB_HISTORY' \
INSIGHTS_MYSQL_SCHEMA='CB_HISTORY' \
INSIGHTS_MYSQL_MIN_TRADE_DATE='2026-03-01' \
uv run python -m backend.app.jobs.sync_strategy_data
```

该步骤会：

- 仅同步 `2026-03-01` 及之后的 MySQL 策略表数据
- 清空并重建 PostgreSQL 中对应策略的目标池快照
- 清空并重建 PostgreSQL 中对应策略的原始调仓动作

### 2. 刷新真实执行与 TPSL 干预事实

```bash
cd /Users/yinfei/MyProjects/insights

INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
uv run python -m backend.app.jobs.sync_execution_facts
```

### 3. 刷新生命周期、补价与日度收益

```bash
cd /Users/yinfei/MyProjects/insights

INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
INSIGHTS_CLICKHOUSE_HOST='treasure-code-simu' \
INSIGHTS_CLICKHOUSE_PORT='8123' \
INSIGHTS_CLICKHOUSE_USER='stock' \
INSIGHTS_CLICKHOUSE_PASSWORD='stock4share' \
INSIGHTS_CLICKHOUSE_DATABASE='cnstock' \
INSIGHTS_CLICKHOUSE_SECURE='false' \
uv run python -m backend.app.jobs.sync_performance_facts
```

### 4. 刷新参数实验室代理回放结果

```bash
cd /Users/yinfei/MyProjects/insights

INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
uv run python -m backend.app.jobs.sync_counterfactual_facts
```

### 5. 刷新标的级 TPSL 诊断与建议

```bash
cd /Users/yinfei/MyProjects/insights

INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
INSIGHTS_CLICKHOUSE_HOST='treasure-code-simu' \
INSIGHTS_CLICKHOUSE_PORT='8123' \
INSIGHTS_CLICKHOUSE_USER='stock' \
INSIGHTS_CLICKHOUSE_PASSWORD='stock4share' \
INSIGHTS_CLICKHOUSE_DATABASE='cnstock' \
INSIGHTS_CLICKHOUSE_SECURE='false' \
uv run python -m backend.app.jobs.sync_symbol_tpsl_facts
```

该步骤会：

- 聚合单标的的生命周期、TPSL 干预与回补买入样本
- 对“原始路径仍在持有、实际路径已提前退出”的样本使用 ClickHouse 最新日线做临时盯市补价
- 写入 `fact_symbol_tpsl_diagnostics`
- 基于启发式规则写入 `fact_symbol_tpsl_recommendation`

### 6. 启动后端

```bash
cd /Users/yinfei/MyProjects/insights

INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8018 --reload
```

### 7. 启动前端

```bash
cd /Users/yinfei/MyProjects/insights/frontend

VITE_API_BASE_URL='http://127.0.0.1:8018' \
npm run dev -- --host 127.0.0.1 --port 5173
```

## 三、测试访问地址

### 1. 总览首页

[http://127.0.0.1:5173/#/](http://127.0.0.1:5173/#/)

### 2. 策略详情页示例

[http://127.0.0.1:5173/#/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu](http://127.0.0.1:5173/#/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu)

### 3. 参数实验室示例

[http://127.0.0.1:5173/#/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51/lab?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu](http://127.0.0.1:5173/#/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51/lab?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu)

### 4. 常用后端接口

- 概览接口：
  [http://127.0.0.1:8018/api/overview/strategies](http://127.0.0.1:8018/api/overview/strategies)
- 日度收益接口：
  [http://127.0.0.1:8018/api/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51/daily?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu](http://127.0.0.1:8018/api/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51/daily?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu)
- 参数实验室接口：
  [http://127.0.0.1:8018/api/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51/parameter-lab?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu](http://127.0.0.1:8018/api/strategies/%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51/parameter-lab?portfolio_id=portfolio_%E6%8A%95%E9%A1%BE%E7%AD%96%E7%95%A51_simu)

## 四、测试操作手册

建议按以下顺序测试，效率最高。

### 第一步：检查总览页是否正常加载

打开总览页：

[http://127.0.0.1:5173/#/](http://127.0.0.1:5173/#/)

重点观察：

- 页面是否能正常加载出策略矩阵
- 是否能看到策略实例数、实际收益效率、原始收益效率、TPSL 标准化净影响
- 顶部卡片主值是否为 `bps`，副信息是否仍保留金额口径
- 是否能看到“效率领先策略 / TPSL 标准化正贡献最强 / TPSL 标准化负贡献最明显”三张聚焦卡片

### 第二步：测试总览页筛选与排序

在总览页中操作：

- 输入策略名搜索，例如：`投顾策略1`
- 切换模式筛选：
  `全部模式 / 仅 SIMU / 仅 LIVE`
- 切换 TPSL 影响方向：
  `全部方向 / 净正贡献 / 净负贡献 / 中性`
- 切换排序方式：
  `按实际收益效率 / 按实际累计收益 / 按原始累计收益 / 按 TPSL 净影响(bps) / 按最新交易日`

预期结果：

- 列表数量变化正确
- 排序优先使用标准化指标时，卡片顺序应发生合理变化
- 卡片点击后能跳到正确的策略详情页

### 第三步：测试策略详情页

推荐优先测试：

- `投顾策略1`
- `投顾策略`
- `大爷微辣`

在详情页重点核对以下模块：

- 顶部结论文案是否符合最近一个交易日的实际表现
- `累计已实现收益对比` 是否能看到实际路径与原始路径两条曲线
- `TPSL 日度净影响` 是否能看到正负变化
- `标准化绩效` 卡片区是否能看到实际收益效率、原始收益效率、TPSL 单位资金净影响、交易成本拖累
- `标准化绩效` 的主值是否为 `bps`，辅助文案中是否仍保留金额与覆盖率信息
- `TPSL 归因摘要` 中正贡献、负贡献、待补价干预数量是否合理
- `路径覆盖` 中原始路径已补价数量是否合理
- `原始调仓摘要` 中买入、卖出、继续持有数量是否与最新调仓动作一致
- `最新目标池` 和 `最新原始动作` 是否能正确展示
- `TPSL 干预明细` 与 `持仓生命周期` 是否能正常渲染表格

### 第四步：重点验证 TPSL 是否“过于敏感”

在策略详情页中重点关注这些信号：

- `负贡献干预` 是否显著多于 `正贡献干预`
- `仍在目标池内被卖出` 的情况是否很多
- `持仓生命周期` 中 `pnl_delta` 是否大量为负
- 某些仓位是否在 TPSL 卖出后又被后续原始调仓重新买回
- `TPSL 单位资金净影响` 是否显著为负，且与生命周期明细的直觉一致

如果这些现象明显，说明：

- 当前 TPSL 参数更可能偏敏感
- 参数实验室中的放宽档位更值得优先测试

### 第五步：测试参数实验室

进入参数实验室页面后，重点看：

- 是否能看到 `敏感度信号`
- 是否能看到 `TPSL 单位资金净影响`
- 是否能看到 `实际相对原始金额差`
- 是否能看到 `仍在目标池内的干预占比`
- 是否能看到 `原始路径补价覆盖率`
- 是否能看到 `实际收益效率` 与 `原始收益效率`

然后继续核对“方案对比”区块：

- 是否包含 `当前实际执行`
- 是否包含 `原始未干预基线`
- 是否包含 `balanced_guard`
- 是否包含 `loose_guard`
- 是否包含 `tight_guard`

若只看到两条默认场景，说明：

- `sync_counterfactual_facts` 未执行成功
- 或参数实验室数据尚未写入 `fact_tpsl_counterfactual`

### 第六步：重点观察参数实验室的结论是否符合直觉

建议优先观察：

- `loose_guard` 是否比 `current_live` 更适合趋势仓位
- `tight_guard` 是否更能压缩回撤，但可能降低收益
- `balanced_guard` 是否更接近你对“现网参数微调版”的预期
- 顶部双轨指标是否一致表达同一结论：
  - `bps` 口径回答“单位资金效率变化”
  - 金额口径回答“真实赚亏差额”

对于当前样本，建议重点关注这些判断：

- `投顾策略1`
  更适合验证“放宽后是否能减少提前打断趋势”
- `投顾策略`
  更适合验证“收紧后是否还能提升保护效果”
- `大爷微辣`
  当前样本整体偏弱，适合先观察信号，不宜过度解读档位差异

### 第七步：接口与页面联调排查

如果页面异常，可以按这个顺序排查：

1. 打开后端接口，确认 JSON 是否正常返回
2. 检查后端控制台是否有异常堆栈
3. 检查前端浏览器控制台是否有请求错误
4. 检查后端端口和前端 `VITE_API_BASE_URL` 是否一致

## 五、建议的测试记录方式

建议测试时按“页面 + 现象 + 预期 + 结论”记录。

推荐记录模板：

```text
测试时间：
测试策略：
测试页面：
操作步骤：
实际结果：
预期结果：
是否通过：
备注：
```

## 六、常见问题排查

### 1. `sync_strategy_data` 报 `缺少 INSIGHTS_MYSQL_DSN`

原因：

- 没有传入 `INSIGHTS_MYSQL_DSN`

解决：

```bash
INSIGHTS_MYSQL_DSN='mysql://stock:stockshare@ww.inode.fun:13306/CB_HISTORY'
```

### 2. 后端启动时报 `Address already in use`

原因：

- `8018` 端口已经被旧服务占用

解决：

```bash
lsof -nP -iTCP:8018
kill <PID>
```

### 3. 参数实验室只有两条场景

原因：

- `sync_counterfactual_facts` 没跑
- 或任务跑失败

解决：

```bash
cd /Users/yinfei/MyProjects/insights
INSIGHTS_POSTGRES_DSN='postgresql://trader:pg4trade@treasure-code-simu:15432/trading_db' \
uv run python -m backend.app.jobs.sync_counterfactual_facts
```

### 4. 明细页中 `raw` 相关字段为空

原因：

- ClickHouse 未配置
- 或原始路径尚未形成可补价时点

解决：

- 检查 ClickHouse 环境变量
- 重新执行 `sync_performance_facts`

### 5. 总览页或详情页数据看起来过旧

原因：

- 还没重跑同步任务
- 或前端连到了旧的后端进程

解决：

- 重新执行四个同步任务
- 重新确认后端端口

## 七、当前测试结论边界

测试时请注意当前系统仍有这些边界：

- 参数实验室目前是“代理回放首版”，不是完整分钟级历史回放
- `fact_tpsl_counterfactual` 中的结果更适合作为方向性比较
- 标准化绩效指标第一阶段已经落地：
  - 总览页、策略详情页、参数实验室均已支持“主看 `bps`、辅看金额”的双轨展示
  - 后端接口已返回 `proxy_return_* / proxy_delta_bps / fee_drag_bps / priced_coverage_ratio` 等代理标准化字段
- `nav_* / return_* / drawdown_*` 仍未接入完整净值回放
- 部分 `raw` 路径仍会因为缺少后续卖点或行情而保持不完整

因此当前测试重点应放在：

- 页面是否稳定
- 数据链路是否打通
- 代理标准化指标与金额口径是否同时合理
- 方向性分析是否符合交易直觉
- 哪些地方需要下一轮细调
