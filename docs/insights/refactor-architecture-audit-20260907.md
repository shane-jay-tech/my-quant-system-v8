# my-quant-system-v8 重构第 0 阶段 · 架构体检（v0.1 待总指挥与用户拍板）

> 任务 20260907-180640-296f 产物。只读勘察，零生产代码改动（git 快照比对通过）。基线：pytest **392 passed / 2 xfailed / 0 failed**；分支覆盖率 **TOTAL 46%**。同人无关；本单为量化系统运维文档。

## 一、模块依赖全景

- **布局**：根目录平铺 60+ 个 .py（约 3 万行）＋ `app/`（pages.py 单文件 1,503 行）＋ `core/`（config/llm/pipeline，仅 4 件）＋ `utils/`＋`bark_sender/`＋`tests/`（32 文件）。**"core 包存在但与根目录平铺逻辑并存"是第一结构性问题**：没有真正的分层，只有"新代码住 core、旧代码住根目录"。
- **事实核心（被依赖最多）**：cost_model（12 处引用）→ position_sizer（9）→ sim_trade（8）→ enhanced_backtest（5）→ walk_forward/sector_classifier/etf_gate/check_trading_day/alpha_gate（各 4）。依赖方向总体健康：无发现 core→app 反向引用；app/pages.py 对 core.config 的 3 处引用全部是**函数内延迟 import**（L470/613/685）——是为了规避循环或加载顺序的补丁式写法，属分层未定的症状。
- **上帝模块**：app/pages.py（1,503 行，页面+业务+录单+看板混合）；sim_trade.py（1,041）；position_sizer.py（1,007）；strategy_feedback.py（919）。

## 二、重复逻辑清单

| 症状 | 位置 | 说明 |
|---|---|---|
| `generate_report` ×9 | 根目录 9 个模块各自实现 | 报告生成无公共骨架 |
| `render_report` ×4 | app 侧 | 同上，展示层重复 |
| `save_state` ×3 | 状态持久化各自为政 | 无统一状态层（与 json.load 散布互为因果） |
| `call_gpt.py` / `call_gpt2.py` | 根目录 | **孪生文件**，疑似一次性脚本残骸，死代码首要候选 |
| 配置默认值多处定义 | 各模块 `json.load` 后各自 `get(key, default)` | 默认值口径分散（R2 风险：改一处漏三处） |

## 三、死代码/未使用文件候选（零 import 引用，**均需人工确认**——根目录脚本多为计划任务/手动入口，零 import ≠ 死代码）

- 强烈疑似死代码：`call_gpt2.py`（与 call_gpt.py 并存）、`benchmark_comparison.py`、`factor_analysis.py`、`external_research.py`
- 疑似纯入口（计划任务/手动跑，保留但应归入 ops 层）：`daily_pipeline.py`、`evolve_strategy.py`、`evolve_daily_light.py`、`fetch_stock_data.py`、`fetch_etf_data.py`、`archive_old_data.py`、`backup_state.py`、`premarket_sim.py`、`monthly_behavior_report.py`、`replay_picks.py`、`research_agent.py`
- 待查：`monte_carlo.py`（零 import，但审计遗留清单点名其前视问题——若已无消费方，修复优先级可降）

## 四、全局状态与单例

- **配置**：`core/config.py` 提供 get/set_value（含 lru_cache），但仅被少数模块使用；其余模块**各自 `json.load` 配置文件**（strategy_feedback×5、sim_trade×4、position_sizer×4、portfolio_manager×4、_self_check×4…）——同一份配置在一个进程里可能有 N 个互不知晓的副本，热更新语义不一致。
- **密钥**：`secrets.json` 读取散布于 `_self_check`、`archive_old_data`、`bark_sender/*`、`core/llm` 等 6+ 处（无统一 secrets 入口；Bark token 历史泄漏已知，轮换在用户侧）。
- **状态文件**：`save_state`×3 + 各自 json 读写，无事务/原子写保证的统一封装。

## 五、路径收敛现状（比预期更差）

- `utils/paths` **引用数 = 0**；同时 **90 个文件**各自手写 `Path(__file__)`/`os.path.join` 拼路径。即"收敛方案"实际从未落地，属全新工程量而非补漏。

## 六、覆盖率基线（分支覆盖，TOTAL 46%）

| 关键模块 | 覆盖率 | 备注 |
|---|---|---|
| portfolio_risk | 84% | 最佳 |
| position_sizer | 58% | R2 核心，缺口在分支 |
| strategy | 70% | — |
| trade_analyzer | 57% | — |
| sim_trade | 40% | **R1/R2 核心，覆盖不足** |
| strategy_feedback | 42% | R1 |
| strategy_arena | 38% | — |
| **multi_strategy** | **0%** | **盲区**（多策略聚合直接参与决策） |
| newbie_protection | 8% | 新手保护近乎裸奔 |
| replay_picks / research_agent | 0% | 工具类 |
| monthly_behavior_report | 11% | — |

## 七、技术债分级（P0/P1/P2）

**P0（进入蓝图第一阶段前必须知道）**
1. multi_strategy.py 0% 覆盖且参与决策聚合——重构前必须先做 characterization 测试钉桩。
2. sim_trade.py 40% 覆盖 + 资金口径遗留（当日收盘 vs 次日开盘）——重构会放大口径风险。
3. 配置多副本读入（无单例）——任何"调参"都可能被另一个副本覆盖，影响面全系统。

**P1**
4. pages.py 1,503 行上帝模块（含函数内延迟 import 的分层补丁）。
5. utils/paths 零收敛（90 文件手写路径）。
6. _self_check.py import 即跑整份自检（513 行）。
7. secrets 读取散布 6+ 处（配合 Bark token 轮换）。
8. call_gpt/call_gpt2 等 15 个零引用模块身份确认。

**P2**
9. generate_report ×9 / render_report ×4 / save_state ×3 重复骨架。
10. AGENTS/CLAUDE 双份维护。
11. Windows 计划任务 LastResult=9009（人工核查项）。

> 以上 P0/P1 全部编入蓝图（refactor-blueprint-20260907.md）对应阶段卡；遗留清单逐项去向见蓝图 §c。
