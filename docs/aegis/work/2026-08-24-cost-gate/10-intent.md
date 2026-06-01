# TaskIntentDraft — 每笔订单成本门槛（Round 4 Slice）

- 日期：2026-08-24
- 父目标：GOAL.md「策略层：每笔订单过成本门槛」「成本层真实口径」
- 难度评分：影响面 2 + 风险领域 2 + 歧义度 1（阈值需配置化+证据）+ 新颖度 1 + 不可逆性 0 + 长程影响 2 = **8 → L3**
- 多模型路由：Flash A/B 方案 + GPT-5.6-terra（Codex CLI）独立方案 + 总指挥 Pro 仲裁。

## Slice Card

- Goal：新增显式成本门槛：每笔买入订单用 cost_model 逐笔计算含 5 元最低佣金的往返成本率，超过配置上限（默认 2.5%）的订单跳过；全部跳过时回退集中到最强 1 只（仍需过门槛），仍无合格订单则不买。sim_trade 同步做防线二。
- Parent plan/spec：GOAL.md；已有小资金模式（<=3000 全仓、前3只、单票1/3）。
- Files：`cost_model.py`、`core/config.py`、`data/system_config.json`、`position_sizer.py`、`sim_trade.py`、新增 `tests/test_cost_gate.py`。
- Boundary：不改评分/买卖公式、止损止盈参数、数据源；只新增门槛过滤与 fallback；阈值可配置。
- Verification：pytest 全量 + 定向；py_compile；历史订单成本分布证据；dry-run。
- Stop：外部模型 CRITICAL 一致或预算超 20 元即停。

## BaselineReadSetHint / 证据

- `cost_model.round_trip_cost(mcap, amount, with_slippage=True)` 为单一真相源。
- 历史 15 笔订单成本分布：min 0.97% / p25 1.14% / 中位 1.82% / p75 2.21% / p90 2.61% / max 2.84%；默认 2.5% 只截掉最贵的约 13%（2 笔：418 元=2.84%、435 元=2.75%），不造成大规模行为改变。
- 基线：pytest 267 passed / 2 xfailed；今日 API 已花 5.96 元。
