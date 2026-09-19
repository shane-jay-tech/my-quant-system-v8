# quant `sim_trade.py` 写点 dry-run 设计稿（q918-22，**只设计不实现**）

- 执行：2026-09-19 14:5x（夜班 `qoder-rev-20260919-1020`）。
- ⚠ **风控域边界声明**：`sim_trade` 是模拟撮合与账户状态写入方，其产物直接参与后续风控/出场判断。
  本稿**零实现、零 py diff、不改任何数值/阈值/口径**，只回答三件事：写点在哪、该在哪拦、怎么回滚。
  落地需日间拍板（涉及账户状态与交易记录的行为面）。
- 锚点：根仓 `docs/insights/quant-write-path-matrix-20260914.md:27`
  「| sim_trade.py | 4 | 无 | **高**（写 risk_config.json 与交易记录） |」→ **写点数 4 ✓、dry-run 无 ✓，但"写 risk_config.json"这半句不成立**（见第一节纠偏）。

## 一、先纠一条会误导设计的前提

`sim_trade.py` 与 risk_config 的关系只有"读"：

| 位置 | 内容 |
|---|---|
| `sim_trade.py:120` | `RISK_CONFIG_FILE = os.path.join(DATA_DIR, 'risk_config.json')`（常量） |
| `sim_trade.py:142-171` | `load_risk_config()` —— **只读**，返回大写键字典（alert_only 时只映射 `max_hold_days`） |
| `sim_trade.py:873` / `:959` | `risk = load_risk_config()` 两处消费（lite / full 两条 main 路径） |
全文件 `grep -n "open(.*'w'\|to_csv\|json.dump\|atomic_write"` 的命中里**没有一处指向 risk_config.json**。
⇒ **真正的 `risk_config.json` 写入方是 `strategy_feedback.py:763`（`config['position_size_mult'] = ...` 后落盘），重建方是 `auto_heal.py:70-85`。**
所以任务书说的"risk_config 重建 vs 交易记录追加分开论述"，在 sim_trade 这一侧**只有后者的写点**；
前者必须另立一单（写方在 strategy_feedback，且它同时是反馈闭环的输出面，风险等级更高）。本稿第四节把这条边界写死。

## 二、四个写点（逐点 file:line ＋ 写形态 ＋ 可回滚性）

| 编号 | 函数 → 写语句 | 目标文件 | 写形态 | 失败/半写风险 | 回滚手段 |
|---|---|---|---|---|---|
| **W-S1** | `save_state()` `sim_trade.py:263`，`os.makedirs(SIM_DIR)` `:265`，`_atomic_write_json(STATE_FILE, state)` **`:267`** | `sim_results/account_state.json`（`:117`） | **原子写**（`utils.file_io.atomic_write_json`，import 于 `:260`） | 原子⇒不会半写；但**内容会被整体覆盖** | 唯一可靠手段＝写前快照 `.bak`；否则旧内容不可恢复 |
| **W-S2** | `record_trades(closed_positions)` `:577`，读旧 `:600-602`，`df_new.to_csv(TRADES_FILE, ...)` **`:604`** | `sim_results/trade_history.csv`（`:118`） | **读旧＋concat＋整体重写**（`utf-8-sig`）——**不是 append** | 重写⇒一次异常可致历史丢失；同日重跑幂等性依赖 `state['positions']` 已被移除 | 写前快照；**不能靠"截断到某行"回滚**（矩阵里"追加"的说法要按此修正） |
| **W-S3** | `update_equity_curve(state)` `:607`，`df.sort_values('日期').to_csv(EQUITY_FILE, ...)` **`:634`** | `sim_results/equity_curve.csv`（`:119`） | 同 W-S2（读旧＋合并＋重写） | 同 W-S2 | 同 W-S2 |
| **W-S4** | `generate_sim_report()` `:638`，`makedirs` `:640`，`open(report_path,'w')` **`:752-753`** | `sim_results/sim_report.md`（固定名，**每次覆盖**） | 纯派生产物（由前三者算出） | 覆盖即丢历史报告；无副作用链 | **风险最低**：可从 W-S1/S2/S3 完全重建，不必快照 |

