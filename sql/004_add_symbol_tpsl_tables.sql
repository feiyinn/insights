-- 用途：新增标的级 TPSL 诊断表与建议表，支撑参数实验室从策略级下钻到标的级。
-- 参数：analysis_run_id、recommendation_run_id、strategy_name、portfolio_id、instrument_id 等维度字段。
-- 返回值：创建两张新的 insights 分析事实表及配套索引。
-- 异常/边界：本脚本只定义表结构，不包含回填逻辑；建议先由 ETL 任务分批写入。

CREATE TABLE IF NOT EXISTS insights.fact_symbol_tpsl_diagnostics (
    symbol_diagnostic_id BIGSERIAL PRIMARY KEY,
    analysis_run_id UUID NOT NULL,
    as_of_date DATE NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    tactic_id TEXT,
    instrument_id TEXT NOT NULL,
    total_lifecycles INTEGER NOT NULL DEFAULT 0,
    closed_lifecycles INTEGER NOT NULL DEFAULT 0,
    priced_lifecycles INTEGER NOT NULL DEFAULT 0,
    priced_coverage_ratio NUMERIC(18, 8),
    priced_entry_notional NUMERIC(20, 6) NOT NULL DEFAULT 0,
    pnl_actual_sum NUMERIC(18, 6),
    pnl_raw_sum NUMERIC(18, 6),
    pnl_delta_sum NUMERIC(18, 6),
    return_actual_bps NUMERIC(18, 6),
    return_raw_bps NUMERIC(18, 6),
    delta_bps NUMERIC(18, 6),
    tpsl_intervention_count INTEGER NOT NULL DEFAULT 0,
    positive_intervention_count INTEGER NOT NULL DEFAULT 0,
    negative_intervention_count INTEGER NOT NULL DEFAULT 0,
    still_in_target_intervention_count INTEGER NOT NULL DEFAULT 0,
    removed_from_target_intervention_count INTEGER NOT NULL DEFAULT 0,
    no_next_target_intervention_count INTEGER NOT NULL DEFAULT 0,
    reentry_count INTEGER NOT NULL DEFAULT 0,
    misfire_count INTEGER NOT NULL DEFAULT 0,
    misfire_rate NUMERIC(18, 8),
    protected_pnl_sum NUMERIC(18, 6),
    missed_pnl_sum NUMERIC(18, 6),
    protection_efficiency NUMERIC(18, 8),
    avg_hold_minutes_actual NUMERIC(18, 2),
    avg_hold_minutes_raw NUMERIC(18, 2),
    hold_gap_ratio NUMERIC(18, 8),
    sample_quality_score NUMERIC(18, 8),
    confidence_score NUMERIC(18, 8),
    diagnosis_label TEXT NOT NULL DEFAULT 'LOW_SAMPLE',
    diagnostic_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_symbol_tpsl_diagnostics UNIQUE (
        analysis_run_id,
        strategy_name,
        portfolio_id,
        instrument_id
    ),
    CONSTRAINT chk_fact_symbol_tpsl_diagnostics_label CHECK (
        diagnosis_label IN (
            'LOW_SAMPLE',
            'OVER_SENSITIVE',
            'BALANCED',
            'PROTECTIVE',
            'MIXED'
        )
    )
);

COMMENT ON TABLE insights.fact_symbol_tpsl_diagnostics IS '标的级 TPSL 诊断事实表：沉淀单标的收益影响、误杀率、保护效率与诊断标签';
COMMENT ON COLUMN insights.fact_symbol_tpsl_diagnostics.analysis_run_id IS '一次标的级诊断批任务的运行标识';
COMMENT ON COLUMN insights.fact_symbol_tpsl_diagnostics.priced_entry_notional IS '已完成补价生命周期的名义本金之和，作为代理标准化分母';
COMMENT ON COLUMN insights.fact_symbol_tpsl_diagnostics.delta_bps IS 'TPSL 对该标的净影响的代理 bps：10000 * pnl_delta_sum / priced_entry_notional';
COMMENT ON COLUMN insights.fact_symbol_tpsl_diagnostics.misfire_rate IS '误杀率：仍在下一次目标池中却被 TPSL 提前卖出的占比';
COMMENT ON COLUMN insights.fact_symbol_tpsl_diagnostics.protection_efficiency IS '保护效率：protected_pnl_sum / (protected_pnl_sum + missed_pnl_sum)';
COMMENT ON COLUMN insights.fact_symbol_tpsl_diagnostics.diagnosis_label IS '诊断标签：LOW_SAMPLE / OVER_SENSITIVE / BALANCED / PROTECTIVE / MIXED';

