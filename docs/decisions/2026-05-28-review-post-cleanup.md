# 2026-05-28 v8.7 清理后第二轮 /review

> 触发：用户「继续检查吧」（在 v8.7 冗余清理 + utils 抽取 + cost 单源 + REGIME 恢复完成后）
> 流程：health_check OK → Opus + DeepSeek + GPT 三方独立审查（每方 ≥5 问题）→ Opus 合并去重 → 逐条 grep/Read 验证

## 三方原始产出（节选关键 critical）

### DeepSeek V4 Pro（审查官）
1. **🔴 sim_trade full-mode 价格类型 bug**：`sim_trade.py:873-878` 非交易日分支 `pos['current_price'] = prices[code]`，但 `load_price_data()` 返回 `{code: {'price':..., 'name':..., 'change_pct':...}}` 是 dict——后续 `(prices[code] - pos['entry_price'])` 直接 TypeError。lite 模式 v8.7 已修，full 模式同样的 bug 漏修。**真金白银流程**。
2. **🔴 exit_advisor 日历日 vs 交易日**：`exit_advisor.py:163` `hold_days = (datetime.now() - entry_dt).days`——周末/国庆持仓被算作满 N 天到期，提前止盈/平仓。
3. **🔴 strategy_feedback 真实交易盲点**：`strategy_feedback.py:280-329` 当 `real_count > 0` 走 placeholder 分支：`win_rate = 0.5` 硬编码、`trades['盈亏'] = 0.0` 不算真实 PnL、提前 `return adjustments`（空字典）。**真实交易越多 → 反馈越失效**，与 v7.5 "真实数据优先级最高" 设计完全相反。
4. 🟡 exit_advisor 用最后一次买入价做止损基准，加仓后持仓 PnL 计算错误。
5. 🟡 RSI/MA 动态参数与 evolve_daily_light 写入 `evolve_daily_state.json` 没看到读取链路接回 strategy.py，疑似断链（待深挖）。

### GPT-5.5 Pro（主程序员独审）
1. **🔴 pipeline exit_advisor 顺序晚一天**：`core/pipeline.py:47` position_sizing → `:50` sim_trade → `:60` exit_advisor。但 `position_sizer.py:535` `generate_order_file` 调 `_load_today_exit_signals()` 读 `results/exit_advisor_*.json`——今天的还没生成，永远只能合并昨天的卖出建议到 `daily_orders.md`。
2. 🟡 1200 元 + 50 亿市值过滤 + 100 股最小单位，可能产生 0 订单未告警。
3. 🟡 5 个 orphan 模块未接入 pipeline：`smoke_tests.py / premarket_sim.py / newbie_instruction_card.py / check_trading_day.py / integrate_knowledge.py`（部分由 .bat 调，部分裸跑）。
4. 🟡 4 个核心模块 0 测试：`strategy.py / multi_strategy.py / portfolio_risk.py / fetch_stock_data.py`。
5. 🟡 sim_trade 启动 delta sync 假设 real_trades.csv 时间序列单调，撤资后再投入的乱序场景未测。

### Claude Opus 4.7（架构师独审）
- 🔴 三大决策路径 bug 与上方一致（独立得出）
- 🟡 Bark 推送在 lite 模式被跳过，1200 元用户没看到出场信号
- 🟡 `archive/` 仍 ~3MB，202605/data/ 已确认保留但未在 .gitignore 里

## 验证结果（grep + Read 复核）

| # | 问题 | 文件:行 | 状态 |
|---|------|---------|------|
| A1 | sim_trade full-mode dict-as-price | sim_trade.py:873-878 | ✅ VERIFIED（3 处 prices[code] 全要改 prices[code]['price']）|
| A2 | exit_advisor 日历日 | exit_advisor.py:160-165 | ✅ VERIFIED |
| A3 | strategy_feedback 真实盲点 | strategy_feedback.py:280-329 | ✅ VERIFIED（return adjustments 在 real_count>0 分支提前 return）|
| A4 | pipeline 顺序晚一天 | core/pipeline.py:47/50/60 + position_sizer.py:505-526/535 | ✅ VERIFIED |
| B1 | 加仓持仓基准价 | exit_advisor.py | 🟡 待深查 |
| B2 | 1200 元空订单告警 | position_sizer.py | 🟡 待深查 |
| B3 | 5 orphan 模块 | 多文件 | 🟡 已确认存在 |
| B4 | 4 核心模块零测试 | tests/ | 🟡 已确认 |

## Opus 仲裁

**A1-A4 都是 v7.5 → v8.7 累积下来的真金白银路径 bug，107/107 单测和 142/142 self-check 没覆盖到——因为单测都用 mock 数据，self-check 看的是文件存在性而不是数据流形。**

修法：
- A1：改 3 行（`prices[code]['price']`），加 1 个 full-mode 非交易日单测
- A2：抽 `count_trading_days(start, end)` 工具函数，用 trading_days.csv，回填到 exit_advisor，加 1 个跨周末单测
- A3：删除 placeholder 分支，让 real 路径真正算 PnL/win_rate，复用回测路径里已有的成对匹配逻辑
- A4：把 `_load_today_exit_signals()` 从 generate_order_file 拆出来，挪到 pipeline 里 exit_advisor 之后、broker_adapter 之前的「订单合并」步骤；或者更简单——pipeline 顺序改成 exit_advisor → position_sizing → sim_trade

**B 类**问题不直接威胁资金，可以排到 v8.8 周期。

**关键陷阱**：A4 修法二（调换顺序）要小心 position_sizer 依赖 sim_trade 的当日 cash/position 状态——必须先 sim_trade 出场结算回收资金，position_sizer 才知道可投资金。所以正确顺序是：
`exit_advisor`（生成卖出建议）→ `sim_trade.check_exits`（结算回收）→ `position_sizing`（按新 cash 算买入）→ `sim_trade.execute_buy`（下单）。
当前 sim_trade 是单步把 check_exits + execute_buy 包死的，要拆。这个 refactor 属于中型改动，不算"修 bug"。

## 用户决策点

A1-A3 是显式 bug，A4 是设计错位。建议分两批：
- **批 1（必修，估 1 小时）**：A1 + A2 + A3 + 单测覆盖
- **批 2（建议修，需用户拍板）**：A4 sim_trade 拆 + pipeline 重排（动到主流程，要谨慎）

## 关联

- [[2026-05-28-review-redundancy-scan]] 上一轮冗余清理
- [[project-quant-v8-7]] v8.7 patch 记忆
