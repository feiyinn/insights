-- 用途：将现有交易系统中的策略、组合、账户和 tactic 信息引导到 insights.dim_strategy。
-- 参数：无。
-- 返回值：向 insights.dim_strategy 执行幂等 upsert。
-- 异常/边界：若某组合暂无账户或 tactic 信息，则相应字段允许为空。

INSERT INTO insights.dim_strategy (
    strategy_name,
    portfolio_id,
    account_id,
    tactic_id,
    mode,
    enabled,
    source_system,
    source_schema,
    source_table,
    metadata,
    created_at,
    updated_at
)
SELECT
    sp.strategy_name,
    sp.portfolio_id,
    pfa.account_id,
    ps.tactic_id,
    CASE
        WHEN sp.portfolio_id LIKE '%_simu' THEN 'SIMU'
        WHEN sp.portfolio_id LIKE '%_live' THEN 'LIVE'
        ELSE 'UNKNOWN'
    END AS mode,
    COALESCE(sp.enabled, TRUE) AS enabled,
    'trading' AS source_system,
    'trading' AS source_schema,
    'strategy_portfolio' AS source_table,
    jsonb_strip_nulls(
        jsonb_build_object(
            'bootstrap_source', 'trading.strategy_portfolio',
            'account_source', CASE WHEN pfa.account_id IS NOT NULL THEN 'trading.pf_portfolio_account' END,
            'tactic_source', CASE WHEN ps.tactic_id IS NOT NULL THEN 'trading.pos_tp_sl_position_state' END
        )
    ) AS metadata,
    NOW() AS created_at,
    NOW() AS updated_at
FROM trading.strategy_portfolio sp
LEFT JOIN LATERAL (
    SELECT pa.account_id
    FROM trading.pf_portfolio_account pa
    WHERE pa.portfolio_id = sp.portfolio_id
    ORDER BY pa.created_at DESC NULLS LAST
    LIMIT 1
) pfa ON TRUE
LEFT JOIN LATERAL (
    SELECT st.tactic_id
    FROM trading.pos_tp_sl_position_state st
    WHERE st.portfolio_id = sp.portfolio_id
    ORDER BY st.updated_ts DESC NULLS LAST
    LIMIT 1
) ps ON TRUE
ON CONFLICT (strategy_name, portfolio_id)
DO UPDATE SET
    account_id = EXCLUDED.account_id,
    tactic_id = EXCLUDED.tactic_id,
    mode = EXCLUDED.mode,
    enabled = EXCLUDED.enabled,
    source_system = EXCLUDED.source_system,
    source_schema = EXCLUDED.source_schema,
    source_table = EXCLUDED.source_table,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();
