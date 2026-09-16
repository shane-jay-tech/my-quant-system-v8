# my-quant-system-v8 重构蓝图 v0.1（待总指挥与用户拍板）

> 任务 20260907-180640-296f 产物。输入：refactor-architecture-audit-20260907（体检）+ refactor-risk-map-20260907（红线图）+ 三份既有审计遗留。原则：**先低风险基础设施、后中风险数据/pipeline、资金核心最后且白天双实现**；夜间 Flash 只做 R3/机械性工作。

## a) 目标架构提案

```
core/        基础设施层：config(单例) / paths(唯一路径源) / secrets(唯一入口) / calendar / llm / db
domain/      策略与资金层：signals(strategy,multi_strategy) / risk(portfolio_risk,newbie_protection,exit_advisor)
             / position(position_sizer) / trading(sim_trade) / backtest(enhanced_backtest,walk_forward,monte_carlo)
             / gates(etf_gate,alpha_gate) / feedback(strategy_feedback,evolve*)
ops/         运维层：pipeline(daily_pipeline) / fetchers(fetch_*) / schedulers / health(_self_check) / notify(bark_sender)
app/         展示层：pages 拆包（dashboard/record/report/system 各一文件）
tests/       镜像 domain 结构；characterization 测试单独目录
```
- **依赖方向规则**：app → ops → domain → core；**禁止反向与跨层跳跃**；domain 内禁止 import app/ops。
- **paths 收敛**：新增 core/paths.py 作为唯一路径源；90 个手写路径文件分批迁移到 `from core.paths import X`（机械替换，可夜间做，每批跑 smoke）。
- **config 单例**：全系统只经 core.config 读取，模块内禁止直接 json.load 配置（消除多副本）。
- **secrets 单例**：core/secrets.py 唯一入口；Bark token 轮换后清 git 历史引用（用户侧）。

## b) 阶段路线图（7 阶段）

**S1 测试补钉与钉桩（夜间 Flash 可做｜R3 为主）**
- 范围：multi_strategy.py characterization 测试（0%→钉住现行为，golden master）；R6 静态可钉项补桩；newbie_protection 最小覆盖。
- 红线：characterization 只锁现状不改动生产码。前置：无。验收：新增测试全绿、pytest 仍 ≥392。回滚：删测试文件。工作量：2 夜。

**S2 _self_check 函数化 + ops 归位（夜间 Flash｜R3）**
- 范围：_self_check.py 改 `run_all()` 入口，import 零副作用；文件迁 ops/health.py；调用点（计划任务）同步。
- 红线：R3。前置：S1。验收：self_check 结果不劣化（160 PASS/1 WARN/2 FAIL 基线）；计划任务实跑一次成功。回滚：git revert 单提交。工作量：1 夜。

**S3 call_gpt2 等死代码清退（夜间 Flash｜R3）**
- 范围：15 个零引用模块逐个人工确认 → 归档到 archive/ 或删除（call_gpt2、benchmark_comparison、factor_analysis、external_research 优先）。
- 红线：R3（确认环节人工）。前置：S1。验收：pytest/smoke 不变。回滚：归档制，移动即回滚。工作量：0.5 夜＋人工确认 30 分钟。

**S4 paths/config/secrets 三收敛（夜间分批＋白天快审｜横切 R2）**
- 范围：新建 core/paths.py、core/secrets.py；90 文件分 5–6 批机械迁移；config 多副本改为单例读。
- 红线：涉及 R2 文件的默认值语义必须逐文件 diff 快审（默认值漂移=资金风险）。前置：S1。验收：pytest 全绿＋smoke 53/53＋关键路径 grep 无手写路径残留。回滚：按批 git revert。工作量：3–4 夜＋1 次白天快审。

**S5 pages.py 拆包（夜间机械拆＋白天快审｜R3 为主，录单部分 R2）**
- 范围：app/pages.py → app/pages/{dashboard,record,report,system}.py；录单/写成交路径标注 R2 并保持原样迁移不改逻辑。
- 红线：迁移不改逻辑。前置：S4（paths）。验收：页面 smoke＋手工冒烟清单。回滚：整包 revert。工作量：2 夜＋0.5 天快审。

**S6 数据源与 pipeline 整合（白天 Pro 审｜R2）**
- 范围：fetch_* 与 data_validator、trading_calendar 收敛进 ops；pipeline 重试/降级统一；monte_carlo 消费方确认（无消费则封存并降遗留级）。
- 前置：S4。验收：数据文件 SHA 不变下的干跑对比（不打真实行情）。回滚：模块级 revert。工作量：2–3 天。

**S7 资金核心六遗留（白天 Pro+GPT 双实现，逐项独立卡｜R1）**
- 范围（每项一张卡，一项一评审一合入）：①sim_trade 成交口径统一；②max_single_position=1.0 vs 15% 裁决；③monte_carlo 前视修正；④strategy_feedback 窗口/风控回写边界；⑤walk_forward 预热复核；⑥gate 评估源新鲜度。
- 前置：S1（钉桩）+S4。验收：双实现 diff 评审＋ pytest＋回测对比报告（同数据双跑）。回滚：单卡 revert。工作量：每卡 0.5–1 天，共 4–6 天。
- 尾段：S8 覆盖率例行化（CI 化 pytest+coverage 报告，门禁覆盖率不降）与 AGENTS/CLAUDE 单源化。

## c) 遗留清单逐项去向

| 遗留项（背景③） | 去向 |
|---|---|
| sim_trade 成交口径 | S7 卡① |
| max_single_position 冲突 | S7 卡② |
| monte_carlo 前视 | S3 确认消费方 → S7 卡③ |
| strategy_feedback 边界 | S7 卡④ |
| walk_forward 预热 | S7 卡⑤ |
| gate 评估源新鲜度 | S7 卡⑥ |
| _self_check 函数化 | S2 |
| pages.py 拆包 | S5 |
| utils/paths 收敛 | S4 |
| AGENTS/CLAUDE 双份 | S8 |
| 计划任务 9009 | S2 验收环节人工核查 |
| Bark token 轮换 | 用户侧（S4 secrets 单例后更易轮换） |
| R4/R6 钉桩、覆盖率例行化 | S1（R6）＋S8（例行化；R4 动态双跑归入 S7 卡①验证方法） |

## d) 里程碑与停止条件（每阶段门禁）

1. pytest 全绿（≥392，只增不减）；2. smoke 53/53；3. _self_check 不劣化（160/1/2 基线）；4. data/ SHA-256 快照前后一致；5. 覆盖率 TOTAL 不低于 46% 且关键模块不降；6. git 历史单阶段单提交、可整段 revert。
**全局停止条件**：任一阶段门禁失败且 24h 内无法定位 → 冻结该阶段、上报总指挥；资金路径（R1）阶段必须白天有人值守，夜间班自动停。
