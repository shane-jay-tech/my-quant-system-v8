# TodoCheckpointDraft — 自检交易日口径 + 弱信号证据审查（Round 5 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。弱信号不买已明确为「证据不足，暂不落地」，不算完成目标项。
- 完成 todo：Flash 方案与 Pro 评审；_self_check K 线新鲜度交易日口径；5 项测试；_self_check 142/142；弱信号证据审查 + 负向决策归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-selfcheck-trading-day-freshness.md`；`docs/decisions/2026-08-24-review-weak-signal-evidence.md`。
- 阻塞项：弱信号 gate 缺证据（样本不足），按停止条件不做。
- Next：数据完整率/流水线成功率统计；端到端风控口径测试；或继续积累弱信号样本。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾 + weak-signal evidence doc。
- 已锁决策：不得在样本不足时硬上 min_score/min_consensus 门槛；`_trading_days_behind` 是 K 线新鲜度唯一口径。

## DriftCheckDraft

- 服务原目标：是（自动化层稳定可查；无证据不落地）。
- 兼容边界：只改自检逻辑；未动数据/策略/风控/成本计算。
- 证据增长：5 项新测试 + 142/142 实跑；弱信号负向结论有 320 样本表。
- 决策：continue。
