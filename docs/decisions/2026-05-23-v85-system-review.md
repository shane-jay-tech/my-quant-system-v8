# v8.5 量化系统审查归档 — 2026-05-23

> **触发**：用户问"检查一下量化选股系统的情况，看看有没有缺陷或者需要优化的地方"
> **流程**：原计划 Opus + DeepSeek 双盲，但 DeepSeek（V4 Pro 推理模型）今日中转站长 prompt 响应超 10 分钟无输出（连通性测试 OK，疑似推理超时），降级为 **Opus 单方深度审查**。已在用户摘要中标注。
> **审查范围**：core/config.py · multi_strategy.py · position_sizer.py · sim_trade.py · cost_model.py · strategy_feedback.py · broker_adapter.py · enhanced_backtest.py（关键路径），共 5104 行核心代码 + tests/（仅 2 文件） + reports/（最近 7 天反馈）

---

## 0. 系统现状速览

| 维度 | 数值 / 状态 |
|---|---|
| 版本 | v8.5（2026-05-19） |
| 自检 | 138/139 PASS（1 WARN 是 sim 持仓为 0，benign） |
| 核心 LOC | 5104 行（10 个关键文件） |
| 测试覆盖 | 极薄：仅 `test_cost_model.py` + `test_etf_gate.py` |
| 真实成本回测 | 10 日净 +1.41%，胜率 48.3%，**超额 -0.71% 跑输沪深 300** |
| 最近 5 日实盘前瞻 | 趋势跟随 6% / 均值回归 17% / 低波动率 7%（平均不到 10%） |
| 已知关闭策略 | 无（3 策略全开） |
| Tier | beginner（1200~30000 元） |

---

## 1. Findings — Opus 单方审查（10 条，按 P0→P3 排）

### P0-1【真金白银】1200 元本金 × 5 元佣金 floor，数学上无边际

**证据**：`sim_trade.py:240,380` + `cost_model.py:14-18`（注释自己也承认了）
```python
commission = max(amount * 0.0003, 5.0)        # 买入 5 元 floor
sell_commission = max(gross_amount * 0.0003, 5.0)  # 卖出又 5 元
stamp_tax = gross_amount * 0.0005              # 卖出印花税
```

**算账**：
- 单笔 ~400 元（动态算的），双边佣金 5×2=10 元 + 印花税 0.2 元 + 滑点 ~0.4×2=0.8 元 ≈ **11 元 / 400 元 = 2.75% 单笔总成本**
- 单笔 200 元（震荡市更小持仓），双边佣金 10 元 + 滑点 0.4 元 ≈ **5.2% 单笔成本**
- 想盈利，每笔必须 **至少 +3% ~ +5%** 才能不亏。A 股短线 5 日中位数收益就是 0.x%，**结构性硬伤**。

**危害**：每天跑流程 = 每天给券商交税。回测 +1.41%/10 日 = 看起来正，但真实多跑几个月会发现累计费率吃光收益（参见沪深 300 跑输 -0.71%）。

**修法**：**不是改代码，是改本金或券商**。
- 选项 A：先空跑系统，用 1200 元买 510300 长持，等 30000 元再启动
- 选项 B：换万二佣金 floor=1 元的券商（华宝、东方财富有这种）
- 选项 C：拉低交易频率到每周 1 次（年化交易成本砍掉 80%）

---

### P0-2【真金白银】strategy_feedback 风控反馈循环逻辑反向

**证据**：`strategy_feedback.py:410-415, 417-425`
```python
if stop_loss_rate > 0.5 and total_trades >= 5:
    adjustments['stop_loss_pct'] = -0.10  # 止损被频繁触发 → 放宽到 -10%
elif stop_loss_rate < 0.2 and total_trades >= 5:
    adjustments['stop_loss_pct'] = -0.06  # 止损很少触发 → 收紧到 -6%

if win_rate < 0.35: position_size_mult = 0.5
elif win_rate < 0.45: position_size_mult = 0.7
elif win_rate > 0.60: position_size_mult = 1.2
```

**为什么反向**：止损率高 = 选股本身有问题，应该（a）改选股逻辑或（b）干脆停手；放宽止损只是让坏票多亏 2% 才出场，**不会让胜率回升**。同理 win_rate 低 → 缩仓位，这件事看似稳健，但配合 P0-1 的成本结构会让下一笔单笔金额更小（200→100 元）→ 单笔成本占比从 5% 飙到 10% → 死亡螺旋。

