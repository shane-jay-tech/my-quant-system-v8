# EvidenceBundleDraft — 自检交易日口径 + 弱信号证据审查（Round 5 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 282 passed, 2 xfailed（基线 277/2xf，净增 5） |
| 定向测试 | `python -m pytest -q tests/test_selfcheck_trading_day.py` | 5 passed |
| 自检实跑 | `python _self_check.py` | 142/142 PASS（修复前 141/142） |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile _self_check.py` | OK |
| K 线新鲜度 | system_self_check JSON | `2026-08-21, 0 trading day(s) behind` PASS |

## 弱信号证据（不落地结论）

- 340 评分样本 / 320 前向收益：评分分桶非单调；multi_vote 最低五分位 T+1 -0.40%、最高五分位 +0.51%，中段无趋势；319/320 为 1/3 共识。
- 决策：样本不足以定阈值，按「无证据不落地」不实现 min_score/min_consensus gate。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **6.4948 元** < 20 元（本轮 flash 0.3129）。

## 未覆盖（不声明目标完成）

- 弱信号不买（证据不足，待样本积累）。
- 数据完整率 / 流水线成功率统计。
- 端到端「订单→sim→exit_advisor」风控口径测试。
