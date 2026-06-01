# EvidenceBundleDraft — 流水线 FATAL 根因修复（Round 7 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 297 passed, 2 xfailed（基线 294/2xf，净增 3） |
| 定向测试 | `python -m pytest -q tests/test_pipeline_failure_regressions.py` | 3 passed |
| 复现→修复 | `calculate_position_sizes(空df, 强熊, 2400)` + `generate_order_file` | 修复前 KeyError 'used_amount' → 修复后正常 |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile position_sizer.py` | OK |

## 失败归因证据

- 4 个 FATAL 日志（20260729/30/31、20260803/04）均为 position_sizing KeyError 'used_amount'，已修。
- 2 类历史失败为 update_history 无终态（含 ^C/截断），本轮不猜测、留待单独诊断。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **6.8957 元** < 20 元（本轮 flash 0.0017）。

## 未覆盖（不声明目标完成）

- fetch_history 卡死/外部中断根因与 step timeout。
- pytest 每日落盘。
- 数据覆盖逐日比对。
