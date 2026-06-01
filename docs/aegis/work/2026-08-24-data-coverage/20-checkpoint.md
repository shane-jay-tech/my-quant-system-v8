# TodoCheckpointDraft — 数据完整率逐交易日覆盖（Round 9 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。
- 完成 todo：Flash 评审；compute_data_coverage；completeness 融合；测试；实跑；归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-data-coverage.md`。
- 阻塞项：本地数据两者都缺的交易日不可发现（需外部交易日历）。
- Next：pytest 每日落盘 / 交易日历引入评估 / 强熊空仓端到端 dry-run。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾 + reports/goal_metrics_*.md。
- 已锁契约：数据完整率 status = 快照与 coverage 融合（任一 UNKNOWN→UNKNOWN；否则取更差）；coverage 期望日 = history 日期 ∪ stock 文件名。
- 不要退回：不要再用「报告缺失」代表「数据缺失」。

## DriftCheckDraft

- 服务原目标：是（验收数据完整率口径更真实）。
- 兼容边界：只改 goal_metrics 指标与测试，不动数据校验器。
- 证据增长：coverage 全/缺场景 + 生产 100% 实跑。
- 决策：continue。
