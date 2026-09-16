# my-quant-system-v8 资金路径红线图（v0.1 待总指挥与用户拍板）

> 任务 20260907-180640-296f 产物。口径：**R1 = 直接产生买/卖决策或风控动作**；R2 = 参数、资金/仓位计算、数据源与回测核心（喂给 R1 的东西）；R3 = 展示与报告（不影响决策路径）。标注规则：**标 R1/R2 的文件任何重构必须白天多模型评审（Pro+GPT 双实现），夜间执行班不得改动**。
> 依据：模块实读 + 引用链（cost_model←12 引用 / position_sizer←9 / sim_trade←8 的调用拓扑）+ docs/decisions/ 三份既有审计。本单只读，零代码改动。

## R1 · 直接下决策 / 风控动作（最高危，夜间禁改）

| 文件 | 关键函数/职责 | 说明 |
|---|---|---|
| strategy.py | 信号生成主逻辑 | 单策略决策源 |
| multi_strategy.py | 多策略聚合（覆盖 0%！） | 聚合口径直接决定买卖标的 |
| strategy_feedback.py | 策略权重反馈/风控边界回写（apply 风控到 risk_config.json） | 二轮审计已修 4 处，仍是 R1 |
| exit_advisor.py | 止损止盈建议 | 直接驱动卖出 |
| newbie_protection.py | 新手保护（仓位/频率限制，覆盖仅 8%） | 风控动作 |
| evolve_strategy.py / evolve_daily_light.py / strategy_arena.py | 策略变异/淘汰 | 改变决策源本身 |
| portfolio_manager.py | 持仓真相源合并、推荐去重 | 决定"能买什么" |

## R2 · 参数与计算 / 数据源 / 回测核心（高危，夜间禁改）

| 文件 | 说明 |
|---|---|
| position_sizer.py | 仓位计算（含 max_single_position 遗留冲突） |
| sim_trade.py | 模拟撮合/资金曲线（当日收盘 vs 次日开盘口径遗留） |
| portfolio_risk.py | 组合风控计算（覆盖 84%，最稳） |
| cost_model.py | 成本模型（被 12 模块引用，改动波及最广） |
| walk_forward.py / enhanced_backtest.py / monte_carlo.py | 回测核心（walk_forward 预热遗留；monte_carlo 前视遗留且零 import 待确认消费方） |
| etf_gate.py / alpha_gate.py | 交易门评估（评估源新鲜度遗留） |
| check_trading_day.py + utils/trading_calendar.py | 交易日历（周一歧义分支） |
| data_validator.py | 数据校验（history lag 口径） |
| fetch_history.py / fetch_stock_data.py / fetch_etf_data.py | 行情数据源入口 |

## R3 · 展示与报告（相对低危，夜间可在验收门下做机械拆分）

| 文件 | 说明 |
|---|---|
| app/pages.py（1,503 行） | 全部页面 + 录单入口（录单写真实成交→升 R2 边界，拆包时该部分按 R2 对待） |
| trade_analyzer.py | 交易分析报告 |
| psychology_assistant.py | 心理辅助（升级建议计数，二轮修过重复调用） |
| monthly_behavior_report.py / newbie_instruction_card.py / replay_picks.py / research_agent.py | 报告与工具 |
| _self_check.py | 自检（import 即执行的运维问题，非资金路径，但 FAIL 项含数据新鲜度） |

## 横切注意点

- **配置多副本**（架构体检 §四）横切 R1/R2：任何参数调整必须确认无第二副本覆盖。
- **data/ 生产数据**：任何阶段不得写入；每阶段门禁含 SHA-256 快照比对。
- **EMERGENCY**：本轮勘察未发现硬编码密钥或可即时触发的下单 bug；已知 Bark token 历史泄漏为 P1（用户侧轮换），不升级 EMERGENCY。

## 引用声明

本图与 docs/decisions/2026-09-03-deep-audit-round2.md §5"仍未动"六项、2026-09-02 审查遗留、2026-09-05 覆盖率审计（R4/R6 未钉桩）一一对应；逐项去向见 refactor-blueprint-20260907.md §c。
