# Build Log

## Build: 2026-07-14 测试覆盖率审查

- `PLAN.md`：锁定测试审查目标、边界和验收命令。
- `tests/test_portfolio_risk.py`：新增组合风险、VaR/CVaR、回撤、波动、换手率测试。
- `tests/test_strategy_core.py`：新增选股参数、指标、过滤、集中度和报告测试。
- `tests/test_enhanced_backtest_core.py`：新增 T+1、死叉、成本、市场状态和结果分析测试。
- `tests/test_v87_post_cleanup_regressions.py`：修复旧测试的真实权益曲线写入泄漏。
- `docs/decisions/2026-07-14-test-coverage-audit.md`：归档覆盖率证据、问题分级和风险。
- Proof：`235 passed, 2 xfailed`；branch coverage `19% -> 25%`。
- 规格偏差：多模型中转因环境缺少三模型变量而不可用，按 AGENTS.md 例外降级单模型。
- 修正轮次：风控测试 1 轮、回测测试 1 轮；未修改生产逻辑。
