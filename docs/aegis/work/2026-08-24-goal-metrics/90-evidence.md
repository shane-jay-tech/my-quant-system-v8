# EvidenceBundleDraft — 目标验收三指标每日快照（Round 6 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 294 passed, 2 xfailed（基线 282/2xf，净增 12） |
| 定向测试 | `python -m pytest -q tests/test_goal_metrics.py` | 12 passed |
| 指标实跑 | `python goal_metrics.py` | rc=0，生成 md/json |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile goal_metrics.py core/pipeline.py` | OK |
| 当日快照 | reports/goal_metrics_20260824 | 流水线 62.5%（DEGRADED）/ 数据 99.95%（OK）/ 自检 100%（OK） |

## 关键行为锁定

- 流水线分类：success / failed / skipped_non_trading / in_progress；旧周末 FATAL 归 skip；Alpha Gate 暂停算 success。
- 数据完整率：nonzero*0.6 + volume*0.4；rows/lag 阈值来自 system_config。
- 缺失/坏文件一律 UNKNOWN 不抛异常；脚本 rc 恒 0。
- pipeline 注册表：goal_metrics 在 self_check 之前，beginner 档 daily。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **6.8940 元** < 20 元（本轮 flash 0.3992）。

## 未覆盖（不声明目标完成）

- 数据完整率的逐交易日覆盖比对（当前是快照加权）。
- 每日 pytest 真实结果落盘接入。
- 流水线月度趋势/失败原因分类。
