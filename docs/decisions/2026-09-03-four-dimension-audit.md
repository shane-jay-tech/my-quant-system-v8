# 2026-09-03 · 从里到外四维全面审查（产品/功能/架构运维/安全质量）+ 修复 + 提交

> 用户要求："不光是代码层面，还有功能、架构、产品等方方面面，从里到外、从上到下全面检查 bug 和系统优化。"
> 执行方式：4 个只读审查员并行（产品体验 / 功能正确性 / 架构·数据·运维 / 安全·质量），
> 总指挥汇总定级，只修「证据充分且安全可修」项；**决策核心 bug 全部列为待多模型评审**。
> 审计全程先做 12 个生产状态文件 SHA-256 快照，结束后逐字节比对——**零污染**（上轮事故的教训）。

## 1. 审查结果总览（完整清单见四个审查报告，此处是已确认要点）

| 层面 | 结论 | 关键问题数 |
|---|---|---|
| 产品/体验 | 理念正确但新用户旅程多处断线：晨间流水线空转、无学习中心、回测页 KPI 全 0、历史订单当"今日动作" | B4 / M8 / m8 |
| 功能正确性 | 核心链路可跑，但交易日节假日误判、模拟同收盘成交 vs 回测次日开盘、反馈短窗口冒充 3/5/10 日、Walk-Forward 无预热、Alpha/ETF 门吃旧评估 | B1 / M9 |
| 架构/运维 | DAG 清晰；两套持仓真相源分叉、日计划任务 LastResult=9009 且 8/23 后无日志、UI"全流程"是四步演示、非原子写、月末任务重复 | B2 / M11 |
| 安全/质量 | **真实 Bark token 仍硬编码在 `_self_check.py` 并已进 Git 历史**；HTTP 明文推送；webhook URL 可能落日志；.env 文档谎称 | B1 / M3 |

## 2. 本轮已修复（全部有回归测试锁定）

**安全（最高优先）**
- `_self_check.py` 删除真实 token 字面量，改为"32 位十六进制形状检测"；`test_v87_hybrid_layer.py` 同步改为正则扫描 5 个推送/自检源码文件。
- `bark_sender/channels.py` 失败日志只留异常类名，webhook URL 不再可能进日志。
- `auto_heal.py` `shell=True` 命令拼接 → `shell=False` 参数列表。
- 遗留：**token 已在 Git 历史中（cc993fb 及更早），请用户轮换 Bark token**；HTTP Bark 端点是第三方服务，未擅改（会破坏推送），已在文档提示。

**产品/功能**
- 晨间流水线 `morning_pipeline.bat` 去掉 dry-run 空转：真跑 `premarket_sim.py` + 真推送，日志改追加。
- 回测页解析重写为按列名解析（旧正则在当前格式下全部 0）；`parse_honest_eval_md` 入 loaders 并测。
- 「今日动作」订单日期 ≠ 今天 → 醒目警示，防止按历史订单操作。
- 今日选股页置顶 digest 四段简报；侧栏"数据更新"改显示真实行情文件 mtime。
- 模拟账户重置：必须勾选确认 + 重置前自动备份 `backup_YYYYMMDD_HHMMSS/`（含账户/曲线/历史）。
- 心理助手：10 万分母 → 权益分母；"现金<1万" → "现金占权益比例<30%"。
- `send_to_bark`：推送失败 → 退出码 1；`.newbie_mode` 存在时自动走新手指令卡；parsers 章节名兼容实际输出。
- 流水线控制页「一键全流程」→ 改名「快速演示四步」，不再冒充完整 DAG（真全流程用 daily_pipeline）。
- `daily_pipeline.py` fatal/异常时写 `data/pipeline_failed.txt` 并尝试推送失败通知。

**架构/数据/运维**
- 剩余 7 处状态 JSON 全部改 `utils.file_io.atomic_write_json`（evolve/regime/orders/factor/weights/exit/llm_analyst）。
- `goal_metrics` 移到 `self_check` 之后（读当日自检）；相关测试同步更新。
- `auto_heal.recreate_default_json` 覆盖前自动备份（防新手段位被重置）；`core/config` 首生成配置原子写。
- `_self_check` 补盲区：morning/run/start-bg/launcher/AGENTS/conftest 文件存在性、v8.7 五模块 import、alpha_gate/strategy_weights/cost_log 数据存在性、morning 任务 WARN（未注册会天天提示）、趋势对比正则修复。
- bat 全部去硬编码路径（`%~dp0`）、日志统一追加；`daily_pipeline.bat` 15:37 口径；`.gitattributes` 统一行尾。
- `core/config` DEFAULTS 止损止盈对齐 20%/10 天（旧 30%/30 天）；佣金文档 0.025%→0.03%。
- 文档：pick_tracker→track_performance、70 项→147 项、任务时间、requirements 上界与 v8.6 头、premarket 输出路径。

## 3. 明确不修（决策核心，待多模型评审——已写入遗留清单）

1. check_trading_day 周一节假日误判（需交易日历/第二数据源）
2. sim_trade 当日收盘成交 vs 回测次日开盘口径
3. etf/alpha gate 优先旧 honest_evaluation
4. strategy_feedback 短窗口冒充 3/5/10 日、无平仓时重置 risk_config
5. walk_forward 测试窗口无预热；monte_carlo 用最新快照做历史截面
6. strategy_arena 共用 equity_curve
7. position_sizer 选股报告回退解析失效、max_single_position=1.0 vs 文档 15%
8. portfolio_state vs sim 账户两套真相源、sync_daily 同日重复 +1
9. behavior_log 收盘后补录不回写；evolve_daily_light 安全锁形同虚设
10. Windows 计划任务 LastResult=9009 / 8-23 后无日志（需人工在任务计划器核查"起始于"目录）
11. `_self_check` import 即执行整份自检、pages.py 拆包、utils/paths 全量收敛、AGENTS/CLAUDE 双份维护

## 4. 验证（全部实跑）

| 检查 | 结果 |
|---|---|
| pytest | **371 passed / 2 xfailed / 0 failed**（新增 6 个审查修复用例；全部改动文件 py_compile 通过） |
| smoke_tests | **53/53 OK** |
| _self_check | **162 项：158 PASS / 2 WARN / 2 FAIL**——147→162 覆盖增加；2 FAIL 仍是改动前数据新鲜度（stock 85.8h / exit 295h）；1 WARN=history 12 天；新增 WARN=QuantMorningPipeline 未注册（按设计暴露） |
| 生产数据零污染 | 审计前后 12 个状态文件 SHA-256 逐字节一致 |
| API 成本 | 0 元（全程离线） |

## 5. 用户下一步
1. 在 Bark 服务端**轮换 token**（旧 token 已进 Git 历史），更新 `data/secrets.json`。
2. 注册晨间任务：`schtasks /create /tn QuantMorningPipeline /tr "D:\code\my-quant-system-v8\morning_pipeline.bat" /sc DAILY /st 09:15 /f`（自检会持续 WARN 直到注册）。
3. 在 Windows 任务计划器里打开 QuantDailyPipeline_v5 → 检查"操作/起始于"，确保 `daily_pipeline.bat` 能被启动（LastResult 9009 的历史原因）。
4. 决策核心 11 项遗留按优先级走多模型评审。
