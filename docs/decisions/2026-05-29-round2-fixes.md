# Round 2 修复归档（2026-05-29）

## 触发原因
Round 1 修了 4 处 bug 后，三方再审（DeepSeek + GPT + Kimi）找到 Round 1 自身漏洞和遗漏，共 9 项需要修。

## 修复清单

### M1 — count_trading_days partial coverage（utils/calendar.py）
**问题**：local stock_*.csv 只覆盖最近 8 天；entry_date 早于这窗口的旧持仓，hold_days 会被严重低估，"满 N 个交易日到期"延迟。
**修法**：区间被本地文件**完全覆盖**才直接用 local 计数；只有部分覆盖时，未覆盖段 fallback `weekday_count`，覆盖段用 local 实测。

### M2 — FIFO 买入手续费重复扣（strategy_feedback.py:pair_real_trades_fifo）
**问题**：`head['fee'] / head['shares_left']` 中 `shares_left` 随分批卖减少，分母越来越小 → 同一批买入的手续费被多次扣。
**修法**：买入入队时存 `original_shares` + `total_fee`；每次摊销用静态 `total_fee / original_shares`。

### M3 — pnl_pct 用毛收益不是净收益（strategy_feedback.py）
**问题**：1200元小资金 + 5元手续费下限，毛 +0.5% 的交易实际是净亏损，但被记为 win → 胜率系统性虚高 5-15pp。
**修法**：`pnl_pct = pnl_amount(净) / cost_basis(含买入费) * 100`；毛收益保留为 `pnl_pct_gross` 仅供参考。

### M4 — NaN 手续费污染 metrics（strategy_feedback.py）
**问题**：`float(NaN or 0) = NaN`（NaN 是 truthy），NaN 一旦混进 pnl_amount 整条 metrics 链全失效。
**修法**：`_safe_float / _safe_int` 显式 NaN 检查。

### M5 — 同日买卖排序歧义（strategy_feedback.py + exit_advisor.py）
**问题**：CSV 同日买卖行顺序不保证；卖出行先于买入行时 buy_queue 为空，卖出被静默丢弃。
**修法**：按 `代码 → 日期 → 方向(买入=0/卖出=1)` 三键排序。

### M6 — exit_advisor 文件陈旧静默使用（position_sizer.py + bark_sender/parsers.py）
**问题**：用 wildcard `exit_advisor_*.json` 兜底，今日文件缺失时静默用昨天的 → 用户拿到陈旧卖出建议（已卖过/价格变了）。
**修法**：严格只读 `exit_advisor_{today}.json/.md`；缺失返回空 + 打印告知。

### M7 — alert_only 硬编码（strategy_feedback.py）
**问题**：`adjustments['alert_only'] = True` 写死，所有 else 分支结构性 dead code；想关 alert_only 必须改源码。
**修法**：`bool(cfg_get('feedback.alert_only', True))`，外部 config 可覆盖。

### M8 — exit_advisor.load_real_positions 用 last_buy 而非 FIFO 加权均价
**问题**：多次买入同票时，止损线/到期判定基于最近一次买入价；与 strategy_feedback FIFO 语义不一致；旧仓"满 N 天"永不到期（每次新买刷新）。
**修法**：FIFO 配对剩余 → 加权均价 + 最早未平仓买入日。

### M9 — full 模式非交易日不更新权益曲线
**问题**：lite 路径调 `update_equity_curve`，full 不调 → 节假日 equity 列空缺，benchmark/tracking 报告周末缺数。
**修法**：full 路径非交易日也调一次（含 try-except 防错）。

## 测试
- 新增 11 个 Round 2 回归测试：M1/M2/M3/M4/M5/M6×2/M7/M8/M9
- 全套 130/130 pass，self_check 142/142

## 文件变更
- utils/calendar.py — partial coverage 逻辑
- strategy_feedback.py — _safe_float/_safe_int + FIFO 修复 + cfg_get alert_only
- position_sizer.py — _load_today_exit_signals 仅今日
- bark_sender/parsers.py — _parse_exit_advisor_sells 仅今日
- exit_advisor.py — load_real_positions FIFO
- sim_trade.py — full 非交易日加 update_equity_curve
- tests/test_v87_post_cleanup_regressions.py — +11 测试
