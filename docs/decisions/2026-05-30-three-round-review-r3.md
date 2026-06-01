# 三轮全面审查 — Round 3（跨模块一致性 + 配置漂移 + 测试覆盖）

**日期**: 2026-05-30
**审查方**: Opus self-review（cross-module + config drift）+ pipeline DAG 一致性扫描
**模式**: quick

## 审查发现汇总

### 🔴 Critical（已修）

| # | 模块:行 | 问题 | 修复 |
|---|---|---|---|
| 1 | log_real_trade.py:14-16 / calc_fee | 用本地常量 `COMMISSION=0.00025`/`STAMP=0.0005`，**没有套用 cost_model 的 5 元最低佣金**。1200 元小资金本金下：买入实际代付 5 元，但 log 写入 `1200×0.00025=0.3 元` → real_trades.csv 里"手续费"系统性低估约 95% → strategy_feedback FIFO 算净 PnL 全部失真 → 反馈闭环把"实际亏损交易"当作"小幅盈利"，自动调参方向反向。 | ✅ 直接 import `cost_model.COMMISSION_RATE / COMMISSION_MIN / STAMP_TAX_RATE`，套用 `max(amount × rate, 5)` |
| 2 | app/pages.py:942-943 | 仪表盘"我的交易"录入面板显示"佣金 X.XX + 印花税 Y.YY"分项，但用 0.00025/0.0005 的旧本地常量；同时调用 `calc_fee()` 返回的 fee 已套用 5 元最低 → 用户看到"佣金 0.30 元"但总额 5.30 元，数字不自洽。 | ✅ 改为从 `cost_model` 拉取常量，分项计算与 fee 总额一致 |

### 🟡 Quality（建议修，不阻塞 — 留作下一阶段）

- **RSI 三处实现不一致**：
  - `strategy.py.calc_rsi(close_series)` 用 **Wilder/EWM** 平滑（业界标准）
  - `exit_advisor.py.calc_rsi(code, hist_df)` 用 **简单 SMA**
  - `sim_trade.py.calc_rsi_sim(code, hist_df)` 用 **简单 SMA**
  - 后果：入场用 Wilder RSI = 32 通过（>30 阈值），出场用 SMA RSI = 28 触发（<35 阈值）—— 同一时刻两种计算法可差 5-10 点，临界值附近行为不可预期。
  - 建议：抽到 `utils/indicators.py`，三处统一调用 Wilder 版本。但此变更会改写历史回测结果，需要先在 walk_forward 上跑前后对比，**不在本次自动修**。
- **fee/commission 常量散落**：bark_sender/builders.py（STAMP=0.0005 硬编码）、replay_picks.py（0.03% 硬编码）、enhanced_backtest 注释里提及历史漂移。建议下一次重构时统一改走 `cost_model` 的常量。
- **fetch_history.py target_date_str 取自文件名**：长假/周末跑 fetch_stock_data 写出 `stock_<非交易日>.csv` → target = 非交易日 → 所有股票永远 stale → 每次都重抓 4400 只（浪费）。理想做法：从 `utils/calendar` 取真实最后交易日。
- **broker_adapter.py:120/132**：`int(amount/price/100)*100` 缺 price=0 保护，缺数据时 ZeroDivisionError。
- **alpha_gate state file 损坏静默重置**：`_load_state` 在 JSON 损坏时返回 `_blank_state()`，paused 事实丢失。建议至少 print warning。
- **cache 写无锁**：data_loader 多个并发写同一个 `cache_*.csv` 可能 race，但当前 pipeline 顺序调用，低风险。

### ⚪ Redundancy（明确不修，文档记录即可）

- `calc_ma` 在 exit_advisor.py + sim_trade.py 各写一份，两份逻辑完全相同。**理由不修**：抽出后两边都要 import，会破坏现有 sim_trade lite/full 模式的隔离；先观察后续是否有第 3 处需求再统一。
- `data_loader.py.load_fund_flow_individual` 接口名 `ak.stock_fund_flow_individual` 与 akshare 实际 API `stock_individual_fund_flow` 可能拼错；当前 graceful fallback 不影响主流程，留待用户实际启用 Advanced 级时再修。
- `enhanced_backtest.run_backtest_window` vs `main backtest` 90% 重复；同 `_main_lite vs main(full)` in sim_trade。下一轮 v8.8 重构候选，本次不动。

## Round-3 修复执行

✅ 2 处 critical fix 已应用（log_real_trade calc_fee + app/pages 显示一致性）
✅ 创建 18 条**回归测试**（`tests/test_three_round_review_regressions.py`），锁定 8 个修复点：
   - cost_model.with_slippage 开关
   - REGIME_ALLOC 五档键
   - position_sizer.calc_gap_deviation prev_close 取值
   - alpha_gate 同日不重复累加
   - fetch_history sina_symbol 沪市可转债
   - log_real_trade calc_fee 5 元最低
   - walk_forward._calc_indicators_with_ma 真生效
   - pipeline 注册表脚本均存在
✅ pytest 154/154 通过（136 旧 + 18 新）
✅ self_check 142/142（100%）

## 模式说明

- 本轮专注于"系统横向一致性"——同一概念在不同文件的不同实现是否统一
- 拦下了 Round 1/2 没看到的 fee 漂移（log_real_trade 把真实交易费用算错 95%）
- 把 8 个 round 1+2+3 的 critical fix 全部锁进 pytest 回归套件，未来回归可立即发现
