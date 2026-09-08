# 15 个「零引用」模块身份核查报告（296f P0 后续 · 2026-09-08）

> 执行：GLM-5.3-Flash 夜间执行班（任务 20260908-195000-q15m，只读）。观察时点：2026-09-09 00:55 前后；HEAD=`77e6c0f`（my-quant-system-v8，codex 分支未切）。
> 方法：全仓静态扫描（import/from/importlib/`python X`/`"X.py"` 五类模式，语料含 .py/.bat/.ts/.cfg/.toml/.yml/.yaml/.txt，排除 .venv/.git/archive/data/logs/docs）＋ core/pipeline.py 注册表核对 ＋ Windows 计划任务实查（PowerShell Get-ScheduledTask）。

## 一、结论（三分档计数）

| 档 | 数量 | 明细 |
|---|---|---|
| **真死代码** | **2** | call_gpt.py、call_gpt2.py |
| **误判（有真实消费方，保留）** | **15** | 见 §二 |
| **存疑** | **0** | — |

**核心修正**：架构审计「强烈疑似死代码」4 个（call_gpt2/benchmark_comparison/factor_analysis/external_research）中 **3 个是误判**——它们全部是 `core/pipeline.py` 分层计划管线的注册步骤（tier 门控+周期调度），属入口脚本而非死代码。真正可清退的只有 call_gpt 双子。

## 二、逐模块判定与证据

### A. 真死代码（2）——S3 可清退

| 模块 | 行数 | 证据 | 处置建议 |
|---|---|---|---|
| call_gpt.py | 87 | 全仓五类模式 0 命中（import/bat/registry/schtasks/self_check 清单均无）；内容=一次性 codex 任务脚本（读 gpt_task.txt、subprocess 调 LLM CLI） | **可清退**：移 archive/ 即回滚 |
| call_gpt2.py | 87 | 同上 0 命中；与 call_gpt 仅 SYSTEM 提示词与任务文件名（gpt_task2.txt）不同，属同型副本 | **可清退**（审计点名单正确） |

### B. 误判（15）——保留，S3 不清退

**B1. pipeline 注册步骤（8 个）**——`core/pipeline.py` 分层管线注册表在案，均带 tiers/schedule：
| 模块 | 注册表行 | 调度 |
|---|---|---|
| factor_analysis.py | :46 | advanced+/周一 |
| evolve_daily_light.py | :54 | 全 tiers/每日 |
| research_agent.py | :63 | 全 tiers/每日（带 --daily 参数） |
| monte_carlo.py | :82 | advanced+/月末 |
| evolve_strategy.py | :85 | advanced+/周四 |
| monthly_behavior_report.py | :89 | 全 tiers/月末 |
| external_research.py | :84 | advanced+/周一 |
| benchmark_comparison.py | :87 | 全 tiers/周五 |
> 辅证：`_self_check.py:110-119/220-228`（存在性+类导入自检清单）、`smoke_tests.py:33-39`、`cost_tracker.py:36-55`（caller 成本归集名录）、`etf_gate.py:127`（对 benchmark_comparison 的功能衔接注释）。

**B2. bat+计划任务实锤入口（4 个）**——计划任务实查在册：QuantDailyPipeline_v5 / QuantMorningPipeline / QuantStallWatchdog / QuantWeeklyHealthCheck：
| 模块 | 证据 |
|---|---|
| daily_pipeline.py | daily_pipeline.bat:13（`"%PYTHON%" -u "%BASE%daily_pipeline.py"`）→ QuantDailyPipeline_v5 |
| premarket_sim.py | morning_pipeline.bat:22 → QuantMorningPipeline |
| stall_watchdog.py | maintenance_night.bat:12 → QuantStallWatchdog |
| backup_state.py | maintenance_night.bat:15-17（存在性守卫调用）→ QuantStallWatchdog 同任务 |

**B3. 工具消费方实锤（3 个）**：
| 模块 | 消费方 |
|---|---|
| fetch_stock_data.py | auto_heal.py:220/224（自愈流程 run_script 实调） |
| fetch_etf_data.py | core/pipeline.py:38（"fetch_etf" tier 步骤） |
| replay_picks.py | app/pages.py:454/532（UI 向用户展示的再生成命令，文档化工具） |

## 三、对蓝图 S3/S7 的反哺建议

1. **S3 阶段卡改写**：「15 个零引用模块逐个清退」应改为「**仅清退 call_gpt.py + call_gpt2.py（2 个）**」；蓝图点名「优先」的 benchmark_comparison/factor_analysis/external_research 全部为误判，**禁止清退**。
2. **其余 15 个的真正问题是「入口散落」而非死代码**——8 个 pipeline 注册步骤 + 4 个 bat 入口 + 3 个工具，对应蓝图 S6（数据源与 pipeline 整合）/ops 归位方向，与死代码清退解耦。
3. **S7 卡③（monte_carlo 前视修正）优先级不降**：monte_carlo 是月末注册步骤（:82），有真实消费方，前视缺陷须修而非随「死代码」降级。
4. 计划任务 4 个均健康在册（无 9009 项命中本次核查范围）。

## 四、验收情况
① 逐模块含路径、证据（命令/命中行 file:line）、判定、处置建议 ✓ ② 三分档汇总表 2/15/0 ✓ ③ 开头注明观察时点与 HEAD=77e6c0f ✓；纯静态核查（未跑 pytest、零改产码零测试）✓

## 五、遗留问题
- `gpt_task.txt`/`gpt_task2.txt` 任务文件若仍在仓库，可与 call_gpt 双子同批清退（本单未检查其存在性）；
- 强制计划任务实查仅覆盖名称含 quant/trade/stock/watchdog/backup 的任务，若存在异名任务引用其他模块，建议日间用 `Get-ScheduledTask | Export-Csv` 全量导出复核一次；
- 「15 个零引用」原始计数与本次 17 个核查对象（15+call_gpt+stall_watchdog）的差异已在本报告口径内对齐（审计 P0 行的「call_gpt/call_gpt2 等」模糊表述是差异来源）。
