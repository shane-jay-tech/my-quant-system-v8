# quant data/ 运行时产物快照对账（q918-38，执行 2026-09-19 13:0x）

> 只读盘点。全程**不读任何文件正文**，只取 `os.lstat` 的 size/mtime 与目录计数——
> 含 `data/secrets.json`（只记 163 B / mtime 2026-07-11，**未打开**）。
> 零删除、零文件改动（本文件与 outbox 结果除外）。

## 一、总览

```
data/ 顶层条目 34（31 文件 + 3 子目录）
合计 117 个文件，56.41 MB
整体最新 mtime = 2026-09-19（regime_state.json，见第五节：是测试写的）
整体最旧 mtime = 2026-05-17
du -sh data → 57M
```

单文件 `history.csv` 占 **46.62 MB = 全目录 83%**；其余大头是 `cache/`（7.04 MB）。

复跑（工作目录 `D:\code\my-quant-system-v8`）：
```bash
find data -type f | wc -l                       # 117
find data -type f -printf "%s\n" | awk '{s+=$1} END{printf "%.2f MB\n", s/1048576}'
du -sh data                                      # 57M
ls -lt data | head -6
```

## 二、三个子目录

| 子目录 | 文件数 | 体积 | 最新 mtime | 最旧 mtime | 内容构成 |
|---|---:|---:|---|---|---|
| `cache/` | 25 | 7.04 MB | 2026-09-08 | 2026-08-03 | `fundamental_*` 15 个 ＋ `north_flow_*` 10 个（按日一文件） |
| `minute_kline/` | 51 | 0.77 MB | 2026-09-08 | 2026-09-08 | 50 个股票代码 CSV ＋ `_fetch_status.json` |
| `risk_config_history/` | 10 | ~1.7 KB | 2026-09-07 | 2026-08-06 | 每个 171 B 的风控配置快照 |

`minute_kline` 的 50 只与 `fetch_minute_kline.py:411 fetch_all_hs300(max_stocks=50)` 一致 ✓。

⚠ `cache/` 两条待查（本单不开正文）：
1. `north_flow_*.csv` 连续 10 天体积**完全相同**（都是 372,499 B），不像每日增量；
2. 没有任何清理逻辑（`grep` 生产码里无 `data/cache` 的删除/过期分支），按当前节奏约 0.6 MB/交易日单调增长。

## 三、顶层 31 个文件（按 mtime 新旧排序，age 以 2026-09-19 13:05 计）

| 文件 | 体积 | 最后改动 | age |
|---|---:|---|---:|
| `regime_state.json` | 211 B | 09-19 13:07 | 0d ← **测试写的，见第五节** |
| `alpha_gate_state.json` | 5,257 B | 09-18 15:37 | 0.9d |
| `stock_20260913.csv` | 431,995 B | 09-13 10:01 | 6.1d |
| `kaoyan.db` | **0 B** | 09-12 23:33 | 6.6d ← **外来物，见第四节** |
| `trading_calendar.csv` | 105,579 B | 09-09 21:00 | 9.7d |
| `hs300_index.csv` / `pick_performance.json` / `portfolio_state.json` / `evolve_daily_state.json` / `behavior_log.csv` / `newbie_status.json` / `risk_config.json` / `strategy_forward_returns.csv` / `strategy_weights.json` / `history.csv` / `minute_kline/*` | 0.00–46.62 MB | 09-08 15:3x–16:4x | 10.8–10.9d |
| `stock_20260906/07/08.csv` | 各 ~0.41 MB | 09-06～09-08 | 10.9–13.1d |
| `system_config.json` | 2,291 B | 09-02 23:50 | 16.5d |
| `cost_log.jsonl` | 14,484 B | 08-21 16:47 | 28.8d |
| `ops_analysis_20260904.md` | 4,750 B | 09-05 00:06 | 14.5d ← **data/ 里唯一被 git 跟踪的文件** |

## 四、异常陈旧项（>30 天未动，共 10 项）

```
124 天（2026-05-17，同日成批）：arena_config.json  backtest_trades.csv  bad_trades.json
                                cold_start_manifest.json  factor_weights.json  good_trades.json
115 天：etf_watchlist.json      114 天：trading_mood.csv      105 天：user_activity.json
 70 天：secrets.json（163 B，本单未打开）
```

