# 量化系统冗余扫描（v8.7）

**日期**：2026-05-28
**触发**：用户问"检查一下量化系统有没有功能或者代码或者其他一切冗余的地方"
**评审方**：Claude Opus 4.7（主） + DeepSeek V4 Pro（独立审）
**模式**：双盲 → 合并 → 三档分级

---

## 用户原问

> 你检查一下量化系统有没有功能或者代码或者其他一切冗余的地方吧

---

## Opus 第一遍扫描发现

直接扫描：
- 51 个顶层 .py，加 core/、bark_sender/、app/、tests/，共 66 个 .py，~20K 行（不含 tests/archive）
- daily_pipeline 走 `core/pipeline.py:PIPELINE_STEPS`（40 步），按 tier 过滤
- archive/ 三层：202605/data（2.1MB）、cleanup_20260526/（backtest.py + morning_pipeline.bat）、scripts_oneoff/（16 个 .ps1，38KB）

发现的具体冗余：
1. `_atomic_write_json` 三处：`sim_trade.py:221` / `alpha_gate.py:105` / `strategy_feedback.py:549`（alpha_gate 多 sort_keys）
2. `get_last_trading_day` 三处完全相同副本：`sim_trade.py:97` / `position_sizer.py:23` / `broker_adapter.py:24`
3. `save_state` 三处：`sim_trade.py` / `evolve_daily_light.py` / `portfolio_manager.py`
4. `load_risk_config` 两处：`sim_trade.py:113` / `exit_advisor.py:33`（逻辑不同）
5. `sim_replay.py` 36 行截断 stub，无 `main()`，无任何 import
6. `replay_picks.py` 和 `sim_replay.py` 都自定义 `COMMISSION_RATE/STAMP_TAX_RATE/SLIPPAGE`，没用 `cost_model`
7. `temp/bark_preview.txt`（9KB）零引用
8. `archive/scripts_oneoff/` 16 个 v7 时代 .ps1（add_bom/check_bytes/fix_crlf 等），无任何引用
9. `app.py` → `app/pages.py`（1412 行单文件，12 个 render_ 函数）
10. `archive/cleanup_20260526/backtest.py`（已归档但目录还在）
11. `data/factor_weights.json` vs `data/strategy_weights.json` 命名相似
12. `check_trading_day.py`（网络）vs `get_last_trading_day`（读文件）名字混淆
13. `_self_check.py:81-87` 列出的 v75/v76 期望文件清单（含 trade_analyzer/smoke_tests/premarket_sim 这些既不在 pipeline 也不被 import 的"半孤儿"）
14. 多处 v7.5/v7.6 注释残留（"# v7.5: 统一配置中心" 等）

---

## DeepSeek V4 Pro 评审（verbatim）

### Verdict: do-not-ship

### Objections (排序：严重 → 一般)

**1. Correctness / business logic** — 多模块硬编码 cost 常量，违反 `cost_model.py` 单一真相源。
- `sim_replay.py:30` 写死 `COMMISSION_RATE=0.00025`，`cost_model` 是 `0.0003`。
- `replay_picks.py` 自定义 `COMMISSION_RATE/STAMP_TAX/SLIPPAGE`。
- 后果：同一笔交易跑不同代码路径会算出不同净 P&L，回测/回放对比不可信。
- Fix：所有模块强制 import `cost_model`；加 lint 规则（grep `COMMISSION_RATE\s*=` 出 cost_model 之外的 → 失败）或 pre-commit test。

**2. Design / maintainability** — 核心工具函数跨文件复制，实现还有 drift。
- `get_last_trading_day()` 三份相同：`sim_trade.py:97`、`position_sizer.py:23`、`broker_adapter.py:24`。
- `_atomic_write_json()` 三份：`sim_trade.py:221`、`alpha_gate.py:105`、`strategy_feedback.py:549`，alpha_gate 多 `sort_keys=True`。
- `load_risk_config()` 两份：`sim_trade.py:113`（含 alert_only 逻辑）、`exit_advisor.py:33`（裸 6 行）。
- 后果：未来在某一份上 bugfix 会漏掉其他副本，行为漂移难定位。
- Fix：抽到 `utils/file_io.py`、`utils/market_calendar.py`、`utils/risk_loader.py`，所有调用方 import 同一份。

