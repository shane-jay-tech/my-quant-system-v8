# TodoCheckpointDraft — 仓位计划预留佣金（Round 10 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。
- 完成 todo：端到端复现；L3 多模型协作；现金收口；测试更新/新增；验证归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-position-cash-fit.md`。
- 阻塞项：无。
- Next：pytest 每日落盘 / 强熊空仓端到端 dry-run / 数据交易日历评估。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾。
- 已锁不变量：position_sizer 输出满足 `sum(金额 + max(金额×rate,5)) <= investable`；现金判定不含滑点；sim_trade 防线二保留。
- 不要退回：不要重新生成满额不可执行订单。

## DriftCheckDraft

- 服务原目标：是（仓位跟随真实账户，模拟与实盘口径一致）。
- 兼容边界：签名/返回结构兼容，summary 加字段，旧消费者仍读 used_amount。
- 证据增长：端到端 5 项 + 既有测试更新，共 307/2xf。
- 决策：continue。
