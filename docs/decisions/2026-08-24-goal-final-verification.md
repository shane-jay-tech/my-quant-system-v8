# 2026-08-24 — GOAL 最终验收（六层证据合成）

## Goal Closure

- Goal status: **done**（在「无证据不落地」约束下完成全部可落地项；未落地项均有负向证据决策）
- Success evidence:
  1. 本金全链路 2400：core.config / system_config / sim / position_sizer / cost_model / 报告文案统一；账户基线 2400.00（round 1 前已完成并复核）。
  2. Alpha Gate 每日真实计数：core.pipeline 先交易日后计数；连续 5 个交易日跑输沪深300 自动暂停并提示 510300/510310 ETF；当前 excess=-0.09% severe、counter=2、paused=false（达到 5 会触发）。
  3. 测试全绿：pytest **308 passed / 2 xfailed**、smoke **48/48**、self_check **142/142**、AppTest **0 异常**。
- Stop state: 预算 7.26 元 < 20 元；未触发多模型 CRITICAL 停站；触及 buy/sell/风控/仓位/数据源处均走 L3 多模型评审。
- Non-goals respected: 未改评分公式、止损止盈参数、回测核心、数据源；弱信号门槛因证据不足**未硬上**（负向决策归档）。

## 六层证据

### 数据层
- fetch_stock_data 双源重试/降级既有；fetch_history 东方财富快路径（2026-08-15）；data_validator 行数/非零价/成交量/lag 校验。
- 数据完整率新口径：最新 data_health 快照 99.95% OK；逐交易日 coverage **100%**（20260817..21 全覆盖）。
- self_check K 线新鲜度改交易日口径，周一不再误报（142/142）。

### 策略层
- Alpha Gate 交易日计数 + pipeline 先交易日后 gate（round 1-2）。
- 强熊空仓：position_sizer 小资金模式强熊 alloc=0，summary 契约完整，流水线不再 FATAL（round 7）。
- 弱信号不买：340 评分/320 前向收益审查显示评分分桶非单调、共识 319/320=1/3，**证据不足不落地**（round 5）；继续由 Alpha Gate/强熊/成本门槛保护。
- 每笔订单成本门槛：cost.order_gate_max_pct=2.5%，position_sizer 第一道 + sim_trade 第二道，fallback 也过门槛（round 4）。

### 风控层
- 风控默认值统一 sim.*：auto_heal 重建、exit_advisor 回退、position_sizer ATR 回退、strategy 文案全部同源 -8%/+20%/10 天（round 3）。
- 端到端一致性：alert_only true/false 下 position_sizer→sim_trade→exit_advisor stop/take/hold 一致；强熊空仓；position_sizer 预算读 sim 账户基线；sim 基线跟随 real_trades 净投入（round 10）。
- 仓位计划预留佣金：2400/3×8 旧出 3 笔只能成交 2 笔，新出 2 笔（占用 1610、剩余 790），模拟与实盘口径一致（round 10）。

### 成本层
- cost_model 单一真相源（0.03% + 5 元 floor + 0.05% 印花 + 分档滑点）。
- Bark 摩擦成本附录逐笔套 floor（旧附录从不显示/低估）（round 2）。
- 每笔订单携带 往返成本/往返成本率/预计佣金/预计总成本；报告用真实口径。

### 自动化层
- pipeline 注册表新增 goal_metrics；非交易日干净跳过 rc=0；日志 append-only + RUN START 分段 + interrupted 单独统计（round 6-8）。
- goal_metrics 每日快照：流水线成功率 71.43%（10 success / 4 failed / 4 weekend skip / 2 interrupted）；失败已归因修复 summary 契约。
- self_check/auto_heal/推送/日志既有链路保持；`run_all(only=['goal_metrics'])` 集成 rc=0。

### 体验层
- 仪表盘 AppTest 0 异常，实测渲染 **1.18s**（round 11）。
- 推送/报告风控文案与系统真实配置一致，不再出现 +15%/5-10天/-5% 等互相打架的旧文案（round 2-3）。

## 验收指标快照（2026-08-24 02:56）

- 测试通过率：pytest 308/2xf；self_check 142/142=100%；smoke 48/48。
- 流水线成功率：71.43%（DEGRADED；成功 10、失败 4、周末 skip 4、用户中断 2 不计分母）。
- 数据完整率：99.95%（快照 OK）+ 100%（最近 5 交易日覆盖）。
- 历史绩效（2026-08-21 报告）：回测 10 日净收益 +1.16%、胜率 48.9%、超额 vs HS300 -0.09%；模拟账户累计 -16.19%、胜率 33.3%、最大回撤 -68.93%、累计佣金 135 元（最低佣金多付 130.37 元）。
- 预算：API 累计 7.26 元 < 20 元。

## 诚实结论

- 历史绩效仍然不好：超额 -0.09%、模拟账户亏损、回撤大。本轮目标不是“把历史亏损改成盈利”，而是**在 2400 元/5 元最低佣金约束下让系统机制更可能赚钱**：Alpha Gate 会在连续跑输 5 个交易日时暂停选股并建议改持 ETF；强熊空仓；高成本订单被门槛拦截；仓位计划保证可执行；报告/推送与真实口径一致。
- 弱信号不买是唯一明确未落地项，证据已存档；未来积累 ≥60 交易日/1800 样本后可重新校准。

## Residual risks

1. Alpha Gate 触发前仍可能继续跑输（阈值 5 天是目标设定，非盈利保证）。
2. 历史 sim 最大回撤 -68.93%，组合风控 Pro 级未启用（beginner 档）。
3. fetch_history 两次历史无终态无法归因；step 超时未加。
4. 缺少外部交易日历，数据覆盖的极端缺失日不可本地发现。
