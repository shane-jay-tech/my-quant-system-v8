# EvidenceBundleDraft — 风控默认值统一（Round 3 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 267 passed, 2 xfailed（基线 258/2xf，净增 9） |
| 定向测试 | `python -m pytest -q tests/test_risk_defaults_unify.py` | 9 passed |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile auto_heal.py exit_advisor.py position_sizer.py strategy.py` | OK |
| 生产配置直跑 | `effective_risk_config(load_risk_config())` | stop=-0.08 / take=0.20 / hold=10 / alert_only=True |
| 回退价格直跑 | `_fallback_stop_loss(10.0)` | 9.20（-8%） |

## 关键行为锁定

- auto_heal 重建 risk_config：-0.08 / 0.20 / 10 / alert_only=True。
- alert_only=true 时 exit_advisor 忽略 risk_config 的 stop/take（与 sim_trade 一致）；false 时保留反馈循环覆盖能力。
- position_sizer：无历史、历史不足、ATR 无效三种路径都写「固定-8%」止损；订单不再缺止损字段。
- strategy 报告：止损 -8%、2400 小资金模式仓位文案；摘要「止损设MA20或-8%」。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **5.9642 元** < 20 元（本轮 flash 0.2517 + smoke deepseek 1.6064）。

## 未覆盖（不声明目标完成）

- 订单→sim→exit_advisor 逐字段端到端一致性测试。
- 每笔订单显式成本门槛 gate。
- 数据完整率/流水线成功率统计。