补充事实（设计要用的约束）：
- `sim_trade.py` **当前完全没有 dry-run 概念**（`grep -n "dry" sim_trade.py` → 0 命中）。
- 入口 `main()` `:922` 按 `core.config.SIM_MODE` 分发 lite/full，**没有 argparse**；`__main__` 在 `:1040-1041`（`sys.exit(main())`，不接受 argv）。
- 流水线调用方式：`core/pipeline.py:56` 注册表项 `{"script": "sim_trade.py", ...}`，实际执行在 `core/pipeline.py:181`
  `cmd = [_python(), script_path] + step.get("args", [])`，`:186` `subprocess.run(cmd, cwd=base_dir)`（**不捕获输出、继承环境**）。
  ⇒ **流水线侧已支持 per-step `args`**，加旗标不必改流水线；不加 args 也能靠环境变量透传。

## 三、拦截点选择（与 q916-04 切片 1/2 同构，不另发明）

既有先例（`fetch_history.py:35-37`）给的契约是：
> 「网络请求路径不变；命中写点/备份副作用时短路并打印 `[DRY-RUN]`；默认行为（无旗标）**逐字节不变**。」
守卫形态是逐写点 `if DRY: print + DRY_HITS.append(id, path) else: <真写>`（见 `fetch_history.py:330-334/340-343/376-379`）。

本稿建议：

1. **拦截层＝写语句级，不用函数入口级。** 理由：W-S1~S3 三个函数都**先算了再写**，
   函数级 return 会跳过计算、从而"预演看不到将要写什么"，失去 dry-run 的价值；
   写语句级保留全部计算，只把落盘换成打印 ＋ 记账，与先例语义一致。
2. **旗标通道二选一（都保持默认行为逐字节不变）**：
   - **(a) 环境变量 `SIM_TRADE_DRY_RUN=1`**：零 CLI 改动，流水线 `subprocess.run(..., cwd=...)` 继承环境即可生效；适合"流水线级预演"。
   - **(b) argparse `--dry-run`**：与 `fetch_history.py:414` 同款，可读性好、能进 `.bat`/手工调用；
     代价是 `main()` 签名要接 argv（`:922` 无参 → 需 `main(argv=None)`），属**行为面 additive 变更**，比 (a) 大一点。
     流水线侧可立即用：`core/pipeline.py:56` 该项加 `"args": ["--dry-run"]`（`:181` 已支持）。
   - 推荐先 (a) 落地、观察一版后补 (b)，两步都能共用同一个 `DRY` 判定入口。
3. **台账命名沿用先例**：`W0/W1/…` → 本模块用 `WS1~WS4`，`DRY_HITS.append(('WS2', TRADES_FILE))`，收尾打印一行汇总
   （先例里 `DRY_HITS.clear()` 在入口做，本模块同理）。
4. **一致性对必须同拦同放**：`account_state.json`（W-S1）与 `trade_history.csv`（W-S2）/`equity_curve.csv`（W-S3）是**一对互为解释的状态**。
   实跑里只放 W-S1 而拦 W-S2，会得到"持仓已平但无成交流水"的账本；反之会得到"有流水但持仓没动"。
   ⇒ 设计要求：**四写点要么全真写、要么全短路，不存在逐点开关**（先例 fetch 系列可以逐点是因为它的写点彼此独立）。
   这条是本模块与 fetch/minute_kline 最大的差别，务必写进实现验收。
5. `is_today_trading_day()` 一类的**读**不受影响（`:932` 非交易日保护在 dry-run 下应保持原判断），
   否则预演结果与真实运行不可比。

## 四、回滚方案（按写形态分档）

