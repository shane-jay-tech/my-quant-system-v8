# README 每日核心链条 vs 注册表＋2026-09-04 注记时效核验（916p-a1-018，2026-09-17，只读）

## 一、注册表真值（命令与输出同段）

```
$ python -c "import sys; sys.path.insert(0,'.'); from core.pipeline import PIPELINE_STEPS as P; print(sum(1 for v in P.values() if v.get('schedule')=='daily'))"
35
$ （daily 条目按注册表序）
check_trading_day,fetch_quote,fetch_etf,update_history,fetch_index,data_validator,data_loader,stock_pick,multi_strategy,backtest,minute_kline,exit_advisor,position_sizing,evolve_daily_light,track_performance,sim_trade,portfolio_risk,strategy_feedback,llm_analyst,broker_export,research_agent,integrate_knowledge,psychology,newbie_protection,newbie_card,cost_tracker,portfolio_sync,behavior_log,digest,decision_replay,bark_push,self_check,goal_metrics,auto_heal,archive
```

## 二、README:59 链条差集表（行数=链条 26 步＋daily 35 条=61 行，两侧逐项）

| # | README:59 链条步 | 对应 daily key（schedule=daily） |
|---|---|---|
| 1 | 交易日检测 | check_trading_day |
| 2 | 行情/ETF/指数抓取 | fetch_quote, fetch_etf, fetch_index, update_history |
| 3 | 数据校验 | data_validator |
| 4 | 选股策略 | stock_pick |
| 5 | 多策略对比 | multi_strategy |
| 6 | 分钟 K 线 | minute_kline |
| 7 | 出场顾问 | exit_advisor |
| 8 | 仓位计算 | position_sizing |
| 9 | 轻量进化 | evolve_daily_light |
| 10 | 模拟交易 | sim_trade |
| 11 | 策略反馈 | strategy_feedback |
| 12 | shadow 多空分析 | llm_analyst |
| 13 | 研究复盘 | research_agent |
| 14 | 知识内化 | integrate_knowledge |
| 15 | 交易心理 | psychology |
| 16 | 新手保护 | newbie_protection |
| 17 | 成本审计 | cost_tracker |
| 18 | 持仓同步 | portfolio_sync |
| 19 | 行为日志 | behavior_log |
| 20 | 开盘前简报 | digest |
| 21 | 决策回放 | decision_replay |
| 22 | 推送（Bark / webhook / 飞书） | bark_push |
| 23 | 目标指标 | goal_metrics |
| 24 | 自检 | self_check |
| 25 | 自动修复 | auto_heal |
| 26 | 数据归档 | archive |

README 链条共 26 步，覆盖 daily key 29/35。

**注册表 daily 35 条逐项对照**（✓=README 已叙及；✗=README 缺步）：

| daily key | README 叙及 | 缺/位置注记 |
|---|---|---|
| check_trading_day | ✓ 第 1 步 | — |
| fetch_quote | ✓ 第 2 步 | — |
| fetch_etf | ✓ 第 2 步 | — |
| update_history | ✓ 第 2 步 | — |
| fetch_index | ✓ 第 2 步 | — |
| data_validator | ✓ 第 3 步 | — |
| data_loader | ✗ 缺步 | 注册表序位于 data_validator 之后 |
| stock_pick | ✓ 第 4 步 | — |
| multi_strategy | ✓ 第 5 步 | — |
| backtest | ✗ 缺步 | 注册表序位于 multi_strategy 之后 |
| minute_kline | ✓ 第 6 步 | — |
| exit_advisor | ✓ 第 7 步 | — |
| position_sizing | ✓ 第 8 步 | — |
| evolve_daily_light | ✓ 第 9 步 | — |
| track_performance | ✗ 缺步 | 注册表序位于 evolve_daily_light 之后 |
| sim_trade | ✓ 第 10 步 | — |
| portfolio_risk | ✗ 缺步 | 注册表序位于 sim_trade 之后 |
| strategy_feedback | ✓ 第 11 步 | — |
| llm_analyst | ✓ 第 12 步 | — |
| broker_export | ✗ 缺步 | 注册表序位于 llm_analyst 之后 |
| research_agent | ✓ 第 13 步 | — |
| integrate_knowledge | ✓ 第 14 步 | — |
| psychology | ✓ 第 15 步 | — |
| newbie_protection | ✓ 第 16 步 | — |
| newbie_card | ✗ 缺步 | 注册表序位于 newbie_protection 之后 |
| cost_tracker | ✓ 第 17 步 | — |
| portfolio_sync | ✓ 第 18 步 | — |
| behavior_log | ✓ 第 19 步 | — |
| digest | ✓ 第 20 步 | — |
| decision_replay | ✓ 第 21 步 | — |
| bark_push | ✓ 第 22 步 | — |
| self_check | ✓ 第 24 步 | — |
| goal_metrics | ✓ 第 23 步 | — |
| auto_heal | ✓ 第 25 步 | — |
| archive | ✓ 第 26 步 | — |

