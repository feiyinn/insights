-- 用途：初始化 insights 分析 schema 及首批分析表。
-- 参数：无。
-- 返回值：创建 schema、表、索引与注释。
-- 异常/边界：脚本按幂等方式编写，可重复执行；仅依赖 PostgreSQL 标准能力。

BEGIN;

CREATE SCHEMA IF NOT EXISTS insights;

COMMENT ON SCHEMA insights IS '交易分析项目 insights 的专用分析 schema';

-- 用途：维护策略与组合之间的映射关系，作为分析维表。
-- 参数：strategy_name/portfolio_id 等策略标识信息。
-- 返回值：每行表示一个可分析策略实例。
-- 异常/边界：同一 strategy_name + portfolio_id 仅保留一条记录。
CREATE TABLE IF NOT EXISTS insights.dim_strategy (
    strategy_key BIGSERIAL PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    tactic_id TEXT,
    mode TEXT NOT NULL DEFAULT 'UNKNOWN',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    source_system TEXT NOT NULL DEFAULT 'trading',
    source_schema TEXT,
    source_table TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dim_strategy UNIQUE (strategy_name, portfolio_id),
    CONSTRAINT chk_dim_strategy_mode CHECK (mode IN ('SIMU', 'LIVE', 'UNKNOWN'))
);

COMMENT ON TABLE insights.dim_strategy IS '策略维表：维护策略名、组合、账户和 tactic 的映射';
COMMENT ON COLUMN insights.dim_strategy.strategy_name IS '策略名称，对齐 MySQL 策略表名与 PostgreSQL strategy_portfolio.strategy_name';
COMMENT ON COLUMN insights.dim_strategy.portfolio_id IS '分析目标组合 ID';
COMMENT ON COLUMN insights.dim_strategy.account_id IS '账户 ID，可为空';
COMMENT ON COLUMN insights.dim_strategy.tactic_id IS '策略 tactic/profile 标识';
COMMENT ON COLUMN insights.dim_strategy.mode IS '运行模式：SIMU/LIVE/UNKNOWN';
COMMENT ON COLUMN insights.dim_strategy.enabled IS '是否启用';
COMMENT ON COLUMN insights.dim_strategy.metadata IS '额外扩展信息';

CREATE INDEX IF NOT EXISTS idx_dim_strategy_portfolio
    ON insights.dim_strategy (portfolio_id);

-- 用途：记录原始每日调仓目标池快照。
-- 参数：trade_date、strategy_name、batch_time_tag、instrument_id 等目标池字段。
-- 返回值：每行表示某日某批次下一个目标标的。
-- 异常/边界：同一策略、同一批次、同一标的仅允许一条记录。
CREATE TABLE IF NOT EXISTS insights.fact_strategy_target (
    target_id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT,
    batch_time_tag TIMESTAMPTZ NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_name TEXT,
    rank_no INTEGER,
    is_latest_batch BOOLEAN NOT NULL DEFAULT TRUE,
    source_system TEXT NOT NULL DEFAULT 'mysql',
    source_schema TEXT NOT NULL,
    source_table TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_strategy_target UNIQUE (strategy_name, trade_date, batch_time_tag, instrument_id)
);

COMMENT ON TABLE insights.fact_strategy_target IS '原始策略目标池快照事实表';
COMMENT ON COLUMN insights.fact_strategy_target.trade_date IS '目标池对应的交易日';
COMMENT ON COLUMN insights.fact_strategy_target.batch_time_tag IS '该批策略列表生成时间';
COMMENT ON COLUMN insights.fact_strategy_target.rank_no IS '策略原始排序名次';
COMMENT ON COLUMN insights.fact_strategy_target.is_latest_batch IS '是否为该交易日当前最新批次';

CREATE INDEX IF NOT EXISTS idx_fact_strategy_target_query
    ON insights.fact_strategy_target (strategy_name, trade_date, batch_time_tag DESC);

CREATE INDEX IF NOT EXISTS idx_fact_strategy_target_instrument
    ON insights.fact_strategy_target (instrument_id, trade_date);