| 档 | 做法 | 适用 | 说明 |
|---|---|---|---|
| R1（推荐，最小） | dry-run **不落任何文件**，只出 `[DRY-RUN] WSx -> <path> (rows=N)` 一行/x 写点 ＋ 收尾汇总 | W-S1~S4 全覆盖 | 与先例逐字对齐；因为不写，就没有"回滚"需求。这是 dry-run 的主用法 |
| R2（真跑前的保险） | 真写前对 `account_state.json` 做一次 `.bak`（`shutil.copy2`，保留 mtime） | W-S1 | 现在**完全没有**这份保险（W-S1 直接原子覆盖）；`auto_heal.recreate_default_json` 有备份逻辑可复用，但那是给 JSON 重建用的 |
| R3（流水/曲线的保险） | 真写前把 `trade_history.csv`/`equity_curve.csv` 各存 `.bak`；**注意它们是 to_csv 整体重写，没有"截断撤销"路径** | W-S2/W-S3 | 若不做 R3，一次错误的 full 跑会永久污染历史流水——这是 sim_trade 相对 fetch 系列更高的地方（fetch 是 append，可截断） |
| R4（报告） | 不需要 | W-S4 | 派生物，重跑即得 |

⚠ 备份落点要显式规定（建议同目录 `*.bak`，与 `fetch_history.py:331` 的 `HISTORY_FILE + '.bak'` 同风格），
并**一并纳入 dry-run 短路范围**——否则 dry-run 反而制造了 `.bak` 文件，正是
`quant-dryrun-fetch-history` 那一族踩过的"备份副作用"（先例契约把 W0 备份列为写点，同理）。

## 五、测试策略（实现时该配什么桩，本单不写）

- 单测只钉"契约面"，**不碰真实 `sim_results/`**：`monkeypatch` 模块 `DRY=True` ＋ 把 `STATE_FILE/TRADES_FILE/EQUITY_FILE/SIM_DIR` 指到 `tmp_path`，
  断言 ①文件不存在 ②`DRY_HITS` 恰含 4 条且 id 为 WS1~WS4 ③stdout 有 `[DRY-RUN]` 行。
- 再加一条**回归护栏**（成本极低、价值最高）：跑完整个测试会话后 `sim_results/` 的 mtime 集合不变——
  这正是今晚 q918-38 在 quant 仓查出的那类泄漏（`tests/test_characterization_multi_strategy_main.py` 会写真实 `data/regime_state.json`）。
  sim_trade 的写点更多，不能重蹈。
- ⚠ 涉及账户/盈亏数值的断言一律**不写**（红线）：桩只断"写没写、写哪儿、拦没拦"，不断"算得对不对"。

## 六、边界与非目标

1. **不实现**：本稿一行代码没写，`sim_trade.py` 未被编辑。
2. **不改数值**：不动任何撮合参数、佣金/滑点费率、止损止盈口径、仓位规则（红线域）。
3. **risk_config 拦截不在本稿**：写方是 `strategy_feedback.py:763`、重建方是 `auto_heal.py:70-85`，需另立单，
   且它的风险等级高于 sim_trade 的写点（那是反馈闭环输出面，见 q918-29 键位文档第四节：`position_size_mult` 当前根本没有消费方）。
4. **待拍板的三个开放问题**：① 旗标通道取 (a) 还是 (a)+(b)；② R2/R3 的 `.bak` 是否默认开——备份若落 `sim_results/`，**`.gitignore:54` 已整目录忽略该目录**，不会污染工作树；
   真正的代价是每天多 3 个文件与目录膨胀，不是 git 脏项；
   ③ 一致性对的"全拦全放"是否允许例外（比如只预演报告 W-S4 而真写状态——本稿建议禁止）。

## 七、复现与零改动证据

```bash
cd /d/code/my-quant-system-v8
grep -n "open(.*'w'\|open(.*'a'\|to_csv\|atomic_write\|json.dump\|shutil\.\|os.remove\|makedirs" sim_trade.py
grep -n "risk_config" sim_trade.py          # 只有 :120 常量与 :142/873/959 读取，无写入
sed -n '181,186p' core/pipeline.py           # cmd 支持 step["args"]，subprocess 不捕获输出
grep -n "DRY\b" fetch_history.py | head      # 先例契约与守卫形态
```
**零 py diff**：本单唯一新增文件是本设计稿；`git status --porcelain` 除它之外应仍只有 `?? tmp/`。