6 个文件同停在 05-17 17:10:35，是"一次性冷启动写入后再没动过"的形态（`cold_start_manifest.json` 同批，互为佐证）。
`arena_config.json` 对应 `strategy_arena.py`——AGENTS.md 记其 v8.6 起默认关，故陈旧属预期。
唯 **`cost_log.jsonl` 28.8 天** 与「每日成本审计报告」的宣称不符（差 1 天就进本清单），留给日间对账。

**`data/kaoyan.db`（0 字节，09-12 23:33）是跨仓泄漏**：quant 全仓代码没有任何 `kaoyan` 引用
（`grep -rn kaoyan --include=*.py .` 唯一命中是 `tests/audit_test_isolation_scan.py:60` 的内联样本串），
而同名文件的真正归属地是 `D:\code\kaoyan-system\kaoyan-news\`（`config.py` / `db_utils.py`）。
⇒ 2026-09-12 深夜某次以 `cwd=D:\code\my-quant-system-v8` 跑了 kaoyan-news 的代码，
用相对路径 `data/kaoyan.db` 建连接、建了个空库（0 B = 只 connect 未写入）。
本单**不删**（零删除），登记待日间定夺。

## 五、本单最有价值的一条：测试会写生产状态文件

全量 pytest 前后对 `data/` 做 117 条 `(size, mtime)` 快照比对：

```
真实变化 1 个 / 新增 0 / 消失 0
  data\regime_state.json  (211 B, 13:00:03) -> (211 B, 13:04:53)
