# EvidenceBundleDraft — 数据完整率逐交易日覆盖（Round 9 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 302 passed, 2 xfailed（基线 301/2xf，净增 1） |
| 定向测试 | `python -m pytest -q tests/test_goal_metrics.py` | 17 passed |
| 指标实跑 | `python goal_metrics.py` | coverage=100%，expected 20260817..21，missing=无 |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile goal_metrics.py` | OK |

## 关键行为锁定

- 期望日 = history.csv 日期 ∪ stock_*.csv 文件名，取最近 5。
- 每日期检查 stock csv 行数 >=4000；<80 FAIL、<100 DEGRADED、100 OK。
- 快照与 coverage 融合：任一 UNKNOWN→UNKNOWN，否则取更差。
- 20260818/19 报告缺失但 stock 数据完好 → coverage 100%，不再误伤数据完整率。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **6.9595 元** < 20 元（本轮 flash 0.0028）。

## 未覆盖（不声明目标完成）

- 两者都缺的交易日发现（需外部交易日历）。
- pytest 每日落盘。
- 强熊空仓端到端 dry-run。
