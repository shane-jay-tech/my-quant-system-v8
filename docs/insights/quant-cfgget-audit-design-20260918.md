# quant `cfg_get` 静默回退审计脚本——规格设计（q918-30，只读设计，零 py 改动）

- 班次：`qoder-rev-20260919-1020`（倒序尾部第 53 单），执行 2026-09-19 14:0x
- **本单不写生产码、不写脚本、不补 key、不改任何默认值**（风控阈值属「资金与统计数值结论」红线域，只报配置面事实）。
- 缘起：根仓 `docs/insights/quant-riskconfig-key-inventory-20260916.md:22`
  「**静默回退**：`cfg_get` 模式统一兜底，不自报缺失——建议 **n916b-08** 的 audit 脚本覆盖此项。」
  落盘核查：`ls tools/` 只有 `audit_test_isolation.py`；`grep -rln "cfg_get" tools/ scripts/ ops/` → **0 命中**
  ⇒ 该 audit 脚本**从未落地**，n916b-08 在仓内只以"被引用"形式出现在夜计划与本 inventory 文档里。本文即其规格。

## 一、机制（为什么"静默"）

```python
core/config.py:258  def get(path, default=None):
core/config.py:262-266      for k in path.split('.'):
                                if isinstance(cfg, dict) and k in cfg: cfg = cfg[k]
                                else: return default        # ← 静默回退点：键缺失／节缺失／中间层不是 dict，三种情况同一个出口
core/config.py:267          return cfg
core/config.py:270-273  get_dict(section) → cfg.get(section, {})
core/config.py:179-197  _load_config(): cfg = DEFAULTS.copy(); 若 data/system_config.json 存在则 _deep_merge 覆盖（带 mtime 单例缓存）
core/config.py:28       _CONFIG_PATH = <repo>/data/system_config.json
```
⇒ **有效配置 = `core.config.DEFAULTS`（17 个顶层节）∪ `data/system_config.json`（13 个节）**，深合并；
`get()` 命中不了就返回调用点自带的默认值，**不打日志、不计数、不自报**。
另需注意：`data/risk_config.json`（顶层 6 键：`alert_only / max_hold_days / position_size_mult / stop_loss_pct / take_profit_pct / updated`）
**不走 cfg_get**，它由 `exit_advisor.load_risk_config()`（`:65`）/`effective_risk_config()`（`:44-52`）与 `auto_heal.fix_missing_risk_config()`（`:70-78`）单独读写
⇒ 审计脚本必须分清"两套配置面"，否则会把 risk_config 的键误判成 cfg_get 的缺失键（见第三节误报实验）。

## 二、实测清单（完成标准第一条）

统计口径（全部命令给出，可复跑）：

```bash
grep -rn "cfg_get" --include="*.py" . | grep -v "\.venv\|^\./archive\|^\./backup" | wc -l      # 含 import 行与定义别名，宽口径
grep -rn "cfg_get(" --include="*.py" . | grep -v "\.venv\|^\./archive\|^\./backup" | wc -l      # 130   （别名 cfg_get）
grep -rn "_cfg_get(" --include="*.py" . | grep -v "\.venv\|^\./archive\|^\./backup" | wc -l     # 12    （别名 _cfg_get）
```
别名面（`core.config.get` 被改名导入，**没有 `def cfg_get` 这个函数**，按 `def cfg_get` 搜会一无所获）：
`grep -o "get as [a-zA-Z_]*"` 统计 → **`get as cfg_get` 32 处、`get as _cfg_get` 6 处、`get as cfg` 1 处**。

按 AST 之外的保守字面量匹配（只认第一参是字符串常量的调用）：

| 指标 | 数 |
|---|---:|
| `cfg_get`/`_cfg_get` 字面量 key 调用点 | **124** |
| 覆盖的不同点分路径 | **89** |
| 其中**不在有效配置里**（⇒ 恒取调用点硬编码默认） | **25** |
| 调用时**不传 default** 的路径（⇒ 缺失即 `None`） | **0**（今天没有这类风险） |

25 条死路径按命名空间归组（这就是审计脚本该产出的样张，见第四节）：

| 命名空间 | 条数 | 具体路径 | 代表调用点 |
|---|---:|---|---|
| `risk.*` | 4 | `risk.drawdown_limit / risk.vol_target / risk.max_turnover / risk.max_pairwise_corr` | `portfolio_risk.py:27-30`（**`system_config.json` 里没有 `risk` 节，DEFAULTS 也没有；`portfolio` 节只有 3 个不相关键** ⇒ 这 4 个风控阈值当前只能靠改代码调） |
| `arena.*` | 5 | `arena.n_strategies / initial_capital / rebalance_days / top_keep / mutation_rate` | `strategy_arena.py:32-36`（AGENTS.md 记 strategy_arena 默认关，开关在 `evolve_priority.*`，与本命名空间无关） |
| `sim.*` | 3 | `sim.use_real_capital / sim.slippage / sim.daily_limit_pct` | `sim_trade.py:35 / :114 / :115`。**节存在、键不存在**（最阴的一类：`sim` 是 system_config 的 13 节之一，改文件的人以为能调）；注意同节里 `sim.initial_capital`（`app/pages.py:471`）与 `sim.manual_capital`（`:622`）是**活的**——同节半生半死 |
| `walkforward.*` | 3 | `walkforward.train_days / test_days / step_days` | `walk_forward.py:34 / :35 / :36`。同节紧邻的 `:37 use_real_cost`、`:38 simplified_cost` 却是活的 ⇒ **同一次 cfg_get 序列里混着两类**，人肉看代码完全分不出来 |
| `llm_analyst.*` | 3 | `llm_analyst.enabled / eval_horizon / max_stocks` | `llm_analyst.py:245/252` 等（AGENTS.md 把 `llm_analyst.max_stocks`（默认 3）当成本地成本闸在宣传，但它在两个配置面都不存在） |
| `montecarlo.*` | 3 | `montecarlo.n_simulations / slippage_std / start_offset_max` | `monte_carlo.py`（该文件内） |
| `factor.*` | 3 | `factor.top_n / horizons / min_days` | `factor_analysis.py:31-33` |
| `feedback.*` | 1 | `feedback.alert_only` | `strategy_feedback.py:408`（`feedback` 节存在于 DEFAULTS，键不存在） |

