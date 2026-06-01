# 三轮全面审查 — Round 1（交易决策路径）

**日期**: 2026-05-30
**审查方**: DeepSeek V4 Pro + Kimi K2.6 (a/b) + Opus self-review (代 GPT，relay 不稳)
**审查范围**: enhanced_backtest.py / walk_forward.py / alpha_gate.py / fetch_history.py / data_loader.py / strategy.py / exit_advisor.py / sim_trade.py / position_sizer.py / portfolio_risk.py / research_agent.py / factor_analysis.py
**模式**: quick

## 三维度发现汇总

### 🔴 Critical（confirmed + 立即修）

| # | 模块:行 | 问题 | 状态 |
|---|---|---|---|
| 1 | enhanced_backtest.py:188/224/236 + cost_model.round_trip_cost | SLIPPAGE 双扣（价格调整 + 成本率各扣一次） | ✅ 已修：cost_model 加 with_slippage 开关 |
| 2 | enhanced_backtest.py:145 vs cost_model.REGIME_ALLOC | regime label "牛市/熊市" vs "强牛/弱牛/震荡/弱熊/强熊"，dyn_notional 永远 fallback 到 0.40 | ✅ 已修：映射到 5 档 key |
| 3 | sim_trade.py:451 check_exits | 跌穿止损时 exit_price=pos['stop_loss']（人工锁 -8%），低估真实穿透损失 | ✅ 已修：用 current 真实价 |
| 4 | sim_trade.py:463-466 vs exit_advisor.py:247-253 | sim 死叉判 MA5/MA30，exit_advisor 判 MA5/MA20，两套口径 | ✅ 已修：sim 改为 MA5/MA20 |
| 5 | position_sizer.py:677 calc_gap_deviation | prev_close 取 iloc[-1]（即"今天"close），gap_pct 永远≈0 | ✅ 已修：改为 iloc[-2] 昨日 close |
| 6 | walk_forward.py:run_backtest_window | MA_LONG 参数不生效（用全局 MA_LONG，硬编码 'MA20' 列名） | ⏳ 留 Round 2/3 |
| 7 | alpha_gate.py:165 | 同一交易日重复跑 pipeline 会重复累加 severe_days，5 日警戒提前误触发 | ⏳ 留 Round 2/3 |
| 8 | fetch_history.py:240-260 | disk_df + existing_full 双倍加载内存爆炸 | ⏳ 留 Round 2/3 |
| 9 | fetch_history.py:175-195 | 长假后首日 latest_by_code 误判，节后首日漏抓 | ⏳ 留 Round 2/3 |
| 10 | fetch_history.py:83-103 code_to_sina_symbol | 1xxxxx 全映射 sz；沪市可转债 110/113/118 应是 sh | ⏳ 留 Round 2/3 |
| 11 | data_loader.py:68 load_fundamental_data | ak.stock_yjbb_em(date=自然日) 错误，应传报告期 | ⏳ 留 Round 2/3 |
| 12 | data_loader.py:114 load_north_flow | ak.stock_gdfx_free_holding_detail_em 是股东分析，不是北向，应改 stock_hsgt_stock_hold_em | ⏳ 留 Round 2/3 |

### 🟡 Quality（建议修，不阻塞）

- enhanced_backtest.py: VaR 参数法偏差、survivorship bias（用今天市值过滤历史日）、simplified momentum mismatch
- alpha_gate.py: state file 损坏 fallback 时 paused 状态被重置
- exit_advisor.py: hold_days = count_trading_days(...) - 1 的 except → 0 静默吞错
- exit_advisor.py: RSI 用 simple rolling，应该 Wilder's exponential smoothing（行业标准）
- sim_trade.py:581: baseline 双兜底 `or _FALLBACK_CAPITAL`，baseline=0 时被改成 1200，total_return 失真
- position_sizer.py:_apply_regime_hysteresis 已修跨周末 bug（v8.6），但 candidate_first_seen 重置时机未严格测试
- data_loader.py:42-46 缓存写无并发锁、节假日情绪指标空值、资金流日期未校验

### ⚪ Redundancy（删除候选）

- enhanced_backtest.py: SLIPPAGE 与 cost_model 滑点率冲突（已通过 with_slippage=False 解耦，但语义双源仍存在）
- enhanced_backtest.py: run_backtest_window vs main backtest 90% 重复
- get_cost_by_mcap 是 round_trip_cost(...).rate 的薄封装，可考虑删
- generate_risk_report 多次读 equity_curve.csv（一次性加载即可）
- calc_ma / calc_rsi 在 strategy.py + exit_advisor.py + sim_trade.py **三处各写一份**，应统一到 utils
- _main_lite vs main(full) sim_trade 90% 代码重复
- load_latest_prices (exit_advisor) vs load_price_data (sim_trade) 95% 重复
- research_agent.py expansions dict 可提为模块级常量
- factor_analysis.py 内部冗余 sort_values

## Round-1 修复执行

✅ 5 处 critical fix 已应用（见上表 #1-#5）
✅ pytest 136/136 通过
✅ self_check 142/142（100%）

## 待 Round 2/3 处理

- 6/7/8/9/10/11/12: walk_forward + alpha_gate + fetch_history + data_loader 七项需要更深入的 read 才能写出准确补丁
- 所有 🟡 Quality 与 ⚪ Redundancy 留 Round 2/3 决策

## 模式说明

- 本轮 GPT relay 多次 RemoteProtocolError，由 Opus self-review 替补审查交易决策路径（strategy/exit_advisor/sim_trade/position_sizer 四个文件全文 read）
- DeepSeek + Kimi(a) + Kimi(b) 三方独立提供发现
- 全部审查记录见 `_round1/_deepseek_output.txt` / `_kimi_output_a.txt` / `_kimi_output_b.txt`