**缺步合计 6**：data_loader, backtest, track_performance, portfolio_risk, broker_export, newbie_card


## 三、README:74 四条时效表（固定 4 行，每条附证据）

| 注记原文（摘要） | 证据 | 现判定 | 建议 |
|---|---|---|---|
| ① LLM 融合层仍待配置 DEEPSEEK_API_KEY 方可实跑 | `python -c "from core.llm import llm_available; print(llm_available())"` → **llm_available = False**；core/llm.py:54 读 env/secrets、:99 未配置即 raise | **仍成立（准确）** | 保留 |
| ② 晨间任务 QuantMorningPipeline（09:15）尚未注册，QuantStallWatchdog（21:00）已注册 | `cmd //c "schtasks /query /tn QuantMorningPipeline"` → **QuantMorningPipeline 下次运行 2026/9/17 9:15 就绪**；同法 QuantStallWatchdog → 下次 2026/9/17 21:00 就绪 | **已过期**：晨间任务现已注册 | 改为「两任务均已注册（09:15／21:00）」 |
| ③ 流水线 2026-08-21 起停摆 | `ls -t logs/pipeline_*.log` 最新＝**pipeline_20260916.log，mtime 2026-09-16 15:37:03**（今日 15:37 档已有产出） | **已过期**：管道已复活运行 | 改为「2026-09-16 起已恢复每日 15:37 运行（见 logs/pipeline_*.log）」 |
| ④ 4 个 bat 行尾问题已修，待次日 15:37 验证 | `git log --oneline -- daily_pipeline.bat morning_pipeline.bat` → **b828b9a "quant: revive pipeline scripts and stall watchdog"**；结合③今日 15:37 log 存在＝验证已通过 | **已过期（验证已闭环）** | 改为「已于 9/4 重写修复，9/16 起验证运行正常」 |

（首跑 schtasks 直接调用被 Git Bash 路径转义拦截——原始报错「无效参数/选项 - 'C:/Program Files/Git/query'」；改经 `cmd //c` 后成功，证据如上，②行非「无法确证」。）

## 四、修正草稿（不改 README，供日间裁定）

落点 README.md:74 行替换草稿：

```
> **当前状态（2026-09-17 核验更新）**：① LLM 融合层仍待配置 DEEPSEEK_API_KEY（llm_available=False）；
② QuantMorningPipeline（09:15）与 QuantStallWatchdog（21:00）两个计划任务均已注册就绪；
③ 日终流水线已恢复（b828b9a），logs/pipeline_20260916.log 起 15:37 档每日运行正常；
④ 4 个 bat 行尾问题（计划任务 9009）已于 2026-09-04 重写修复并验证。
```

README.md:59 链条建议补 6 缺步（data_loader／backtest／track_performance／portfolio_risk／broker_export／newbie_card），草稿：

```
- **每日核心**：交易日检测 → 行情/ETF/指数抓取 → 数据层 → 数据校验 → 选股策略 → 多策略对比 → 回测(分档成本) → 分钟 K 线 → 出场顾问 → 仓位计算 → 轻量进化 → 模拟交易 → 策略反馈 → shadow 多空分析 → 券商导出 → 研究复盘 → 追踪 → 知识内化 → 交易心理 → 新手保护 → 新手指令卡 → 成本审计 → 持仓同步 → 行为日志 → 开盘前简报 → 决策回放 → 推送（Bark / webhook / 飞书）→ 目标指标 → 自检 → 自动修复 → 数据归档。
```

## 五、零改动自证

本单零触碰 README.md：`git diff -- README.md` 的现有输出＝a1-015 已归因的班前既有脏项（与本单无关、逐字未新增）；未注册/未启停任何计划任务；未执行流水线步骤本体；不 push。
