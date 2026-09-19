# quant screen_stocks 未来函数——只读复跑证据包（q918-32，执行 2026-09-19 13:5x）

- **性质**：零改码、零改测试、零改数值、零新建文件（除本报告）。所有结论都是**可粘贴复跑的命令 ＋ 当场输出**。
- **与同批 q918-33 的分工**：`quant-strategycore-review-pack-20260918.md` 是"评审问题清单＋方案对照"，
  **本报告是它的证据附件**——那边提问，这边给"照做就能看见"的复跑记录。两份配对读，勿只看一份。
- 红线：未来函数修复会改回测/选股数字（资金与统计数值结论域），故本包**只做取证与复现，不表态该不该修**。

## E-0 `target_date` 在函数内的全部出现点（机器枚举，非人工 grep 印象）

对 `strategy.py` 第 222 行起、到下一个顶层 `def`（`:433 render_markdown`）之前的函数体逐行扫 `target_date`：

| 行 | 原文（节选） | 性质 |
|---|---|---|
| `strategy.py:222` | `def screen_stocks(today_df, history_df, target_date=None, override_params=None):` | 形参 |
| `strategy.py:231` | `if target_date is None:` | 缺省判定 |
| `strategy.py:232` | `target_date = history_df['日期'].max()` | 缺省赋值 |
| **`strategy.py:234`** | `print(f"[STRATEGY] Screening for date: {target_date}")` | **唯一消费点＝打印** |

⇒ 函数体 `:222-:432` 内除这 4 处外再无 `target_date` 被读；`:239-242` 的 hist 构建
（`hist = history_df.copy()` → `astype/zfill` → `hist['日期'] = pd.to_datetime(...)` → `hist.sort_values(['代码','日期'])`）**不含任何按日期的过滤**。

## E-1 复跑对照：换三个 target_date，指标层看到的窗口长度**恒等于全量 70**

方法：复用 `tests/test_strategy_core.py` 的现成夹具（`_history(periods=70)` `:10`、`_today()` `:28`、
`_patch_indicators_and_market` `:43`），把 `strategy.calc_rsi` 换成只记长度的探针，
分别取 `target_date = hist.iloc[30/60/69]['日期']` 调 `screen_stocks`。**不落任何文件、不改任何生产数据。**

```
target_date=iloc[30] (2026-01-31) -> calc_rsi 收到窗口 [70]
target_date=iloc[60] (2026-03-02) -> calc_rsi 收到窗口 [70]
target_date=iloc[69] (2026-03-11) -> calc_rsi 收到窗口 [70]
```

只有 `[STRATEGY] Screening for date: …` 那一行随入参变化，**指标输入完全不变**
⇒ "target_date 只进日志"由静态枚举（E-0）与动态复跑（E-1）两侧同时坐实。
（对照：现有 xfail 用例 `tests/test_strategy_core.py:235` 断的是 `seen_lengths == [61]`，
今天实测 `[70]` ⇒ 该断言正是"应有 as-of 行为"的冻结契约，见 E-6。）

复跑（inline，不留脚本；`python -` 走 stdin，避免在 cwd 里落文件）：
把 E-1 的方法写成 heredoc，核心 4 行是
`T._patch_indicators_and_market(mp)` → `strategy.calc_rsi = 探针` → `strategy.screen_stocks(T._today(), hist, target_date=td)` → 打印 `seen`。

## E-2 影响面①「回测/选股数字会变」——定位与验证命令

| 证据 | file:line |
|---|---|
| 缺少的截断点（草案插入处） | `strategy.py:242`（`hist = hist.sort_values(['代码', '日期'])`）之后 |
| 受影响的指标输入 | `strategy.py:239-242` 建出的 `hist`，其后按代码切片喂 MA/RSI/量比/MACD（函数体 `:222-:432`） |
| 唯一"读得到变化"的现成出口 | `strategy.py:234` 的日志行（只反映参数，不反映计算） |

验证命令（现状确认，不含任何修改）：
```bash
grep -n "target_date" strategy.py | head            # 只见 222/231/232/234
sed -n '239,242p' strategy.py                       # hist 构建无日期过滤
```
⚠ 数字会变＝需重跑全部回测基线（本包不下"该不该变"的结论）。

## E-3 影响面②「新股门由全期计数变 as-of」

```python
strategy.py:257    hist_counts = hist.groupby('代码').size()
strategy.py:258    new_stock_codes = set(hist_counts[hist_counts < 60].index)
```
⇒ 当前门看的是**整份 history 的行数**；一旦 hist 按 target_date 截断，同一只票在早日期会被判"不足 60 期＝次新"而排除，
在晚日期才放行。阈值 `60` 本身是策略参数（红线域），本包不动、不建议。

## E-4 影响面③「today_df 语义」——入口确实存在（本条是 q918-33 的新增取证，此处只给行号）

