# 决策核心行为规范与不变量清单（quant-E2）

- 生成：2026-09-05（夜间任务 20260904-194640-6c70）
- 用途：R1–R15 日间多模型评审的统一底稿。所有陈述附 `文件:行号`；读不准处标 **待确认** 并给验证方法。
- 口径：中文陈述、标识符英文；只读代码产出，未改任何代码。

---

## 1. position_sizer.py（仓位计算）

**职责**：把"选股结果"变成"带金额/股数/止损的订单"。三段式：加载 picks（multi_vote → pick 报告 → stock csv 兜底）→ 按市场状态分档仓位 → 按合规与成本约束切股数。

**入口/契约**：`load_latest_picks()`（position_sizer.py:886）返回 DataFrame（列：代码/名称/收盘/momentum）；`calculate_position_sizes(picks_df, regime, total_capital)`（position_sizer.py:387）输出订单 list + summary。数据源文件名即接口：`orders/multi_vote_YYYYMMDD.json`（position_sizer.py:841-847 取倒序第一个）、`results/pick_*.md`（position_sizer.py:894）、`data/stock_YYYYMMDD.csv`（position_sizer.py:917）。

**关键数值**：小资金模式 `effective_max_single = 1.0/n_picks`（position_sizer.py:434-435，v8.6 改动注释在 432-433）；ATR 止损入口 `calculate_stop_loss(hist, orders, atr_period=14, multiplier=ATR_STOP_MULTIPLIER)`（position_sizer.py:601）；止损下限 `_stop_loss_floor(code, entry_price)`（position_sizer.py:577）。

**不变量**：
1. 订单金额不超过 `broker.max_single_amount`（50 万，broker_adapter.py:39）——**现状成立**（compliance 阶段强制）。
2. 小资金档单票可达 `1.0/n_picks`（2 只票=50%、1 只=100%）——**现状违反**与文档 15% 上限冲突（**R10**，position_sizer.py:434-435；broker_adapter.py:36 的 0.15 在该模式下被绕开）。**待确认**：验证方法=2 只票小资金跑 `calculate_position_sizes` 看输出金额占比。
3. 订单不得基于非最后交易日的 multi_vote 生成——**现状违反**（**R2**，position_sizer.py:841 倒序取名无日期校验；组合 **core/pipeline.py:44** 同样按文件名取）。
4. 多源全缺失时不得"全市场 head(10) 买任意票"——**现状违反**（**R5**，position_sizer.py:913-926 兜底存在）。
5. ATR 止损必须基于最新交易日 history——**现状违反**（停摆期次生）（**R14**，position_sizer.py:601）。
6. 北交所判定不得误伤沪 B——**现状违反**（**R6**，position_sizer.py:577 `_stop_loss_floor` 内 `startswith('8'/'9')`，沪 B 900xxx 命中）。

## 2. sim_trade.py（模拟撮合）

**职责**：读当日订单 → 涨停/滑点/成本门槛过滤 → 创建或更新仓位（含止损/止盈）→ 到期/止损/死叉平仓 → 出绩效报告。

**入口/契约**：`execute_buy_orders(state, orders, prices, stop_loss_pct, take_profit_pct)`（sim_trade.py:308）；`check_exits(state, prices, max_hold_days)`（sim_trade.py:475）；`load_daily_orders()`（sim_trade.py:276，倒序取 `orders/daily_orders_*.json` 第一个，返回 `data['订单']`）；`generate_sim_report()`（sim_trade.py:639，读 `sim_results/equity_curve.csv`）。状态文件 `sim_results/account_state.json`（v8.6 起原子写，sim_trade.py:265-272）。

**关键数值**：`STOP_LOSS_PCT=cfg_get('sim.stop_loss_pct',-0.08)`（sim_trade.py:112）、`TAKE_PROFIT_PCT=0.20`（:113）、`SLIPPAGE=0.001`（:115，仅买入）；佣金 `COMMISSION_RATE=0.0003 / COMMISSION_MIN=5.0`（cost_model.py:32-33，sim_trade.py:29-30 转导入）；印花税卖出单边 `0.0005`（cost_model.py:34）；涨跌停阈值 `get_limit_pct`：688/300/301→19.8、`startswith('8'/'9')`→29.8、其余→10（sim_trade.py:124-133，**R6** 沪 B 误伤在此）。