CREATE INDEX IF NOT EXISTS idx_fact_symbol_tpsl_diag_strategy_date
    ON insights.fact_symbol_tpsl_diagnostics (strategy_name, portfolio_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_fact_symbol_tpsl_diag_instrument_date
    ON insights.fact_symbol_tpsl_diagnostics (instrument_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_fact_symbol_tpsl_diag_label
    ON insights.fact_symbol_tpsl_diagnostics (diagnosis_label, confidence_score DESC);

CREATE TABLE IF NOT EXISTS insights.fact_symbol_tpsl_recommendation (
    symbol_recommendation_id BIGSERIAL PRIMARY KEY,
    recommendation_run_id UUID NOT NULL,
    as_of_date DATE NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    account_id TEXT,
    tactic_id TEXT,
    instrument_id TEXT NOT NULL,
    source_method TEXT NOT NULL,
    based_on_analysis_run_id UUID,
    recommended_action TEXT NOT NULL DEFAULT 'HOLD',
    recommended_profile TEXT,
    hard_sl_multiplier NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    break_even_trigger_multiplier NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    trailing_buffer_multiplier NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    take_profit_trigger_multiplier NUMERIC(18, 6) NOT NULL DEFAULT 1.0,
    expected_delta_bps NUMERIC(18, 6),
    expected_misfire_rate NUMERIC(18, 8),
    expected_protection_efficiency NUMERIC(18, 8),
    confidence_score NUMERIC(18, 8),
    priority_score NUMERIC(18, 8),
    reason_summary TEXT,
    recommendation_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fact_symbol_tpsl_recommendation UNIQUE (
        recommendation_run_id,
        strategy_name,
        portfolio_id,
        instrument_id
    ),
    CONSTRAINT chk_fact_symbol_tpsl_recommendation_action CHECK (
        recommended_action IN (
            'HOLD',
            'LOOSEN',
            'TIGHTEN',
            'CUSTOM'
        )
    )
);

COMMENT ON TABLE insights.fact_symbol_tpsl_recommendation IS '标的级 TPSL 建议事实表：沉淀单标的建议动作、建议倍数、置信度与解释信息';
COMMENT ON COLUMN insights.fact_symbol_tpsl_recommendation.recommendation_run_id IS '一次标的级建议批任务的运行标识';
COMMENT ON COLUMN insights.fact_symbol_tpsl_recommendation.source_method IS '建议生成方法，例如 symbol_proxy_heuristic_v1';
COMMENT ON COLUMN insights.fact_symbol_tpsl_recommendation.based_on_analysis_run_id IS '本次建议所依赖的诊断批次标识';
COMMENT ON COLUMN insights.fact_symbol_tpsl_recommendation.recommended_action IS '建议动作：HOLD / LOOSEN / TIGHTEN / CUSTOM';
COMMENT ON COLUMN insights.fact_symbol_tpsl_recommendation.priority_score IS '建议优先级分数，用于前端排序与下游筛选';

CREATE INDEX IF NOT EXISTS idx_fact_symbol_tpsl_rec_strategy_date
    ON insights.fact_symbol_tpsl_recommendation (strategy_name, portfolio_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_fact_symbol_tpsl_rec_instrument_date
    ON insights.fact_symbol_tpsl_recommendation (instrument_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_fact_symbol_tpsl_rec_action_priority
    ON insights.fact_symbol_tpsl_recommendation (recommended_action, priority_score DESC, confidence_score DESC);
