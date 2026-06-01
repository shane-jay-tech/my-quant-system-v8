# EvidenceBundleDraft — 每笔订单成本门槛（Round 4 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 277 passed, 2 xfailed（基线 267/2xf，净增 10） |
| 定向测试 | `python -m pytest -q tests/test_cost_gate.py` | 10 passed |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 语法 | `python -m py_compile cost_model.py core/config.py position_sizer.py sim_trade.py` | OK |
| 历史订单回放 | 15 笔 × `order_passes_cost_gate(..., 0.025)` | SKIP 2（435元2.75%、418元2.84%），PASS 13 |

## 关键行为锁定

- 纯函数：400 元小盘 3.15% → False；2400 元小盘 1.25% → True；显式 max_pct 覆盖生效；amount<=0 → False + 零成本拆解。
- position_sizer：top3 全被拦 → fallback 单票 2400 过门槛；fallback 也全不过 → 返回空 orders；强熊仍空仓；订单携带往返成本/成本率。
- sim_trade：手工 400 元高成本单被拒；2000 元正常单成交；已有持仓减仓不被门槛拦截。

## 预算证据

- `D:\code\data\cost_log.jsonl` 今日累计 **6.1819 元** < 20 元（本轮 flash 0.2177；smoke 未新增计费）。

## 未覆盖（不声明目标完成）

- 门槛 2.0%/2.5%/3.0% 的回测/前向收益校准。
- 「弱信号不买」评分门槛。
- 数据完整率/流水线成功率统计。
