# 2026-05-23 v8.6 — 核心模块测试覆盖（P1-2）

## 问题

v8.5 测试目录只有 2 个测试文件（test_cost_model + test_etf_gate），核心交易逻辑模块（sim_trade / position_sizer / strategy_feedback）零覆盖。

## 决策

新增 3 个测试文件，覆盖 v8.6 修复的关键回归点：

- `tests/test_sim_trade.py` — 10 个 case
- `tests/test_position_sizer.py` — 11 个 case
- `tests/test_strategy_feedback.py` — 11 个 case

合计 32 个新增测试。重点回归 v8.6 修复行为：

- **alert-only 模式回归**（test_strategy_feedback）— 验证 stop_loss_pct/take_profit_pct/position_size_mult 在反向逻辑触发条件下**不**被自动修改
- **30 笔门槛回归**（test_strategy_feedback）— 10 笔时不应触发任何自动调整
- **trading_days 修复回归**（test_position_sizer）— 跨长假场景不会被 cal_days*5/7 误估
- **atomic write 回归**（test_sim_trade + test_strategy_feedback）— 写完无 .tmp 残留
- **risk_config 历史归档**（test_strategy_feedback）— 第一次写无归档、第二次写有归档、31 天前自动清理

## 验证

```
============================= 96 passed in 0.75s ==============================
```

64 个现有测试 + 32 个新增测试，全绿无回归。

## 风险

无显著风险。GPT-coder 写完后已自验通过。所有测试用 pytest tmp_path fixture 隔离 IO，不依赖现有 sim_results/ 或 data/ 目录。