**3. Code hygiene / cruft** — 孤儿、僵尸、截断文件。
- `sim_replay.py` 37 行 stub，定义 `REGIME_ALLOCATION`（line 29-35）但从未使用，无 `main()`、无 import。
- `temp/bark_preview.txt`（9KB）零 .py 引用。
- `archive/scripts_oneoff/` 16 个 .ps1（add_bom/fix_crlf 等）从 v7 编码清理时代遗留，已不再调用。
- 后果：增加认知负担、有误执行风险、说明 repo 没在主动维护。
- Fix：删 `temp/bark_preview.txt` 和 v7 archive 脚本（或外移到真归档）；`sim_replay.py` 要么补完逻辑要么删掉，留就加 TODO 注释。

### Smaller nits

- `app/pages.py` 1412 行单文件含 12 个顶层 `render_*` 函数无内部 import — 拆子模块。
- `integrate_knowledge.py` 反复把同一知识块 append 到 CLAUDE.md，导致 15+ 重复条目（"反反爬实战笔记" 在 CLAUDE.md 里出现 15 次以上）— 加去重。
- `REGIME_ALLOCATION`（在 `cost_model.py:47` 叫 `REGIME_ALLOC`）在三处定义、值不一致 — 集中到 cost_model 或专门 config。
- `smoke_tests.py` 不在 `PIPELINE_STEPS`，仅 `_self_check.py` 用作 import 检查 — 集成进来或写清职责。
- `data/strategy_weights.json` 和 `data/factor_weights.json` 关注点不同但都裸放 data/ 没 README — 加说明。

### What's actually good

- `sim_trade.py` 正确从 `cost_model` import `COMMISSION_RATE/COMMISSION_MIN/STAMP_TAX_RATE`，是其他模块该学的样板。
- `init_account()` v8.7 把 sim 初始资金和 `real_trades.csv` 净投入同步，让 paper return 贴近真实——避免了通常的 paper-vs-real 漂移，是个有想法的设计。

---

## Opus 仲裁：合并三档清单

### 🔴 必修（保留即损害正确性）

**A1. `sim_replay.py` 是截断 stub，cost 常量还和 cost_model 不一致**
- 路径：`sim_replay.py`（36 行 / 1136 字节）
- 问题：定义 `COMMISSION_RATE=0.00025` / `STAMP_TAX_RATE=0.0005`，前者比 `cost_model.COMMISSION_RATE=0.0003` 小 17%；定义 `REGIME_ALLOCATION` 全 1.0（不分档），与 `position_sizer` 当前 v8.7 分档（0.80/0.60/0.40/0.20/0）冲突；没有 main()，没有任何调用，**就是个未完成的半成品**
- 动作：直接删（用户回放需求由 `replay_picks.py` 满足）
- 风险：极低，无任何 import 引用

**A2. `replay_picks.py` 自定义 cost 常量绕过 cost_model**
- 路径：`replay_picks.py`
- 问题：违反 v8 Phase 1.2 设计（`cost_model.py` 是单一真相源），未来 cost_model 改了它不跟，回放结果和实盘不一致
- 动作：改成 `from cost_model import COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE, SLIP_LARGE/SLIP_MID/SLIP_SMALL`，删本地常量
- 风险：需要重跑一次回放对比新旧曲线，但本来就该是这个值

**A3. `integrate_knowledge.py` 没去重，CLAUDE.md 里"反反爬实战笔记"出现 15+ 次**
- 路径：`integrate_knowledge.py` + 后果文件 `D:\code\CLAUDE.md`
- 问题：每次跑都把同一块知识 append 进 CLAUDE.md，CLAUDE.md 现在已经被污染了 15+ 重复块；这会污染我每次 session 的 system prompt，浪费 token、影响判断
- 动作：(a) 加幂等检查（按 `> 来源：` 行去重）；(b) 一次性清理 CLAUDE.md 把重复块合并
- 风险：清理 CLAUDE.md 是用户配置文件，**改之前必须先 backup**

