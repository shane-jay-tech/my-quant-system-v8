# 2026-08-24 — 流水线 FATAL 根因修复：空仓 summary 契约（Round 7）

## 元数据

- 任务类型：缺陷修复（systematic-debugging quick lane：单 owner、可复现、低风险）
- 难度评分：影响面 1 + 风险领域 0 + 歧义度 0 + 新颖度 0 + 不可逆性 0 + 长程影响 1 = **2 → L2 下沿**
- 模型：Flash quick 评审；Pro 本会话实施与复核。health_check 全 OK。
- override：0
- 测试：pytest **297 passed / 2 xfailed**（基线 294，净增 3）；smoke 48/48；py_compile 通过
- API：本轮 Flash 0.0017 元；今日累计 6.90 元 < 20 元

## Symptom / Reproduction / Root Cause

- Symptom：goal_metrics 显示流水线成功率 62.5%，6 个失败里 4 个是 `position_sizing failed (rc=1); aborting pipeline`，日志 `KeyError: 'used_amount'`（20260729/30/31、20260803/04）。
- Reproduction：`calculate_position_sizes(pd.DataFrame(), '强熊', 2400)` → summary 缺 `used_amount`；随后 `generate_order_file()` 直接 `summary['used_amount']` → KeyError（本轮已实跑复现）。
- Root Cause：`calculate_position_sizes` 正常路径与早退路径（`alloc_pct==0 or len(picks)==0`）返回的 summary 契约不一致；早退路径缺 `used_amount / cash_remaining / sector_distribution`，消费者 `generate_order_file / generate_order_markdown` 假定完整契约。Canonical owner：position_sizer 的 summary 契约。
- PatchShape：CanonicalOwner=position_sizer summary；UpwardDrillSignal=None；Decision=fix owner。

## Change Necessity

- User-visible need：强熊/无候选日是合法输出，不应让日终流水线 FATAL、阻断后续自检/推送。
- No-change / non-code option：无（消费者按契约取键）。
- Why code change：summary 契约必须在 owner 层补全。
- Minimum boundary：只加 `_empty_summary()` 并替换早退路径；不改仓位/门槛/阈值。
- Decision: code-change

## Flash 评审（verbatim）

同意。补充风险：空仓时生成订单文件可能让下游误以为有真实交易，需在订单内容中显式标记“空仓/无操作”，避免后续流程误执行或对账异常。


补充风险的处理：generate_order_file 本来就会在 orders 为空时输出「今日无买入订单/无操作」并带强熊风控提示；新增回归测试断言风控提示存在，不引入新字段。

## 修复与验证

- `position_sizer.py`：新增 `_empty_summary()`，早退路径返回完整契约（used_amount=0 / cash_remaining=capital / sector_distribution={} / cost_gate_*）。
- `tests/test_pipeline_failure_regressions.py`：3 项回归（强熊空仓契约、无候选契约、generate_order_file 不 KeyError 且 JSON 资金分配正确）。
- 验证：pytest 297/2xf；smoke 48/48；复现脚本从 KeyError 变为 True；`python -m py_compile position_sizer.py` OK。

## Retirement

- 旧路径：无独立旧代码，早退 dict 被 `_empty_summary` 替换；无需保留兼容分支。
- 状态：closed。

## 残留（下一轮单独诊断）

- goal_metrics 里另外 2 类失败：4 个历史日志在 `update_history` 步骤无终态（20260718/19 等，含 ^C 痕迹或截断），不能归因于本 bug；需要单独检查 fetch_history 卡死/外部终止原因，考虑 step timeout。
