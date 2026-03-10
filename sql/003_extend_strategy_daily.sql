-- 用途：为策略日度分析表补充首版可用的已实现收益与仓位统计字段。
-- 参数：无。
-- 返回值：扩展 `insights.fact_strategy_daily` 表结构。
-- 异常/边界：脚本按幂等方式编写，可重复执行；若字段已存在则跳过。

BEGIN;

ALTER TABLE insights.fact_strategy_daily
    ADD COLUMN IF NOT EXISTS realized_pnl_actual_daily NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS realized_pnl_raw_daily NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS realized_pnl_actual_cum NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS realized_pnl_raw_cum NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS position_open_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS position_closed_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS raw_exit_estimated_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN insights.fact_strategy_daily.realized_pnl_actual_daily IS '按实际执行路径统计的日度已实现收益';
COMMENT ON COLUMN insights.fact_strategy_daily.realized_pnl_raw_daily IS '按原始未干预路径估算的日度已实现收益';
COMMENT ON COLUMN insights.fact_strategy_daily.realized_pnl_actual_cum IS '按实际执行路径累计的已实现收益';
COMMENT ON COLUMN insights.fact_strategy_daily.realized_pnl_raw_cum IS '按原始未干预路径累计的已实现收益';
COMMENT ON COLUMN insights.fact_strategy_daily.position_open_count IS '截至该交易日仍处于 OPEN 的生命周期数量';
COMMENT ON COLUMN insights.fact_strategy_daily.position_closed_count IS '在该交易日完成实际关闭的生命周期数量';
COMMENT ON COLUMN insights.fact_strategy_daily.raw_exit_estimated_count IS '该交易日具有原始退出时间、但价格仍待估值的生命周期数量';

COMMIT;
