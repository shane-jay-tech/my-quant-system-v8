# TodoCheckpointDraft — 每笔订单成本门槛（Round 4 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。
- 完成 todo：L3 多模型协作；配置键；cost_model 纯函数；position_sizer 第一道 + fallback；sim_trade 第二道；10 项测试；验证与归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-cost-gate.md`。
- 阻塞项：无。
- Next：门槛阈值回测校准 / 弱信号不买 / 数据与流水线指标。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾。
- 已锁契约：`order_passes_cost_gate(amount, mcap=0, max_pct=None)` 纯函数；阈值从 `cost.order_gate_max_pct` 读取；减仓不受买入门槛拦截；订单新字段 `流通市值/往返成本/往返成本率`。
- 不要退回：不得移除执行层防线二；不得让 fallback 绕过门槛。

## DriftCheckDraft

- 服务原目标：是（策略层每笔订单过成本门槛）。
- 兼容边界：旧订单文件无 `流通市值` 时按小盘最保守；旧测试全过。
- 新 owner/fallback：cost gate 归 cost_model 判定 + position_sizer/sim_trade 双调用；无新数据源。
- 证据增长：10 项新测试 + 历史 15 笔回放。
- 决策：continue。