**不变量**：
7. 止损价必须大于 0——**现状违反**（**R1**，sim_trade.py:384 `order.get('止损价', 默认)` 对显式 0/None 原样写入；对照 :410 新买分支有守卫；已由特征测试钉住 `tests/test_characterization_risk.py::TestR1StopLossZero`）。
8. 旧订单文件不得在新交易日重复成交——**现状违反**（**R3**，sim_trade.py:276-283 无日期校验；已钉住 `tests/test_characterization_stale.py::TestR3StaleDailyOrders`）。
9. 同日重跑不得重复买回当日已卖出票据——**现状部分违反**（**R4**，sim_trade.py:894-898 的 blocked 集合只覆盖"本次运行内"因 止损/死叉 平的票：重跑新进程 `closed` 为空 → 上一进程卖出票可被买回；且其他 exit_reason 不拦）。**待确认**：验证方法=同日跑两遍 pipeline lite，观察 trade_history 是否出现买回。
10. "最大回撤"必须保证 min 发生在 max 之后——**现状违反**（**R8**，sim_trade.py:716-717 `(max-min)/max`；单调上涨也报 16.67%，已钉住 `test_characterization_risk.py::TestR8DrawdownFormula`）。

## 3. exit_advisor.py（出场顾问）

**职责**：对真实持仓逐票给出持有/减持/清仓建议与理由（持仓期、止损线、死叉、基本面事件）。

**入口/契约**：逐股扫描持仓对比 history（exit_advisor.py:180 附近为全表线性扫描，88 万行×持仓数，**Q13/P2**）。**待确认**：入口函数名与 CLI 参数（验证方法=`python exit_advisor.py --help`）。

**不变量**：
11. 建议中的止损价必须与当前 config 的止损参数一致——**现状违反**（**R13**，exit_advisor.py:145 使用 import 时冻结的模块常量 `STOP_LOSS_PCT`，config 热改不生效）。

## 4. cost_model.py（成本模型）

**职责**：统一佣金/印花税/滑点/最低佣金计算，供 sim_trade 与 position_sizer 复用；提供分档滑点。

**关键数值**：`COMMISSION_RATE=0.0003`、`COMMISSION_MIN=5.0`（cost_model.py:32-33）、`STAMP_TAX_RATE=0.0005` 卖出单边（:34, :98）、滑点三档 large/mid/small = 0.001/0.002/0.003（:35-37）。

**不变量**：
12. 卖出成本 ≥ 买入成本（印花税单边）——**现状成立**（cost_model.py:98 仅 sell 加印花税）。
13. 所有成本参数必须可经 config 覆盖且有默认值——**现状成立**（全部 `cfg_get` 带默认，cost_model.py:32-37）。注意旧口径"万2.5"与现行"万3"在 memory.md 混用（**Q15/P2**）。

## 5. portfolio_manager.py（组合状态）

**职责**：维护跨日组合视图（持仓聚合、仓位占比）。**待确认**：与 sim_trade 的 state 主从关系——两处都写 `sim_results/` 下的状态，谁是 source of truth 需以调用链核实（验证方法=`grep -rn "portfolio_manager" *.py core/` 看被谁调用）。

**不变量**：
14. 持仓市值合计 + 现金 = 总权益——**现状成立**（generate_sim_report 按 cash+Σpos_value 计，sim_trade.py:643-644）。

## 6. broker_adapter.py（合规检查）

**职责**：`compliance_check(orders, stock_data, total_capital)`（broker_adapter.py:73）输出 (passed, warnings, errors)；合规常量表 COMPLIANCE（broker_adapter.py:36-39：max_single_pct 0.15 / max_total_pct 0.80 / min_order_amount 1000 / max_single_amount 500000）。

**不变量**：
15. 合规检查遇单条坏数据不得使整批失败——**现状违反**（**R7**，broker_adapter.py:124,136 `int(amount/price/100)` 对 price=0 抛 ZeroDivisionError；已钉住 `test_characterization_risk.py::TestR7ZeroPriceDivision`）。
16. 总仓位 ≤ `broker.max_total_pct`（0.80）——**现状成立**（compliance 汇总检查，broker_adapter.py:37 起的 COMPLIANCE 项）。

## 7. core/pipeline.py（DAG 注册表与调度）

**职责**：`PIPELINE_STEPS`（core/pipeline.py:35）注册全部步骤（tiers/schedule/retry/label）；`_schedule_match`（core/pipeline.py:109-115）实现 daily/month-end/星期调度；step rc≠0 的致命性规则与月末窗口在此层。