## 三、误报实验（规格必须写死的一条）

我第一版原型把别名 `get as cfg`（1 处）也纳入匹配，于是 `\bcfg\.get\(` 命中了
`exit_advisor.py:52  alert_only = cfg.get('alert_only', False) is True` ——
**那里的 `cfg` 是个普通 dict（risk_config 内容），不是配置模块**，被我误报成"死配置路径"。
剔除 `cfg.get(` 后 25/89 才是干净数（原型 26/90）。

⇒ 规格第 1 条硬要求：**扫描器必须用 AST ＋ 导入表**判定别名，不能靠正则猜函数名：
先收集 `from core.config import get as X` 的 X 集合（当前 = {cfg_get, _cfg_get, cfg}），
再只统计"该模块作用域内、X 的 `Name` 引用被调用且首参为 `Constant` 字符串"的调用。
本地同名变量遮蔽（如上面那个 `cfg`）由"该文件是否存在对 `cfg` 的赋值"判定并跳过（或降级为 warning）。

## 四、audit 脚本规格（交给日间落地，本单不写码）

**名称／位置**：`tools/audit_cfg_keys.py`（`tools/audit_test_isolation.py` 已有同类先例，可复用其"文本喂函数＋可单测"的结构）。

**输入**：① 全仓 `*.py`（排除 `.venv/ archive/ backup/ tmp/`，与 `pytest.ini:norecursedirs` 同口径）；
② 有效配置 = `core.config.DEFAULTS` ∪ `data/system_config.json`（深合并后取点分键集，**只取键名，不读值**）。

**四类判定**（逐条输出 `路径 | 调用点 file:line | 类别 | 建议`）：
1. `DEAD`：路径不在有效配置里 ⇒ 恒取硬编码默认（本单实测 25 条）。
2. `NODEF`：调用未传 default ⇒ 缺失即 `None`（实测 0 条，但要长期盯着）。
3. `ORPHAN`：有效配置里有、**代码从不调用**的键（本次未统计，脚本该出；`DEFAULTS` 17 节 ∪ 文件 13 节的并集减去 89 条被消费路径）。
4. `SHADOW`：同名键同时存在于 `system_config.json` 与代码内 `DEFAULTS` 且**当前生效值等于默认**（人工核对是否"改了没生效"；只报键名与是否相等，**不打印数值**，避免把风控阈值抄进日志）。

**输出与退出码**：默认人类可读表格；`--json` 供机器消费；发现 `DEAD`/`NODEF` 时 **退出码 1**（便于接流水线）。
`--only risk.,sim.,portfolio.,position.` 支持按命名空间收窄（风控优先）。

**运行时机（建议）**：先只做"报告"，不进断言——
① 手动跑；② 稳定两周后再挂进 `ops/health.py`（其 `:133` 已有一张 20 项 `data/` 文件检查表，可加一行 `Config: cfg_get key drift`）；
③ **不要**进 pytest 断言：`DEAD` 是设计选择而非 bug，一旦进断言，夜班为求绿会去"补 key"，等于无人评审地改了配置面。

**验收**：`python tools/audit_cfg_keys.py --json | python -c "import json,sys;d=json.load(sys.stdin);print(len(d['DEAD']),len(d['NODEF']))"`
期望首跑与本文第二节对齐（**25 0**）；数字变了就是配置面真变了，进晨报对账。

## 五、本单产出的边界（红线）

- 未新建脚本、未改 `core/config.py`／`portfolio_risk.py`／任何调用点的 default。
- **未打印任何配置值**（只列键名与计数）；未读未改 `data/risk_config.json` 内容值（只取顶层键名，沿用 inventory 那份"只读 key 面"的口径）。
- 上表 25 条里 `risk.*` 4 条要不要"接通"（在 DEFAULTS/文件里补 `risk` 节）＝**风控配置面变更**，必须日间拍板；
  本单只指出"这 4 个阈值当前不可经配置文件调整"这一事实，不评价阈值本身。

## 六、锚点核对

| 任务书 | 磁盘实况 |
|---|---|
| `docs/insights/quant-riskconfig-key-inventory-20260916.md:22` 引文 | ✓ 逐字命中（且该文件在**根仓** `D:\code\docs\insights\`，任务书写作相对路径易被误读成 quant 仓——quant 仓 `docs/insights/` 下无此文件） |
| 「全部 5 key 均有硬编码默认」（该文件 `:20`） | △ 口径注：`data/risk_config.json` 顶层实有 **6** 键，去掉元数据 `updated` 才是 5 ⇒ 该句成立，但下一班照 "5" 去数是错的 |
| 「n916b-08 的 audit 脚本」 | ✓ 全仓查无该脚本（`ls tools/`、`grep -rln cfg_get tools/ scripts/ ops/` 0 命中）⇒ 本文即其规格填补 |
| 完成标准「报告含 `grep -rn "cfg_get" --include="*.py"` 实测计数」 | ✓ 第二节三条命令＋宽/窄口径分列（130 / 12 / 124 字面量） |
| 完成标准「零 py diff」 | ✓ `git diff --stat` 里 py 文件仅他人遗留的 `auto_heal.py`/`data_loader.py`（本单未 add 未改）；本单唯一新增是本文档 |
