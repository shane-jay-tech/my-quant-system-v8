# TodoCheckpointDraft — Alpha Gate 交易日口径修复（Slice 1）

- 状态：slice 完成，目标未完成（GOAL 仍 active，下一轮继续六层验收）
- 完成 todo：
  1. 多模型协作（Flash A/B + GPT-terra + Pro 仲裁）
  2. check_trading_day 周一误判修复
  3. core.pipeline 交易日闸门 + 非交易日干净跳过 + Alpha Gate 顺序修正
  4. alpha_gate 非交易日不计数
  5. 测试补充与旧测试适配
  6. 验证（247 passed / 2 xfailed，smoke 48/48，dry-run rc=0）
  7. 归档 + memory 更新
- 活跃 slice：无（本轮收尾）
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-alpha-gate-trading-day.md`；`data/alpha_gate_state.json`（counter 保持 2，同日未重复计数）。
- 阻塞项：无。
- Next：下一轮候选——成本门槛显式 gate / 实盘模拟口径一致性审计 / 数据完整率看板。

## ResumeStateHint

- 从这里继续：读取本文件 + GOAL.md + memory.md 末尾。
- 已锁定的兼容边界：state 文件字段未新增（仅 AlphaGateResult.counted 为内存字段）；check_trading_day CLI 退出码语义保留。
- 不要退回：Alpha Gate precheck 必须位于交易日确认之后；`trading_day_ok=True` 是省一次联网的契约。

## DriftCheckDraft

- 仍服务原目标：是（目标第 2 条证据更严格：按交易日计数）。
- 兼容边界：未改阈值/公式/风控参数/数据源。
- 新 owner/fallback：`_check_trading_day_inline` 是新增的单一交易日判定入口，owner 为 core.pipeline；未新增数据源。
- retirement：旧 `is_paused()` 只读调用未动，仍被其他模块使用。
- 证据增长：足够支撑本 slice 声明，不足以声明整个 GOAL 完成。
- 决策：continue（目标继续下一轮）。