内容 sha1 前后同为 7ab17a5e4f —— 即：内容没变，mtime 被刷新
```

定位过程（二分法，脚本 `/tmp/bisect.py` 思路：按文件半区间跑 `pytest -q` 并比对 mtime）：

```
元凶 = tests/test_characterization_multi_strategy_main.py（单独跑 4 passed，即可复现刷新）
```

该文件 `:10` 的 docstring 明写「隔离：DATA_DIR/RESULTS_DIR/ORDERS_DIR 全部 monkeypatch 到 tmp_path；**不读写真实 data/**」，
但它只 patch 了 `ms_mod.DATA_DIR`（:29-31，`multi_strategy` 模块自己的常量），
而真正的写点在**另一个模块**：`position_sizer.py:92 os.path.join(DATA_DIR, 'regime_state.json')`。
⇒ 生产仓位模块在测试里被真实调用并按真实 `DATA_DIR` 落盘。今天写回的内容与磁盘一致所以无损，
但这是"测试可覆写生产状态文件"的通路——`ops/health.py:133` 的 `regime_state.json` 新鲜度检查和任何按 mtime 的取证都会被它污染。

**为什么哨兵没抓到**：`tests/audit_test_isolation_scan.py` 是把**源码文本片段**喂给 `tools/audit_test_isolation.audit_text`
做静态匹配（:25 甚至拿 `open(data_dir / 'regime_state.json', 'w')` 当"应当不报"的 golden 样本），
它识别字面写点，识别不了"测试经生产码间接写"。这是该审计的设计盲区，不是漏配。

建议（本单不动手，"不做顺手改动"）：把 `tests/conftest.py` 里对 `DATA_DIR` 的重定向做成**跨模块统一**
（凡生产模块有 `DATA_DIR` 常量，全部指到 tmp），并给 `test_characterization_multi_strategy_main.py`
补一条"data/ 快照 mtime 前后不变"的自证。

## 六、git 治理对账

- `.gitignore:49` = `data/` —— **整目录被忽略**，`git status --short data/` 空（116 个未跟踪文件全部被忽略，零脏项）。
- 于是 `.gitignore:2 data/secrets.json`、`:21 data/history.csv`、`:22 hs300_index.csv`、`:23 minute_kline/`、`:24 cache/`、`:31 pipeline_failed.txt`
  这 6 条具体规则**被 :49 吞并＝冗余**（无害；`secrets.json` 那条可当"哪天删了 :49 也不泄"的双保险留着）。
- 例外：**`data/ops_analysis_20260904.md` 被 git 跟踪**（提交 `32d015c feat: ops analyzer + morning task registration`）。
  在整体忽略的目录里单独跟踪一个运行产物，与 :49 的策略互相打脸——要么承认它是报告（该挪去 `reports/`），要么撤跟踪。
- `data/pipeline_failed.txt` **不存在** ⇒ 与 `daily_pipeline.py:26 FAIL_MARKER` 的失败落盘路径一致（没失败过或已被清）。

## 七、锚点漂移与参照核对

| 任务书 | 磁盘实况 |
|---|---|
| 「data/ 目录（**logs/** 归档、trading_calendar.csv 等）」 | ✗ 漂移：`data/logs/` **不存在**，data/ 下只有 `cache` / `minute_kline` / `risk_config_history`。日志在**仓库根** `logs/`（6 项，含 `morning_20260919.log`——盘前链今天有动）。`trading_calendar.csv` ✓ 在盘（105,579 B，09-09） |
| 「参照 `quant-dirty-triage-20260917.md` 已列 .coverage 等」 | ✓ 存在 `docs/insights/quant-dirty-triage-20260917.md`，:14 `?? .coverage`、:27 建议"加 .gitignore【需日间确认】或删除"；该项已由 `6164c64`（q918-27）落 `.gitignore`。该文**不含 data/ 条目**（`grep -n "data/"` 0 命中）⇒ 本单确实是补侧 |
| 产出文件名 `quant-data-snapshot-20260918.md` | 按任务书原样命名（含 0918 字样），实际执行日为 2026-09-19；不改名以免和信箱记录对不上 |

## 八、命名 vs mtime 的一处错位（读元数据即可看出）

`risk_config_history/` 里文件名的时间戳是**复制时刻**，mtime 是**被复制文件原来的写入时刻**（`shutil.copy2` 语义），
两者错开一个运行周期。例：`risk_config_20260811_170333.json` 的 mtime = 08-10 16:45:36，
而 `data/risk_config.json` 自己的 mtime（09-08 16:41:10）恰好等于最后那份快照**文件名**里的时间（`20260908_164110`）。
⇒ 按 mtime 找"最新快照"仍然正确；但拿文件名与 mtime 交叉核对会误以为少了一份，别按文件名做连续性断言。

## 九、日志侧交叉验证（防止把"data/ 冻结"误读成"流水线挂了"）

`data/` 有 11 个运行态文件停在 09-08，容易得出"流水线 10 天没跑"的错误结论。**日志不支持这个结论**：

```
logs/pipeline_20260917.log  1652 B  mtime 09-17 15:37
logs/pipeline_20260918.log  1648 B  mtime 09-18 15:37   ← 里面其实有两个 RUN START（15:30 与 15:37）
logs/morning_20260919.log    174 B  mtime 09-19 09:15   ← "[1/3] Trading day check … [SKIP] Non-trading day"
```
复跑：`grep -an "RUN START\|ALPHA-GATE" logs/pipeline_20260918.log` → 22 行文件里 2 次 RUN START，各以 3 行 ALPHA-GATE 收尾。

1. **09-19 盘前链正常跳过**：今天 09-19 是周六（09-18 日志头写 "friday"），交易日检查判非交易日直接 SKIP ⇒ 174 B 的小日志是预期行为，不是异常。
2. **日终链在跑，但当前 tier 不产出这些文件**：`pipeline_20260918.log` 头部（GBK 编码，见下条）显示 `tier=beginner`，
   并明确列出被跳过的步骤（`data_loader`、`backtest`、`factor_analysis`、`portfolio_risk`、`broker_export` 等）——
   **这些正是写 `data/history.csv`／`cache/`／`portfolio_state.json` 的那批**。
   ⇒ data/ 的 09-08 冻结与"档位过滤"方向一致，属配置驱动，而非流水线崩溃。
   要日间确认的是：beginner 档跳过全部数据生产步骤是否符合本意（本单不评判——`ALPHA-GATE` 的 paused 状态与其中任何数值均属资金/统计结论域，红线，只指出"日志里有这几行"）。
3. **交叉印证 q918-39 的方向性提醒**：`logs/pipeline_20260918.log` 按 UTF-8 解会 `UnicodeDecodeError`，按 **GBK 完整可解**
   （`python -c "open('logs/pipeline_20260918.log','rb').read().decode('gbk')"`）。
   ⇒ 定时链路下的子进程确实按本地码页出字，而 `daily_pipeline.bat` 没设 `PYTHONIOENCODING`/`chcp`（`run.bat:3-4` 才设了 UTF-8）。
   所以给捕获型调用（`auto_heal.py:59/:121/:137`、`scripts/capacity_collect.py:60`）刷 `encoding='utf-8'` 之前，
   得先把入口环境或子进程输出编码钉成 UTF-8，否则只是把崩溃换成乱码。