-- 用途：保存未受 TPSL 干预时的原始调仓动作。
-- 参数：trade_date、strategy_name、instrument_id、action_type 等动作字段。
-- 返回值：每行表示一条原始策略动作记录。
-- 异常/边界：同一策略、同一日、同一批次、同一标的、同一动作仅保留一条。
CREATE TABLE IF NOT EXISTS insights.fact_strategy_action_raw (
    action_id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT,
    batch_time_tag TIMESTAMPTZ NOT NULL,
    instrument_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    reason_type TEXT NOT NULL DEFAULT 'UNKNOWN',
    before_in_target BOOLEAN,
    after_in_target BOOLEAN,
    before_rank_no INTEGER,
    after_rank_no INTEGER,
    raw_holding_qty BIGINT,
    planned_qty BIGINT,
    planned_weight NUMERIC(18, 8),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_strategy_action_raw UNIQUE (strategy_name, trade_date, batch_time_tag, instrument_id, action_type),
    CONSTRAINT chk_fact_strategy_action_raw_action CHECK (action_type IN ('BUY', 'SELL', 'HOLD')),
    CONSTRAINT chk_fact_strategy_action_raw_reason CHECK (
        reason_type IN (
            'NEW_ENTRY',
            'REMOVE_FROM_TARGET',
            'CONTINUE_HOLD',
            'REENTRY_AFTER_TPSL',
            'UNKNOWN'
        )
    )
);

COMMENT ON TABLE insights.fact_strategy_action_raw IS '原始策略动作事实表：仅反映目标池与原始持仓差异，不包含 TPSL 干预动作';
COMMENT ON COLUMN insights.fact_strategy_action_raw.raw_holding_qty IS '未受 TPSL 干预时，应视为仍持有的原始仓位数量';
COMMENT ON COLUMN insights.fact_strategy_action_raw.reason_type IS '动作原因分类';

CREATE INDEX IF NOT EXISTS idx_fact_strategy_action_raw_query
    ON insights.fact_strategy_action_raw (strategy_name, trade_date, batch_time_tag DESC, action_type);

CREATE INDEX IF NOT EXISTS idx_fact_strategy_action_raw_instrument
    ON insights.fact_strategy_action_raw (instrument_id, trade_date);

-- 用途：统一存储真实订单与成交事实，作为后续归因与收益分析基础。
-- 参数：订单标识、成交标识、来源类型、价格数量等执行字段。
-- 返回值：每行表示一次订单执行事实。
-- 异常/边界：同一 order_id + exec_id 仅允许一条；当 exec_id 为空时由上层保证不重复写入。
CREATE TABLE IF NOT EXISTS insights.fact_order_execution (
    execution_id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    exec_id TEXT,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    strategy_name TEXT,
    instrument_id TEXT NOT NULL,
    trade_ts TIMESTAMPTZ,
    order_created_at TIMESTAMPTZ,
    order_updated_at TIMESTAMPTZ,
    side TEXT NOT NULL,
    qty BIGINT NOT NULL,
    filled_qty BIGINT,
    order_price NUMERIC(18, 6),
    avg_price NUMERIC(18, 6),
    fee NUMERIC(18, 6) NOT NULL DEFAULT 0,
    tax NUMERIC(18, 6) NOT NULL DEFAULT 0,
    source_type TEXT NOT NULL,
    tactic_id TEXT,
    client_order_id TEXT,
    parent_intent_id UUID,
    level_type TEXT,
    level_index INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_order_execution UNIQUE (order_id, exec_id),
    CONSTRAINT chk_fact_order_execution_side CHECK (side IN ('BUY', 'SELL', 'SHORT', 'COVER')),
    CONSTRAINT chk_fact_order_execution_source CHECK (source_type IN ('STRAT', 'TPSL', 'OTHER'))
);

COMMENT ON TABLE insights.fact_order_execution IS '统一订单执行事实表：融合 STRAT 与 TPSL 的真实订单/成交';
COMMENT ON COLUMN insights.fact_order_execution.source_type IS '执行来源：STRAT/TPSL/OTHER';
COMMENT ON COLUMN insights.fact_order_execution.parent_intent_id IS '若为 TPSL 执行，则记录对应 intent_id';

