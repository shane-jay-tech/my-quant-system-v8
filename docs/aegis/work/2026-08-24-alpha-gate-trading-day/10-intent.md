# TaskIntentDraft — Alpha Gate 交易日口径修复（Slice 1）

- 日期：2026-08-24
- 父目标：GOAL.md（2400 元小资金六层优化，预算 20 元）
- 难度评分（根配置评分卡）：影响面 2 + 风险领域 1 + 歧义度 1 + 新颖度 0 + 不可逆性 0 + 长程影响 2 = **6 → L3**
- 多模型路由：Flash A/B 方案 + GPT-5.6（Codex CLI, gpt-5.6-terra, effort=high）独立方案 + 总指挥（DeepSeek V4 Pro 本会话）仲裁。

## Slice Card

- Goal：Alpha Gate 只按「交易日」计数，周末/非交易日不得累加 severe；日终流水线在非交易日干净跳过（rc=0）；修复 check_trading_day 周一误判。
- Parent plan/spec：GOAL.md 成功证据第 2 条（连续 5 个交易日跑输沪深300 自动暂停选股）。
- Files：`check_trading_day.py`、`core/pipeline.py`、`alpha_gate.py`、`tests/test_three_round_review_regressions.py`、新增 `tests/test_alpha_gate_trading_day.py`。
- Boundary：不改 severe 阈值/lookback_days/超额收益计算/买卖公式/止损止盈/仓位参数；不新增数据源；断网 fail-open。
- Verification：`python -m pytest -q`；`python smoke_tests.py`；`python -m py_compile ...`；`python -m core.pipeline --dry-run`；`python alpha_gate.py --status`。
- Stop：测试回归或评审 CRITICAL 未解决即停；API 预算超 20 元即停。

## BaselineReadSetHint

- `GOAL.md`、`memory.md`（尾部已读）、`core/pipeline.py`（Alpha Gate precheck 与 check_trading_day fatal 步骤）、`alpha_gate.py`（日历日去重）、`check_trading_day.py`（周一 day_diff=3 误判）、`utils/calendar.py`（本地交易日工具）、`data/alpha_gate_state.json`。
- 基线状态：pytest 239 passed / 2 xfailed；alpha_gate_state：consecutive_severe_days=2、last_counted_date=2026-08-24、paused=false；git 工作树已有前轮大量未提交改动，本 slice 不提交。

## ImpactStatementDraft

- 正面：Alpha Gate 计数语义与目标「5 个交易日」一致，避免周末 2 天 + 实际 3 个交易日就误暂停；周末流水线不再记 FATAL，提高流水线成功率口径。
- 风险：交易日判定仍依赖新浪行情 fail-open，周一恰逢法定节假日可能被当作交易日（与旧逻辑同类风险，且最多延迟/提前一次计数）；`check_trading_day` 的 CLI 退出码语义保留（非交易日 rc=1），盘前 bat 行为不变。
