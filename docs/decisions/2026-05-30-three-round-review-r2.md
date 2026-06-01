# 三轮全面审查 — Round 2（调度+进化+反馈+数据接入）

**日期**: 2026-05-30
**审查方**: Opus self-review（覆盖 fetch_history / data_loader / walk_forward / alpha_gate / strategy_feedback / broker_adapter / send_to_bark）+ Round-1 deepseek/kimi 滞留 critical
**模式**: quick

## 审查发现汇总（含 Round-1 滞留）

### 🔴 Critical（已修）

| # | 模块:行 | 问题 | 修复 |
|---|---|---|---|
| 1 | walk_forward.py:run_backtest_window | MA_LONG 参数永远不生效——调 `enhanced_backtest.calc_indicators` 把 MA 写到固定列名 'MA20'，grid search MA_LONG=[20,25,30] 实际上永远查同一列。退化为 RSI×RSI 二维网格。 | ✅ 加 `_calc_indicators_with_ma(hist, ma_long)` 本地函数，按参数动态写 'MA_long' 列；筛选条件改 `latest['MA_long']` |
| 2 | alpha_gate.py:165-180 | 同一交易日重复跑 pipeline 会让 `consecutive_severe_days` 一天 +2，5 日警戒阈值在 3 个日历日内就误触发，系统冤枉暂停。 | ✅ 加 `last_counted_date` 字段去重；同一天仅累加一次 |
| 3 | fetch_history.py:88-97 code_to_sina_symbol | 110/113/118 是沪市可转债，旧版按"1xxxxx → sz"误归深市，导致这批可转债日线全部 404 静默失败。 | ✅ 在 sh 分支增加 `code[:3] in ('110', '113', '118')` 判断 |
| 4 | fetch_history.py:211-260 双倍内存加载 | `existing_full = read_csv(history.csv)` 全量驻留，main 末尾再次 `disk_df = read_csv(...)` + `concat([disk_df, existing_full])`，4400 只 × 60 日的历史在内存里同时存两份（~50 万行临时占用），4G 小机子直接 OOM。 | ✅ 只保留 `latest_by_code` 字典（usecols 仅读 ['代码','日期']），DataFrame 用完立即 `del`；最终去重单 disk_df 自带去重 |
| 5 | data_loader.py:76 load_fundamental_data | `ak.stock_yjbb_em(date=datetime.now())` 传自然日（如 20260530）作"报告期"参数，akshare 内部找不到对应季报数据 → 静默 fail → fundamental cache 永远空 → ROE/净利润增速/负债率因子在策略里始终是 NaN。 | ✅ 加 `_latest_report_period()` helper：取（今天-45 天）之前最近的季度末（0331/0630/0930/1231），传给 ak.stock_yjbb_em |
| 6 | data_loader.py:140 load_north_flow | `ak.stock_gdfx_free_holding_detail_em()` 是"股东分析"接口（前十大流通股东、社保/基金）——不是陆股通北向，列名也对不上 → 永远 fall through except → 北向因子永远为空。 | ✅ 优先用 `ak.stock_hsgt_hold_stock_em(market='北向')`（陆股通持股个股榜），失败回退 `stock_hsgt_north_acc_flow_in_em`，最后兜底旧 API |

### 🟡 Quality（建议修，不阻塞）

- **fetch_history.py target_date_str 取值** — 从 `stock_YYYYMMDD.csv` 文件名提取，若长假/周末跑 fetch_stock_data 会写出 `stock_<非交易日>.csv`，target = 非交易日 → 所有股票永远 stale，每次都会重抓 4400 只（浪费）。理想做法：从 trading_calendar 取真实最后交易日。
- **broker_adapter.py:120/132** — `int(amount / price / 100) * 100` 没有保护 `price=0`，缺数据时 ZeroDivisionError；建议在 compliance_check 入口增加 `if price <= 0: continue`。
- **broker_adapter.py:89** — `code = order.get('代码', '').zfill(6)` 当 `代码` 缺失时返回 '000000'，会被当成有效代码（实际是平安银行）下单。建议缺代码直接 skip。
- **strategy_feedback.py:107** — `cutoff_date = datetime.now() - timedelta(days=lookback_days + 10)`：用自然日数推前瞻窗口，碰到长假会少算。改用交易日推。
- **alpha_gate.py state file 损坏 fallback** — `_load_state` 在 JSON 损坏时 silently 返回 `_blank_state()`，paused 状态被静默重置（系统已暂停的事实丢失）。建议至少 print warning 提示用户检查。

### ⚪ Redundancy（删除候选 / 合并候选）

- `fetch_history.py.existing_full` 现在已删，但 Round-1 报告里列的"calc_ma/calc_rsi 三处重复（strategy + exit_advisor + sim_trade）"仍未处理 — 留 Round 3 决策（轻量重构）
- `data_loader.py.load_fund_flow_individual` 走 `ak.stock_fund_flow_individual()` ——akshare 实际接口名 `stock_individual_fund_flow`，不一定能跑通；需要长期监控（不影响当前流水线，graceful fallback 返回空 df）
- `send_to_bark.py` 已被 `bark_sender/` 子包瘦化，主文件 67 行，符合 v8 拆解风格，无冗余
- `broker_adapter.py.to_eastmoney_format / to_flush_format / to_generic_csv` 三个格式化函数 80% 字段重叠，可抽公共 `_normalize_order(order)` helper（不是 critical，可不改）

## Round-2 修复执行

✅ 6 处 critical fix 已应用
✅ pytest 136/136 通过
✅ self_check 142/142（100%）

## 模式说明

- 本轮专注于 Round-1 滞留的 #6-#12（walk_forward / alpha_gate / fetch_history / data_loader），加上新模块快速扫描（broker_adapter / send_to_bark / strategy_feedback）
- evolve_strategy / evolve_daily_light / strategy_arena / newbie_protection / multi_strategy 暂未深入读，但它们核心逻辑在 Round-1 有间接覆盖（strategy.py / sim_trade.py / position_sizer.py 是它们的接力下游），高频 critical 已被 Round-1 拦下
- 留 Round 3 处理：跨模块一致性 + config 漂移 + 可能的 race condition（缓存同写、state file 同读同写）+ 测试覆盖空白
