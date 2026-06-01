# TaskIntentDraft — 仓位计划必须预留佣金（Round 10 Slice）

- 日期：2026-08-24
- 父目标：GOAL.md 风控层「仓位跟随真实账户，模拟与实盘口径一致」。
- 难度评分：影响面 2 + 风险领域 2 + 歧义度 1 + 新颖度 0 + 不可逆性 0 + 长程影响 2 = **7 → L3**。
- 多模型路由：Flash A/B + GPT-5.6-terra（Codex CLI）独立方案 + Pro 仲裁。

## Slice Card

- Goal：position_sizer 生成的每日订单计划必须包含每笔 5 元最低佣金后的总成本，保证 sim_trade/实盘现金足够执行；不再出现「订单文件 3 笔，实际只能成交 2 笔」。
- Parent plan/spec：GOAL.md；每笔订单成本门槛（round 4）。
- Files：`position_sizer.py`、可能 `sim_trade.py` 仅日志；新增/修改测试。
- Boundary：不改评分/买卖公式、止损止盈、成本门槛阈值；只改预算与裁剪逻辑。
- Evidence：端到端新测试复现——2400 元、3 只各 8 元、每只 100 股，position_sizer 出 3 单（合计2400），sim_trade 第 3 单因佣金不足被拒（仅成交 2 单）。
- Stop：外部模型 CRITICAL 一致或预算超 20 元即停。