CREATE INDEX IF NOT EXISTS idx_fact_order_execution_portfolio_ts
    ON insights.fact_order_execution (portfolio_id, trade_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_order_execution_strategy_ts
    ON insights.fact_order_execution (strategy_name, trade_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_order_execution_source
    ON insights.fact_order_execution (source_type, trade_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_order_execution_instrument
    ON insights.fact_order_execution (instrument_id, trade_ts DESC);

-- 用途：记录 TPSL 干预事件及其与下一次调仓目标池的关系。
-- 参数：intent_id、level_type、trigger_ts、next_target_still_holding 等字段。
-- 返回值：每行表示一次 TPSL 触发干预。
-- 异常/边界：一个 intent_id 仅对应一条干预记录。
CREATE TABLE IF NOT EXISTS insights.fact_tpsl_intervention (
    intervention_id BIGSERIAL PRIMARY KEY,
    intent_id UUID NOT NULL,
    parent_order_id TEXT,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    strategy_name TEXT,
    instrument_id TEXT NOT NULL,
    position_state_id UUID,
    tactic_id TEXT,
    level_type TEXT NOT NULL,
    level_index INTEGER NOT NULL DEFAULT 0,
    trigger_ts TIMESTAMPTZ,
    fill_ts TIMESTAMPTZ,
    filled_qty BIGINT,
    fill_price NUMERIC(18, 6),
    status TEXT,
    trigger_reason TEXT,
    next_rebalance_trade_date DATE,
    next_batch_time_tag TIMESTAMPTZ,
    next_target_still_holding BOOLEAN,
    classification TEXT NOT NULL DEFAULT 'UNKNOWN',
    protected_pnl NUMERIC(18, 6),
    missed_pnl NUMERIC(18, 6),
    net_pnl_delta NUMERIC(18, 6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_tpsl_intervention UNIQUE (intent_id),
    CONSTRAINT chk_fact_tpsl_intervention_level CHECK (level_type IN ('TP', 'SL', 'BE', 'TSL')),
    CONSTRAINT chk_fact_tpsl_intervention_classification CHECK (
        classification IN (
            'PRE_REBALANCE_EXIT_STILL_IN_TARGET',
            'PRE_REBALANCE_EXIT_REMOVED_FROM_TARGET',
            'INTRADAY_EXIT_NO_NEXT_TARGET',
            'UNKNOWN'
        )
    )
);

COMMENT ON TABLE insights.fact_tpsl_intervention IS 'TPSL 干预事实表：记录风控退出与原始目标池的关系';
COMMENT ON COLUMN insights.fact_tpsl_intervention.next_target_still_holding IS '下一次原始目标池中，该标的是否仍应继续持有';
COMMENT ON COLUMN insights.fact_tpsl_intervention.protected_pnl IS '估算的保护收益';
COMMENT ON COLUMN insights.fact_tpsl_intervention.missed_pnl IS '估算的错失收益';
COMMENT ON COLUMN insights.fact_tpsl_intervention.net_pnl_delta IS '干预净影响：保护收益减去错失收益';

CREATE INDEX IF NOT EXISTS idx_fact_tpsl_intervention_strategy_ts
    ON insights.fact_tpsl_intervention (strategy_name, trigger_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_tpsl_intervention_level
    ON insights.fact_tpsl_intervention (level_type, trigger_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_tpsl_intervention_instrument
    ON insights.fact_tpsl_intervention (instrument_id, trigger_ts DESC);

-- 用途：重建单次持仓从开仓到实际/原始退出的完整生命周期。
-- 参数：entry_*、exit_*、pnl_*、tpsl_intervened 等字段。
-- 返回值：每行表示一条持仓生命周期。
-- 异常/边界：原始退出可为空，表示仍待估值或仍处于持有状态。
CREATE TABLE IF NOT EXISTS insights.fact_position_lifecycle (
    lifecycle_id BIGSERIAL PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    strategy_name TEXT,
    instrument_id TEXT NOT NULL,
    tactic_id TEXT,
    entry_order_id TEXT,
    entry_exec_id TEXT,
    entry_ts TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(18, 6) NOT NULL,
    entry_qty BIGINT NOT NULL,
    exit_ts_actual TIMESTAMPTZ,
    exit_price_actual NUMERIC(18, 6),
    exit_qty_actual BIGINT,
    exit_reason_actual TEXT,
    exit_order_id_actual TEXT,
    exit_intent_id_actual UUID,
    exit_ts_raw TIMESTAMPTZ,
    exit_price_raw NUMERIC(18, 6),
    exit_qty_raw BIGINT,
    exit_reason_raw TEXT,
    holding_minutes_actual NUMERIC(18, 2),
    holding_minutes_raw NUMERIC(18, 2),
    pnl_actual NUMERIC(18, 6),
    pnl_raw NUMERIC(18, 6),
    pnl_delta NUMERIC(18, 6),
    max_favorable_excursion NUMERIC(18, 6),
    max_adverse_excursion NUMERIC(18, 6),
    tpsl_intervened BOOLEAN NOT NULL DEFAULT FALSE,
    raw_path_status TEXT NOT NULL DEFAULT 'OPEN',
    actual_path_status TEXT NOT NULL DEFAULT 'OPEN',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_position_lifecycle UNIQUE (portfolio_id, instrument_id, entry_ts, entry_order_id),
    CONSTRAINT chk_fact_position_lifecycle_raw_status CHECK (raw_path_status IN ('OPEN', 'CLOSED', 'ESTIMATED')),
    CONSTRAINT chk_fact_position_lifecycle_actual_status CHECK (actual_path_status IN ('OPEN', 'CLOSED'))
);

COMMENT ON TABLE insights.fact_position_lifecycle IS '持仓生命周期事实表：用于对比原始路径与实际路径';
COMMENT ON COLUMN insights.fact_position_lifecycle.pnl_delta IS 'TPSL 及其它执行偏差对单次持仓收益造成的变化';
COMMENT ON COLUMN insights.fact_position_lifecycle.tpsl_intervened IS '该生命周期是否受过 TPSL 干预';
COMMENT ON COLUMN insights.fact_position_lifecycle.raw_path_status IS '原始未干预路径的状态：OPEN/CLOSED/ESTIMATED';

CREATE INDEX IF NOT EXISTS idx_fact_position_lifecycle_strategy_entry
    ON insights.fact_position_lifecycle (strategy_name, entry_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_position_lifecycle_instrument_entry
    ON insights.fact_position_lifecycle (instrument_id, entry_ts DESC);

CREATE INDEX IF NOT EXISTS idx_fact_position_lifecycle_tpsl
    ON insights.fact_position_lifecycle (tpsl_intervened, entry_ts DESC);

-- 用途：记录策略日度收益、回撤和 TPSL 净影响。
-- 参数：trade_date、nav_actual、nav_raw、tpsl_net_delta 等日度指标。
-- 返回值：每行表示某策略某组合在某交易日的聚合分析结果。
-- 异常/边界：同一 strategy_name + portfolio_id + trade_date 仅保留一条。
CREATE TABLE IF NOT EXISTS insights.fact_strategy_daily (
    strategy_daily_id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    nav_actual NUMERIC(18, 6),
    nav_raw NUMERIC(18, 6),
    daily_return_actual NUMERIC(18, 8),
    daily_return_raw NUMERIC(18, 8),
    cum_return_actual NUMERIC(18, 8),
    cum_return_raw NUMERIC(18, 8),
    drawdown_actual NUMERIC(18, 8),
    drawdown_raw NUMERIC(18, 8),
    turnover_actual NUMERIC(18, 8),
    turnover_raw NUMERIC(18, 8),
    tpsl_exit_count INTEGER NOT NULL DEFAULT 0,
    tpsl_reentry_count INTEGER NOT NULL DEFAULT 0,
    tpsl_positive_delta NUMERIC(18, 6) NOT NULL DEFAULT 0,
    tpsl_negative_delta NUMERIC(18, 6) NOT NULL DEFAULT 0,
    tpsl_net_delta NUMERIC(18, 6) NOT NULL DEFAULT 0,
    fee_total NUMERIC(18, 6) NOT NULL DEFAULT 0,
    tax_total NUMERIC(18, 6) NOT NULL DEFAULT 0,
    notes JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_strategy_daily UNIQUE (strategy_name, portfolio_id, trade_date)
);

COMMENT ON TABLE insights.fact_strategy_daily IS '策略日度分析事实表：对比原始收益、实际收益和 TPSL 影响';
COMMENT ON COLUMN insights.fact_strategy_daily.nav_actual IS '实际执行路径下的净值';
COMMENT ON COLUMN insights.fact_strategy_daily.nav_raw IS '原始未干预路径下的净值';
COMMENT ON COLUMN insights.fact_strategy_daily.tpsl_reentry_count IS '日内因 TPSL 卖出后又被原始调仓重新买回的次数';

CREATE INDEX IF NOT EXISTS idx_fact_strategy_daily_strategy_date
    ON insights.fact_strategy_daily (strategy_name, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_fact_strategy_daily_portfolio_date
    ON insights.fact_strategy_daily (portfolio_id, trade_date DESC);

-- 用途：保存参数实验与反事实回放结果。
-- 参数：experiment_id、param_profile、收益和回撤等实验结果。
-- 返回值：每行表示一组参数在一个策略区间上的实验结果。
-- 异常/边界：同一 experiment_id + 策略 + 参数档位仅保留一条。
CREATE TABLE IF NOT EXISTS insights.fact_tpsl_counterfactual (
    experiment_result_id BIGSERIAL PRIMARY KEY,
    experiment_id UUID NOT NULL,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT,
    tactic_id TEXT,
    param_profile TEXT NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    cum_return NUMERIC(18, 8),
    max_drawdown NUMERIC(18, 8),
    sharpe NUMERIC(18, 8),
    win_rate NUMERIC(18, 8),
    trade_count INTEGER,
    tpsl_trigger_count INTEGER,
    avg_hold_minutes NUMERIC(18, 2),
    net_delta_vs_baseline NUMERIC(18, 6),
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_tpsl_counterfactual UNIQUE (experiment_id, strategy_name, portfolio_id, param_profile)
);

COMMENT ON TABLE insights.fact_tpsl_counterfactual IS 'TPSL 参数回放与反事实实验结果表';
COMMENT ON COLUMN insights.fact_tpsl_counterfactual.param_profile IS '参数档位名称，例如 baseline/loose/tight';
COMMENT ON COLUMN insights.fact_tpsl_counterfactual.net_delta_vs_baseline IS '相对于基线方案的净收益变化';

CREATE INDEX IF NOT EXISTS idx_fact_tpsl_counterfactual_strategy
    ON insights.fact_tpsl_counterfactual (strategy_name, date_from, date_to);

CREATE INDEX IF NOT EXISTS idx_fact_tpsl_counterfactual_experiment
    ON insights.fact_tpsl_counterfactual (experiment_id);

-- 用途：记录分析同步与批处理任务的运行状态，便于排查与重跑。
-- 参数：job_name、source_system、status、行数统计等。
-- 返回值：每行表示一次 ETL / 分析任务运行。
-- 异常/边界：允许同名任务多次运行，通过 run_id 区分。
CREATE TABLE IF NOT EXISTS insights.etl_job_run (
    run_id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    source_system TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    rows_written INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_etl_job_run_source CHECK (source_system IN ('MYSQL', 'POSTGRES', 'CLICKHOUSE', 'SYSTEM')),
    CONSTRAINT chk_etl_job_run_status CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED'))
);

COMMENT ON TABLE insights.etl_job_run IS '分析任务运行记录表';
COMMENT ON COLUMN insights.etl_job_run.rows_written IS '本次运行新增写入记录数';
COMMENT ON COLUMN insights.etl_job_run.rows_updated IS '本次运行更新记录数';

CREATE INDEX IF NOT EXISTS idx_etl_job_run_job_started
    ON insights.etl_job_run (job_name, started_at DESC);

COMMIT;
