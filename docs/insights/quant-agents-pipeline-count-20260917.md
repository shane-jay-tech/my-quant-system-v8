# AGENTS.md 流水线步数口径 vs core/pipeline.py 注册表（916p-a1-016，2026-09-17，只读）

## 一、实跑真值（命令与输出同段）

```
$ python -c "import sys; sys.path.insert(0,'.'); from core.pipeline import PIPELINE_STEPS as P; from collections import Counter; print(len(P)); print(Counter(v.get('schedule') for v in P.values()))"
44
Counter({'daily': 35, 'month-end': 3, 'monday': 2, 'friday': 2, 'wednesday': 1, 'thursday': 1})
```

## 二、主张一：AGENTS.md:350「核心模块（16步完整流水线，0-15）」

| 项 | 判定 | 依据 |
|---|---|---|
| 「16步」数字 | **过期＋已标历史** | 该行位于「## 系统架构 v7（仅作历史参考，v8 不再使用）」标题（:348）之下，是 v7 时点的 0-15 十六段架构；v8 已迁移注册表（AGENTS.md:279 自述），16 与真值 44 无对应关系 |

结论：语义无害（历史节已自我声明），但建议在历史节标题行后补一句 v8 指针，防新会话误当现状。

## 三、主张二：AGENTS.md:412「24步日终流水线（0-24）」逐链勾对

链式叙述实际列出 **22 个叙事段**（非 24）；逐段与注册表 key 勾对：

| 叙事段 | 对应 registry key | 勾对 |
|---|---|---|
| 1 数据 | check_trading_day/fetch_quote/fetch_etf/update_history/fetch_index/data_validator | ✓6键 |
| 2 数据层(基本面) | data_loader | ✓ |
| 3 选股(含基本面过滤) | stock_pick | ✓ |
| 4 多策略 | multi_strategy | ✓ |
| 5 回测(分档成本) | backtest | ✓ |
| 6 因子分析(周一) | factor_analysis(monday) | ✓ |
| 7 分钟K线 | minute_kline | ✓ |
| 8 仓位 | position_sizing | ✓ |
| 9 模拟交易 | sim_trade | ✓ |
| 10 组合风控 | portfolio_risk | ✓ |
| 11 反馈闭环 | strategy_feedback | ✓ |
| 12 研究 | research_agent | ✓ |
| 13 追踪 | track_performance | ✓ |
| 14 内化 | integrate_knowledge | ✓ |
| 15 心理 | psychology | ✓ |
| 16 新手指令卡 | newbie_card＋newbie_protection | ✓2键 |
| 17 推送 | bark_push（digest/decision_replay 未叙及） | ✓1键 |
| 18 自检自愈 | self_check＋auto_heal | ✓2键 |
| 19 Walk-Forward(周三) | walk_forward(wednesday) | ✓ |
| 20 蒙特卡洛(月末) | monte_carlo(month-end) | ✓ |
| 21 策略竞技(周五) | strategy_arena(friday) | ✓ |
| 22 每周任务 | external_research/evolve_strategy/benchmark_compare/tracking_error/monthly_behavior | ✓5键 |

**链内未叙及的注册表 key（12 个）**：exit_advisor、evolve_daily_light、llm_analyst、broker_export、cost_tracker、portfolio_sync、behavior_log、digest、decision_replay、goal_metrics、newbie_protection、archive。

判定：**数字错误＋过期口径**——「24步（0-24）」既不等于叙事段数（22），也不等于注册表真值（44）；44 条目按叙事可归并为上述 22 段，但另有 12 个 daily 键游离在叙述之外。

## 四、修正建议（本单不改，供日间人工裁定）

落点 1（AGENTS.md:412 行内替换）：

```
- ## 日终流水线（0-24）：数据→…→每周任务
+ ## 日终流水线：v8 起为 core/pipeline.py:PIPELINE_STEPS 注册表驱动（44 条目：
+   daily 35／month-end 3／monday 2／friday 2／wednesday 1／thursday 1，
+   按 tier 与 schedule 自动过滤）。下述 22 段为链路叙事，段≠条目。
```

落点 2（AGENTS.md:350 行后追加一行）：

```
+ > 注：上节为 v7 历史架构（16 段）。v8 现状见 :279 注册表口径（44 条目）。
```

## 五、零改动自证

`git diff -- AGENTS.md core/pipeline.py` 输出为空 ✓；未执行任何流水线步骤本体（仅 import 注册表常量）；不 push。
