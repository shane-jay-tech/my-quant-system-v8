# EvidenceBundleDraft — Bark 推送成本/风控口径统一（Round 2 Slice）

## 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | 258 passed, 2 xfailed（基线 247/2xf，净增 11） |
| 定向测试 | `python -m pytest -q tests/test_bark_cost_guidance.py` | 11 passed |
| 语法 | `python -m py_compile bark_sender/builders.py bark_sender/formatters.py newbie_instruction_card.py` | OK |
| 烟雾 | `python smoke_tests.py` | 48 OK / 0 FAIL |
| 生产订单直跑 | `_build_friction_cost_addendum()` | 买入 ¥467（1 笔）→ 往返 ¥10.23（2.19%）；不再返回空串 |
| simple 直跑 | `build_bark_message_simple(...)` | 「止损-8% | 止盈+20% | 持10天」 |
| guide 直跑 | `build_tomorrow_guide(...)` | 小资金模式、单票上限约1/3、止损-8%、止盈+20%、持有10天 |

## 关键回归锁定

- 3 笔各 800 元 → 佣金 15+15、印花 1.2 → 总 31.20，逐笔 floor（旧算法只算约 7.2×2）。
- 强熊订单文件 → 风控文案「强熊市空仓观望」。
- 空候选池 → `build_tomorrow_guide([], {})` 不再除零崩溃。
- 旧文案全部消失：+15%、5-10天、8%-12%、牛市6-8成、-5%硬止损、478只。

## 预算证据

- `D:\code\data\cost_log.jsonl` 2026-08-24：flash 0.4017 + smoke 外部探测 deepseek 1.5651（本轮）；今日累计 **4.1061 元** < 20 元。

## 未覆盖（不声明目标完成）

- 推送 vs 引擎的全链路成本/风控一致性逐字段测试。
- 每笔订单显式成本门槛 gate。
- 数据完整率/流水线成功率统计。
