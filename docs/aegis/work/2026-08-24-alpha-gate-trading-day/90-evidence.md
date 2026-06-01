# EvidenceBundleDraft — Alpha Gate 交易日口径修复（Slice 1）

## 命令与结果（全部本地运行）

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 247 passed, 2 xfailed |
| 定向测试 | `python -m pytest -q tests/test_alpha_gate_trading_day.py tests/test_pipeline_alpha_gate.py tests/test_three_round_review_regressions.py` | 29 passed |
| 语法 | `python -m py_compile check_trading_day.py alpha_gate.py core/pipeline.py` | OK |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 流水线 dry-run | `python -m core.pipeline --dry-run` | 26 步列出，rc=0，未触网 |
| 周一真实检测 | `python check_trading_day.py`（2026-08-24 周一） | 「最新行情=2026-08-21(上一工作日), 工作日→假设交易日」rc=0 |
| Alpha Gate 真实路径 | `python alpha_gate.py` + `--status` | severe=-0.09，consecutive_severe_days=2（同日未再 +1），paused=false |

## 关键行为证据

- 周末不计数：`tests/test_alpha_gate_trading_day.py::test_alpha_gate_non_trading_day_does_not_count`（tmp state 写盘后 count 仍 0、无 history）。
- 流水线先交易日后 Alpha：`test_run_all_confirms_trading_day_before_alpha_gate_and_dedupes_step`（precheck 收到 trading_day_ok=True；check_trading_day 子进程未再跑）。
- 非交易日流水线干净跳过：`test_run_all_skips_cleanly_on_non_trading_day`（rc=0，_run_script 调用数为 0）。

## 预算证据

- `D:\code\data\cost_log.jsonl` 2026-08-24 两条：flash 0.3912 元 + deepseek（smoke 外部探测触发）1.7481 元 = **2.1393 元**；< 20 元上限。
- GPT-5.6 走 Codex CLI（ChatGPT Plus 额度，未计 API 费）。

## 待下一轮证据（本 slice 不覆盖，因此不声明目标完成）

- 数据完整率、流水线成功率（周末 skip 计入成功后的历史统计）
- 每笔订单显式成本门槛 gate
- 真实账户与模拟账户止损/仓位口径一致性
- 仪表盘速度/复盘/心理反馈体验指标
