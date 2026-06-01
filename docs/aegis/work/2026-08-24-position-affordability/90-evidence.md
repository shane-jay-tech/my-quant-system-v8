# EvidenceBundleDraft — 仓位计划预留佣金（Round 10 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 307 passed, 2 xfailed（基线 302/2xf，净增 5） |
| 定向测试 | `python -m pytest -q tests/test_risk_consistency_end_to_end.py tests/test_position_sizer.py tests/test_cost_gate.py` | 27 passed |
| 关键场景 | 2400 / 3×8 元 | 旧：3 笔计划、sim 成交 2；新：2 笔计划、占用 1610、剩余 790 |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile position_sizer.py` | OK |

## 关键行为锁定

- 现金判定：`金额 + max(金额×0.0003, 5)`，不含滑点（GPT 修正）。
- 订单新增预计佣金/预计总成本；summary 新增佣金合计/占用现金。
- 成本门槛 fallback 单票 2400 → 自动缩至 1600（1605 占用）。
- sim_trade 防线二保留。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **7.2626 元** < 20 元（本轮 flash 0.3031）。

## 未覆盖（不声明目标完成）

- pytest 每日落盘。
- 强熊空仓端到端 dry-run。
- 外部交易日历。
