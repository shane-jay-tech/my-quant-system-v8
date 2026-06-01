# TodoCheckpointDraft — 流水线 FATAL 根因修复（Round 7 Slice）

- 状态：slice 完成；GOAL 仍未完成（active）。
- 完成 todo：goal_metrics 失败日志归因；强熊空仓 KeyError 复现；owner 层 summary 契约修复；Flash 评审；3 项回归；验证归档。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-pipeline-fatal-summary-contract.md`。
- 阻塞项：update_history 无终态历史失败原因未归因（无可靠证据，未猜测）。
- Next：fetch_history 步骤超时/中断诊断；pytest 每日落盘；数据覆盖逐日比对。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾 + goal_metrics 报告。
- 已锁契约：`calculate_position_sizes` 所有 return 路径都必须含 used_amount/cash_remaining/sector_distribution/cost_gate_*。
- 不要退回：不要在 generate_order_file 里用 .get 绕过——契约在 owner 层修。

## DriftCheckDraft

- 服务原目标：是（自动化层流水线稳定可查）。
- 兼容边界：只补 summary 键，不改仓位计算。
- 证据增长：3 项新测试 + KeyError 复现闭环。
- 决策：continue。
