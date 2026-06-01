# Round 3 修复归档（2026-05-29）

## 触发原因
Round 2 修了 9 处后，DeepSeek + Kimi 三方再审（GPT 中转网络故障三连失败）。
两方独立找出的 critical 在去重后共 5 条真 bug、5 条建议性/低优先级问题。
Round 3 仅修真 bug，不动建议性优化（避免推迟稳定）。

## Round 3 真 bug（已修）

### R1 — calendar.count_trading_days 区间误扩
**问题（DeepSeek 找）**：查询区间完全在 local 左侧时，前段 `_weekday_count(s, local_min-1day)`
会越过查询终点 e。例：query [4/1, 4/5]、local 仅 [4/10]，结果会算 [4/1, 4/9] 共 7 天，
而正确答案是 [4/1, 4/5] 的 3 个工作日。
**修法**：前段终点夹到 `min(e, local_min-1)`，后段起点夹到 `max(s, local_max+1)`。
**测试**：`test_count_trading_days_query_entirely_left_of_local` +
`test_count_trading_days_query_entirely_right_of_local`

### R2 — strategy_feedback FIFO 排序非稳定
**问题（DeepSeek 找）**：pandas `sort_values` 默认 quick-sort 非稳定，同日同向多笔
买入入队顺序不可复现 → FIFO 匹配结果在 pandas 版本/数据顺序变化时漂移。
**修法**：`sort_values(..., kind='mergesort')`。
**测试**：`test_pair_real_trades_fifo_stable_sort_order`（同日两笔不同价买入，第一笔应先卖出）

### R3 — alert_only bool 字符串陷阱
**问题（DeepSeek + Kimi 都找到）**：`bool(cfg_get('feedback.alert_only', True))`，
若 system_config.json 写 `"alert_only": "false"`（字符串），`bool('false') = True`，
用户改配置永远关不掉 alert_only。
**修法**：显式分支 — bool/数字直接转，字符串走 `lower() in ('true','1','yes','y','on')`。
**测试**：`test_alert_only_string_false_parses_correctly` + 多变体测试

### R4 — sim_trade full 非交易日 except 太宽静默吞数据 bug
**问题（DeepSeek + Kimi 都找到）**：Round 2 加的 `try: update_equity_curve(state) except Exception`
吞所有异常 → 数据格式错误、字段缺失等真 bug 全被静默。
**修法**：收紧到 `except (OSError, IOError)`（写盘 IO 错误确实可恢复），其余 ValueError 等抛回。
**测试**：`test_sim_trade_full_non_trading_day_does_not_swallow_value_error`（断言 ValueError 抛出）

### R5 — exit_advisor.load_real_positions 除零保护
**问题（Kimi 找）**：`weighted_price = ... / total_shares`，若 buy_queue 空 → ZeroDivision。
**核查**：源码 100-102 行已有 `if total_shares <= 0: continue`。Kimi 误读，无需修改。

## Round 3 不修（明确取舍）

| 编号 | 三方建议 | 不修原因 |
|---|---|---|
| 双胞胎 FIFO（DeepSeek+Kimi） | 抽 utils/trade_fifo.py 公共 helper | 当前两处实现细节不同：strategy_feedback 算 PnL，exit_advisor 只算剩余持仓。强行抽象增加耦合，等第三个调用点出现再抽。 |
| 浮点残差累积（Kimi） | original_shares 静态分母在多次卖出 round-trip 后可能差 0.0001 | 量级远小于 1 分钱，不影响任何决策。 |
| cost_basis 含卖出费（Kimi） | pnl_pct 分母应含双边费 | 业内通常 ROI 分母 = 投入成本（仅买入侧），卖出费走 PnL 分子。当前实现是主流口径。 |
| 节假日 fallback exit_advisor 文件（DeepSeek+Kimi） | 周末补跑信号永空 | 设计取舍：陈旧信号比无信号更危险（用户已卖过却被再推送）。如需补跑请调度层禁止非交易日跑。 |
| weekday count 不剔节假日（Kimi） | 跨春节统计偏大 | 已在 docstring 注明是 fallback 兜底。生产路径应让 stock_*.csv 覆盖完整窗口。 |
| 脏方向数据 assert 抛（Kimi） | '买入 ' 带空格被 fillna(2) 排到末尾 | log_real_trade.py 录入时已规范化，CSV 直接编辑场景属手工修改边缘 case，加 assert 反而误伤。 |

## 测试 + 自检
- pytest: **136/136 pass**（Round 2 = 130，新增 6 个 Round 3 测试）
- self_check: **142/142**
- pipeline 顺序确认：exit_advisor #11 → position_sizing #12 → sim_trade #15

## 文件变更
- utils/calendar.py — 区间夹紧
- strategy_feedback.py — mergesort + bool 字符串解析
- sim_trade.py — except 收紧
- tests/test_v87_post_cleanup_regressions.py — +6 测试，补全 Round 1 fake_state 字段
