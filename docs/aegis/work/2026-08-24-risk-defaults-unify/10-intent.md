# TaskIntentDraft — 风控默认口径统一（Round 3 Slice）

- 日期：2026-08-24
- 父目标：GOAL.md（风控层止损止盈与仓位跟随真实账户，模拟与实盘口径一致；自检自愈稳定）
- 难度评分：影响面 2（风控默认值影响实盘建议）+ 风险领域 2（止损/止盈）+ 歧义度 0 + 新颖度 0 + 不可逆性 0 + 长程影响 2 = **6 → L3**
- 多模型路由：Flash 两版 + GPT-5.6-terra（Codex CLI）独立方案 + 总指挥 Pro 仲裁。

## Slice Card

- Goal：把系统内四处互相打架的风控默认值收敛到 `core.config sim.*` 单一真相源：auto_heal 重建 risk_config、exit_advisor 回退常量、position_sizer ATR 止损回退、strategy.py 选股报告止损文案。
- Parent plan/spec：GOAL.md「止损止盈与仓位跟随真实账户，模拟与实盘口径一致」。
- Files：`auto_heal.py`、`exit_advisor.py`、`position_sizer.py`、`strategy.py`、新增 `tests/test_risk_defaults_unify.py`。
- Boundary：不改当前生效的 `data/risk_config.json` 值；不新增加密/网络/数据源；只改 fallback/重建默认值与文案读取方式。
- Verification：pytest 全量 + 定向；py_compile；用临时目录验证重建 risk_config 的输出。
- Stop：外部模型一致报 CRITICAL 或预算超 20 元即停。

## BaselineReadSetHint

- `auto_heal.py:62-68`（重建 risk_config：take 0.3 / hold 30，与系统 0.20/10 冲突）
- `exit_advisor.py:26-31`（MAX_HOLD_DAYS=30、TAKE_PROFIT_PCT=0.30 回退）
- `position_sizer.py:466-493`（ATR 不可用时固定 -5% 止损，与系统 -8% 冲突）
- `strategy.py:339/456/479`（stop fallback 0.95 / 文案 -5%）
- `core/config.py` 与 `data/system_config.json`（sim.stop=-0.08 / take=+0.20 / hold=10；risk_config 当前 alert_only=true 仅接管 hold）
- 基线：pytest 258 passed / 2 xfailed；今日 API 已花 4.11 元。
