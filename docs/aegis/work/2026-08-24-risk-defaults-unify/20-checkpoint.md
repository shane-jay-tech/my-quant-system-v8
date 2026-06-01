# TodoCheckpointDraft — 风控默认值统一（Round 3 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。
- 完成 todo：多模型 L3 协作（Flash A/B + GPT + Pro 仲裁）；auto_heal 重建默认值；exit_advisor effective_risk_config + 动态报告；position_sizer 固定止损回退；strategy 报告文案；9 项测试；验证与归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-risk-defaults-unify.md`。
- 阻塞项：无。
- Next：订单→sim→exit_advisor 端到端口径测试 / 成本门槛 gate / 数据与流水线指标。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾。
- 已锁语义：`exit_advisor.effective_risk_config` 与 `sim_trade.load_risk_config` 的 alert_only 行为一致；position_sizer 订单始终带止损字段；strategy 报告不再有 -5% 文案。
- 不要退回：不得恢复 take=0.30/hold=30 的重建默认值，不得恢复 -5% 固定止损。

## DriftCheckDraft

- 服务原目标：是（风控口径一致 + 自愈默认值正确）。
- 兼容边界：保留 exit_advisor 模块常量兼容旧 import；未改当前 risk_config 文件。
- 新 helper：`effective_risk_config` 是 exit_advisor 内新语义出口，无跨模块循环依赖。
- 证据增长：9 项新测试 + 全量 267/2xf。
- 决策：continue。