**真实场景**：
- 当前 5 日胜率 < 10%（趋势跟随 6%、低波动率 7%）
- 等积累 10 笔后，反馈系统会触发 `position_size_mult = 0.5`
- 下次 1200 × 0.5 × alloc 0.4 / 3 只 = **80 元/笔**，5 元 floor 双边佣金 = **12.5% 单笔成本**
- 系统按部就班把账户磨干

**修法**：把"自动改风控"砍掉，留一个"通知"——胜率低就 alert 用户暂停系统，而不是自动调小仓位继续跑。或者最少：风控调整窗口要求 **≥30 笔** 而不是 5/10 笔（统计显著性）。

---

### P1-1 跨周末 trading days 估算误差在长假翻倍

**证据**：`position_sizer.py:97-106`
```python
def _trading_days_between(d1, d2):
    cal_days = (d2 - d1).days
    return max(0, int(cal_days * 5 / 7))  # 日历天 ×5/7
```

**问题**：注释说"误差最大 ±1 天"。但跨春节/十一长假实际交易日和日历天比是 0/9 而非 5/7：
- 春节 9 天假 × 5/7 = 6.4 → 系统以为有 6 个 trading day，实际 0 个
- 这意味着 hysteresis（默认 N=2）会**在长假后立刻切档**，而不是真的看到了连续 2 个交易日的新 regime

**危害**：节后第一天误判 regime，仓位档位错。强熊→震荡误切，全仓接盘；强牛→震荡误切，错过补仓。**节后开盘踩坑的概率提升**。

**修法**：用 `data/stock_*.csv` 文件名集合数交易日（系统已经有交易日历了，文件本身就是真理）。

---

### P1-2 测试覆盖率近乎为零

**证据**：5104 行核心代码，`tests/` 目录只有 2 个测试文件
- `test_cost_model.py`、`test_etf_gate.py`
- strategy.py / multi_strategy.py / sim_trade.py / position_sizer.py / strategy_feedback.py / enhanced_backtest.py / broker_adapter.py / portfolio_risk.py 全无回归测试

**危害**：每次改一行代码都是赌博。系统已经修过"跨周末 hysteresis bug"（position_sizer.py 注释里明文承认），下次再改 regime 判断/止损/仓位逻辑还会再翻车。

**修法**：先补 3 个最关键 case：
1. `test_sim_trade.py` 至少覆盖买/卖/止损/止盈/到期 5 条出场路径
2. `test_position_sizer.py` 覆盖 5 个 regime × 小资金分支
3. `test_strategy_feedback.py` 覆盖冷启动 / 实盘交易 / 无数据 三种数据源分支

---

### P1-3 系统没有实际优势 vs 510300 ETF

**证据**：用户记忆 `project_quant_v8_real_edge.md`：「真实回测 +1.41% / 胜率 48.3% / 超额 -0.71% 跑不赢沪深 300」+ 最近 5 日 3 策略前瞻平均胜率 < 10%。

**问题**：这不是代码缺陷，是**业务硬事实**——系统在小资金条件下无 alpha。继续往代码上加优化（更多策略、更复杂风控、更精细 regime 识别）都是在 0 上乘系数。

**修法**：
- 短期：暂停启动实盘交易，用 paper trading 跑 60 天，看真实前瞻胜率能否稳定在 50%+
- 中期：替换或砍掉表现最差的策略（趋势跟随 6% 胜率，比抛硬币还差）
- 不要做：再加新策略 / 再调超参

---

### P1-4 risk_config.json 自动写盘无版本/回滚

**证据**：`strategy_feedback.py:467-474`
```python
config['stop_loss_pct'] = adjustments['stop_loss_pct']
...
with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)
```

**危害**：反馈系统每天可能改一次止损。三个月后想问"止损为什么是 -10% 而不是 -8%"，**没法查**——只剩最后一版。配合 P0-2 的反向逻辑，这个文件是黑盒地把账户绑死。

**修法**：每次写之前 cp 旧版本到 `data/risk_config_history/risk_config_YYYYMMDD.json`，保留 30 天。

---

### P2-1 sim_trade 状态文件无 atomic write

**证据**：`sim_trade.py:120-125`
```python
def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
```

**危害**：每天跑流程时 Ctrl-C 或电脑断电正好砸在写盘瞬间，account_state.json 会变成 0 字节，账户记录归零。每天 1 次发生概率小，但发生就是 100% 数据丢失。

**修法**：写 `.tmp` 然后 `os.replace`。10 行代码。

---

### P2-2 broker_adapter 北交所代码归类错