### 🟡 建议修（不改不影响功能，但维护性显著提升）

**B1. 三处重复的 `_atomic_write_json` + 三处重复的 `get_last_trading_day` + 两处 `load_risk_config`**
- 动作：建 `utils/io_utils.py` 放 atomic write，`utils/calendar.py` 放 get_last_trading_day，sim_trade/exit_advisor 共享 `load_risk_config`
- 收益：未来改逻辑只改一处，避免 alpha_gate 的 `sort_keys=True` 那种偷偷 drift
- 风险：动了核心 utility 必须跑全部 107 个测试 + sim_trade 烟雾测试

**B2. `REGIME_ALLOC`（cost_model）/ `REGIME_ALLOCATION`（position_sizer）两个名字一份概念**
- 动作：cost_model 是源头，position_sizer 改成 import，删本地副本；但保留小资金 override 逻辑
- 收益：将来改 regime 系数只改一处
- 风险：低，但要确认 cost_model 的 REGIME_ALLOC 值和 position_sizer 当前一致（已确认，都是 0.80/0.60/0.40/0.20/0.00）

**B3. 半孤儿文件 `sim_replay.py`（必修后不再有）、`smoke_tests.py`、`premarket_sim.py`**
- 动作：sim_replay 删；smoke_tests 集成到 weekly_health_check.bat；premarket_sim 集成到 morning pipeline 或删（v8 已没 morning bat）
- 收益：清掉"_self_check 列着但 pipeline 没跑"的半挂机模块

**B4. `temp/bark_preview.txt`（9KB）+ `archive/scripts_oneoff/` 16 个 .ps1（38KB）+ `archive/cleanup_20260526/`（20KB）**
- 动作：全删；要存历史就搬到 D:/ 外面或开个独立 git tag
- 收益：清掉 ~70KB 噪音，repo 看起来不像废墟
- 风险：这些都已 archive，删了不影响运行

**B5. `app/pages.py` 1412 行单文件 12 个 render_ 函数**
- 动作：拆成 `app/pages/` 子包，一个 render_ 一文件
- 收益：以后改某一页不用滚 1412 行
- 风险：纯重构，但要回归测试 Streamlit UI

### 🟢 可不修（列出但暂不动）

**C1. `_self_check.py:81-87` 的 v75/v76 期望文件清单**
- 这是历史扫描器的"应当存在"白名单，硬编码每个版本应该有哪些文件；删了没收益，留着确实"啰嗦"但不害事

**C2. 各处 `# v7.5/v7.6:` 注释残留**
- 是设计意图的演化注脚，保留有助于读懂为什么这么写；统一删掉反而损失可读性

**C3. `data/factor_weights.json` vs `data/strategy_weights.json`**
- 名字相似但职责不同（一个是因子 IC 权重、一个是 3 策略加权投票权重），改名要追到所有 reader；先加个 `data/README.md` 说明就够

**C4. `check_trading_day.py` vs 各处 `get_last_trading_day`**
- 一个是网络判断今天是不是交易日、一个是从最新 stock 文件名取最近交易日；功能不同。不重命名，靠 docstring 区分

**C5. `app.py`（47 行瘦壳）保留即可**
- 已经是入口模式正确写法，不算冗余

---

## 推荐执行顺序（如果用户决定动手）

1. **先 backup**：`git status`（如果有 git）+ 拷 CLAUDE.md → CLAUDE.md.bak.20260528
2. **🔴 必修一次性做完**：
   - 删 sim_replay.py（1 行命令）
   - replay_picks.py 改 cost 常量（5 分钟）
   - integrate_knowledge.py 加幂等（10 分钟） + 清理 CLAUDE.md 重复块（手动审一遍 5 分钟）
3. 跑 `pytest`（应该 107/107）+ `python _self_check.py`（应该 142/142）
4. **🟡 建议修按需**：B1 utility 抽取 + B2 REGIME 合并是一组，B3/B4/B5 可独立
5. **🟢 可不修**：暂不动

预估：必修 30 分钟 + 测试 5 分钟 = 35 分钟
建议修 B1+B2：1.5 小时；B3+B4：30 分钟；B5：2 小时（拆包+回归）