**关键数值**：月末窗口 `datetime.now().day >= 25`（core/pipeline.py:105-106，`_is_month_end()` 定义体）——**现状违反**：25-31 每天都算月末，月内多跑 6-7 次（**R11**，**Q8/P2**）。非交易日 rc=0 干净跳过（core/pipeline.py:262，v8.7）；rc=1 记 FATAL 的历史口径见 :200。

**不变量**：
17. 交易日判定必须 fail-safe——**现状部分违反**（**R12**，check_trading_day.py:103-105 日历不可用时"保守假设交易日"属 fail-open 残余，行情可用时以行情为准）。
18. 交易日历不得被幽灵文件污染——**现状违反**（**R9**，utils/calendar.py:18-20 `_list_local_trading_days` 按 stock_*.csv 文件名算交易日；stock_20260830.csv 幽灵文件已归档、代码修复待评审；auto_heal.py:219 的补抓判定同属此链）。
19. 策略反馈复核不得绕过双守卫——**现状成立但脆弱**（**R15**，strategy_feedback.py:402-404 注释明确 alert_only 改读 config 后仍依赖双守卫结构，日间改此处时严禁"顺手简化"）。

---

## 模块间调用关系（文字版）

```
core/pipeline.py（调度/致命性）
  ├─ fetch_history / fetch_quote …（数据层）
  ├─ multi_strategy → position_sizer.load_latest_picks → calculate_position_sizes
  │                                    └── cost_model（成本门槛 `_order_cost_gate_check`）
  ├─ sim_trade（execute_buy_orders / check_exits / generate_sim_report）
  │     ├── broker_adapter.compliance_check（订单合规）
  │     ├── cost_model（佣金/印花/滑点）
  │     └── utils/calendar（持有天数/交易日）
  ├─ exit_advisor（真实持仓建议）
  └─ strategy_feedback（复核，R15 守卫）
```

## 已知风险索引（R1–R15 → 所属章节）

| # | 模块节 | 位置 | 一句话 |
|---|---|---|---|
| R1 | §2 sim_trade | sim_trade.py:384 | 止损价 0/None 原样写入（新买分支 ：410 有守卫，更新分支无） |
| R2 | §1 position_sizer | position_sizer.py:841 + core/pipeline.py:44 | 陈旧 multi_vote 在今日价格上生成订单 |
| R3 | §2 sim_trade | sim_trade.py:276-283 | 旧订单文件新交易日重复成交 |
| R4 | §2 sim_trade | sim_trade.py:892-898 | 同日重跑买回已卖票（blocked 仅进程内/仅两 reason） |
| R5 | §1 position_sizer | position_sizer.py:913-926 | 兜底 head(10) 买任意票 |
| R6 | §2 sim_trade / §1 | sim_trade.py:128-130, position_sizer.py:577 | startswith('8'/'9') 误伤沪 B 900xxx |
| R7 | §6 broker_adapter | broker_adapter.py:124,136 | price=0 除零炸整批 |
| R8 | §2 sim_trade | sim_trade.py:716-717 | 回撤公式不保证 min 在 max 后（恒非负） |
| R9 | §7 pipeline | utils/calendar.py:18-20 + auto_heal.py:219 | 幽灵交易日代码级修复 |
| R10 | §1 position_sizer | position_sizer.py:435 | 小资金单票 100% vs 文档 15% |
| R11 | §7 pipeline | core/pipeline.py:105-106 | day>=25 月末窗口失真 |
| R12 | §7 pipeline | check_trading_day.py:103-105 | 节假日启发式 fail-open 残余 |
| R13 | §3 exit_advisor | exit_advisor.py:145 | import 冻结常量做止损线 |
| R14 | §1 position_sizer | position_sizer.py:601 | ATR 止损依赖 history 新鲜度 |
| R15 | §7 pipeline | strategy_feedback.py:402-404 | 复核双守卫防"顺手简化" |

不变量合计 19 条（#1–#19）：现状成立 6 条（#1,12,13,14,16,19），现状违反或部分违反 13 条（#2,3,4,5,6,7,8,9,10,11,15,17,18，对应 R10,R2,R5,R14,R6,R1,R3,R4,R8,R13,R7,R12,R9）。三条"待确认"（#2 注、§3 入口、§5 主从关系）均已附验证方法。