```python
strategy.py:515-516   today_str = datetime.now().strftime('%Y%m%d'); today_file = .../stock_{today_str}.csv
strategy.py:518-524   文件缺失 → sorted(glob('stock_*.csv'), reverse=True)[0]（取目录最新，与 target_date 无关）
strategy.py:527       today_df = pd.read_csv(today_file, ...)
strategy.py:545       results = screen_stocks(today_df, history_df, target_date, override_params=override_params)
strategy.py:600-602   if __name__ == '__main__': target = sys.argv[1] ...; sys.exit(main(target))
```
⇒ **CLI 接受任意历史日期，而 `today_df` 恒取"今天/最新"**：即便按草案补了 hist 截断，
`python strategy.py 2026-08-01` 这类复跑仍是"今天的快照 ＋ 昨天的 hist 窗口"混口径。
（详细推论与两个修复边界 A/B 见 review-pack 第四节，此处不重复。）
验证命令：`sed -n '508,527p;545p;600,602p' strategy.py`

## E-5 影响面④「需重跑的用例」——可执行清单（实测计数）

| 目标 | 命令 | 现状实测 |
|---|---|---|
| 直接契约 | `python -m pytest tests/test_strategy_core.py -q` | **19 passed, 1 xfailed in 2.08s** |
| 另一条不传 target_date 的生产路径 | `python -m pytest tests/test_characterization_multi_strategy.py -q` | 18 passed（委托测在 `:349`；生产侧 `multi_strategy.py:58-59` 不传 target_date） |
| 端到端风险链 | `python -m pytest tests/test_risk_consistency_end_to_end.py -q` | **5 passed** in 1.31s |
| 全仓 | `python -m pytest tests/ -q` | **708 passed, 4 skipped, 1 xfailed in 13.08s** |
| 流水线/回测脚本层 | 未清点（`core/pipeline.py` 注册表里哪些步骤吃 screen_stocks 输出） | **留白**，见遗留问题 |

## E-6 影响面⑤「xfail 解除条件」——形状与陷阱

```python
tests/test_strategy_core.py:219-222  @pytest.mark.xfail(strict=True,
        reason="screen_stocks 的 target_date 目前只用于日志，没有截断历史数据，存在未来函数")
tests/test_strategy_core.py:235      assert seen_lengths == [61]
```
1. **`strict=True` 是双刃**：修复后该用例会从 xfailed 变 XPASS，而 XPASS 在 strict 下**判为失败**
   ⇒ 修完必须同时删掉 `:219-222` 装饰器，否则全量会出现 1 个"看着像坏了"的红。
2. **断言形状是 `== [61]`（单元素列表）**：它同时要求 `calc_rsi` 在这条路径上**只被调用一次**、窗口**含当日共 61 期**。
   若修成"逐只股票分别算"或截断口径改成"不含当日"，这条会以意外方式变红——评审时应确认这就是想要的契约。
3. 复跑验证：`python -m pytest tests/test_strategy_core.py -q -rxX`（看 reason 原文与 XFAIL 行）。

## 七、锚点核对（1 处配对漂移）

| 任务书 | 磁盘实况 |
|---|---|
| `docs/insights/quant-screenstocks-futurefunc-design-20260916.md`（**commit 673b552**；git log 原文「hist 截断 diff 草案；影响面 5 条含回测口径变更；不建议夜间落地留评审」） | △ 引号里的提交信息**逐字属于 `673b552`** ✓，但那个 commit 落盘的文件是 **`quant-futurefunction-design-20260917.md`（n916d-17，53 行）**；任务书指向的 `…20260916.md` 是**另一份交叉引用稿（n916e-06）**，由 **`53097e7`** 提交。⇒ 文件与提交**配错一对**，两稿内容本身仍在盘、结论一致，不影响取证 |
| 引文「影响面 5 条」 | ✓ 实测 n916d-17 §四确实 5 条，本包 E-2…E-6 逐条对应 |
| 引文「hist 截断 diff 草案」 | ✓ 在该稿 §三；其标注插入点 `:241` 现已漂到 **`:242`**（`strategy.py` 期间有改动） |

## 八、零改动证据

```
$ git diff --stat
 AGENTS.md |  4 +++-            ← 别的班次遗留脏树，本包未 add 未改
 auto_heal.py |  2 +-
 data_loader.py | 16 ++++++--------
$ git status --short docs/insights/quant-screenstocks-evidence-20260918.md
?? docs/insights/quant-screenstocks-evidence-20260918.md   ← 本包唯一产出（未跟踪新文件，不影响 git diff）
```
⚠ 完成标准「`git diff --stat` 空」**在仓库层面不成立、在本单层面成立**：
那 3 个 M 文件是本单开工前就在的他人改动（q918-37/39 结果里也各自登记过同一批），本包一律未 add、未改；
除此之外 tracked 文件零改动。
本包未新建脚本、未落中间文件（E-1 用 stdin heredoc 跑完即散），未读未写 `data/` 任何内容
（复跑用的 history/today 均为测试夹具内存构造的合成数据）。