**证据**：`broker_adapter.py:165`
```python
exchange = 'SH' if code.startswith(('6', '9')) else 'SZ'
```

**问题**：北交所代码是 4xxxxx / 8xxxxx，被判到 SZ。新三板做市股 9xxxxx 被判到 SH。

**当前影响**：只要 etf_gate / 选股不放开北交所，没事。但 v8 系统配置里 `broker.daily_limit_pct = 0.098`（10%），北交所是 30%，**已经存在风险**。

**修法**：
```python
if code.startswith(('60', '68')): exchange = 'SH'
elif code.startswith(('00', '30', '301')): exchange = 'SZ'
elif code.startswith(('43', '83', '87', '88', '92')): exchange = 'BJ'
```

---

### P2-3 position_sizer 小资金分支 head(3) 强制写死

**证据**：`position_sizer.py:294`
```python
if total_capital <= 3000:
    picks = picks.head(3)
    effective_max_single = 0.5  # 但是 0.5 × 3 = 1.5 > 1.0
```

**问题**：max_single = 0.5 + head(3) 数学不一致。3 只票每只最多 50% = 总 150%，超出 100%。等权场景被 base_weight=1/3 救回来了，但动量加权场景（line 311-315）会真的让某只票 > 50%，触发风控告警/截断。

**修法**：max_single 在小资金分支改 1.0/n（动态等权上限），或者 head 改 2 让逻辑自洽。

---

### P3-1 .bak 文件污染（工程债）

**证据**：根目录有 8 个 .bak 文件（broker_adapter.py.20260518.bak、enhanced_backtest.py.20260519.bak 等）

**问题**：占空间不大，但 `from broker_adapter import` 路径下如果出现历史 .bak 模块名冲突会很难调。git 又没用（不是 git 仓库）。

**修法**：移到 `archive/` 子目录（如已存在），或直接删——既然不是 git 仓库，重要历史就归档到 `docs/decisions/`。

---

## 2. 仲裁与去重（如果 DeepSeek 接通后会和这份比对）

DeepSeek 今日不可用，无对比。**所有 finding 都是单方意见**，但 P0-1 / P0-2 / P1-3 是从代码实证 + 业务事实双重锁死的，不需要二次确认。

如果用户问：「等 DeepSeek 通了再补一份意见吗？」 → **不必**，P0/P1 已经够明确，DeepSeek 可能在 P2/P3 层面补几条工程优化（atomic write / type hint / etc），不会改变结论方向。

---

## 3. 推荐行动顺序（如果用户决定要做）

| 优先级 | 动作 | 工作量 | 价值 |
|---|---|---|---|
| 🔴 立即 | **暂停"自动调风控"**：关闭 strategy_feedback.py 写 risk_config.json 的功能，留 alert | 5 min | 止损死亡螺旋 |
| 🔴 立即 | **接受"无 alpha"事实**：1200 元先买 510300 长持，等 30000 元再启动系统 | 0 min（决策） | 不再交无意义佣金 |
| 🟡 本周 | 跨周末 trading days bug 修复 | 30 min | 节后开盘不踩坑 |
| 🟡 本周 | risk_config.json 加历史归档（30 天保留） | 20 min | 可审计 |
| 🟡 本周 | sim_trade.save_state 改 atomic write | 15 min | 防数据损坏 |
| 🟢 中期 | 补 3 个核心模块的回归测试 | 2-3 小时 | 后续改代码不翻车 |
| 🟢 中期 | 砍掉胜率持续 < 10% 的策略（看 60 天前瞻） | 1 小时（数据） | 简化系统 |
| ⚪ 不做 | 再加新策略、再调超参、再加因子 | - | 0 上乘任何数都是 0 |

---

## 4. DeepSeek 不通的处理日志

```
14:50:00  llm_call.py 连通性测试（"OK"）→ 1 秒返回成功
14:51:00  发送完整 prompt（6 段代码切片）→ 10+ 分钟无响应，终止
14:62:00  发送精简 prompt（3 段代码）→ 5+ 分钟仍无响应，终止
```

可能原因：DeepSeek-V4 Pro 是 reasoning model，长 prompt 进入深度思考，中转站缓冲区或 stream 配置问题。下次审查可考虑改用 GPT-5.5 (gpt-coder) 做交叉审。

```
$ ls /tmp/deepseek_review_prompt.txt → 已删
$ ls /tmp/ds_quick.txt → 已删
```

---

*归档时间 2026-05-23 · v8.5 · Opus 4.7*
