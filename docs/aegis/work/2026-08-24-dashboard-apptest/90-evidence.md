# EvidenceBundleDraft — 仪表盘 AppTest + goal_metrics 集成验证（Round 11 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 308 passed, 2 xfailed（基线 307/2xf，净增 1） |
| 仪表盘测试 | `python -m pytest -q tests/test_dashboard_apptest.py` | 1 passed（AppTest 0 异常） |
| 仪表盘实测 | AppTest.run | 1.18s，exceptions=0 |
| 集成实跑 | `core.pipeline.run_all(only=['goal_metrics'])` | trading check → Alpha Gate counted=True(counter=2) → goal_metrics rc=0 → Pipeline complete |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **7.2626 元** < 20 元；本轮 0 元。

## 未覆盖（不声明目标完成）

- pytest 每日落盘。
- 六层证据合成整体验收清单。
