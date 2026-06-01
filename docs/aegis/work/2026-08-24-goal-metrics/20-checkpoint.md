# TodoCheckpointDraft — 目标验收三指标每日快照（Round 6 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。
- 完成 todo：L2 协作（Flash 方案 + Pro 评审）；goal_metrics.py 三指标；pipeline 注册；12 项测试；实跑报告；归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-goal-metrics.md`；`reports/goal_metrics_20260824.md/json`。
- 阻塞项：无。
- Next：数据完整率逐交易日覆盖比对 / pytest 每日落盘接入 / 流水线月度趋势。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾 + reports/goal_metrics_*.md。
- 已锁契约：goal_metrics 永不非零退出；周末旧 FATAL 归 skip；PIPELINE_STEPS 是 dict，goal_metrics 在 self_check 前。
- 不要退回：不要把周末 skip 计入失败；不要把指标脚本失败升级成流水线 FATAL。

## DriftCheckDraft

- 服务原目标：是（验收三指标可查）。
- 兼容边界：只新增报告与注册表条目，未动执行逻辑。
- 证据增长：12 项新测试 + 当日真实快照。
- 决策：continue。
