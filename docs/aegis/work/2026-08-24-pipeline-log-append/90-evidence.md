# EvidenceBundleDraft — 流水线日志 append-only + 多段分类（Round 8 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 301 passed, 2 xfailed（基线 297/2xf，净增 4） |
| 定向测试 | `python -m pytest -q tests/test_goal_metrics.py` | 16 passed |
| 指标实跑 | `python goal_metrics.py` | 旧口径 62.5% → 新口径 71.43% |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile goal_metrics.py` | OK |

## 关键行为锁定

- bat 日志 append-only + 每段 `=== RUN START [date time] ===`。
- 分类只解析最后一段；最后终态按出现位置：SKIP / FATAL / complete / PAUSED / ^C。
- 空尾段不复用前段 success；^C 单独计 interrupted，不计 attempts。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **6.9567 元** < 20 元（本轮 flash 0.061）。

## 未覆盖（不声明目标完成）

- fetch_history 无终态进程级根因与 step timeout。
- pytest 每日落盘。
- 数据覆盖逐日比对。
