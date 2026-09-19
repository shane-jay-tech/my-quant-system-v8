# quant screen_stocks 未来函数——日间评审材料包（q918-33，只读汇编）

- 班次：`qoder-rev-20260919-1020`（倒序尾部第 51 单），执行 2026-09-19 13:4x
- **性质**：只读汇编＋一处新增取证。零改码、零改测试、零改数值、零改配置。
- **为什么不夜间落地**：修复会全面改变回测/选股数字（统计口径变更），属夜班协议红线邻域「资金与统计数值结论」，
  且材料里有一条前置问题（第六节 Q1）**至今未闭环**。本包只把决策所需事实排好，**不对"该不该修/哪个数对"表态**。
- 沿革：`docs/insights/quant-defect-test-sync-20260916.md:34` 原文
  「无。strategy_core 未来函数缺陷本体按 9/17 拍板 #6 留日间评审（非本单范围）。」——**本包即为该"留日间评审"备料**。

## 一、缺陷本体（当前磁盘定位，行号已按 09-19 复核）

`strategy.py` 里 `target_date` 这个参数的**唯一实际用途是一行打印**：

| file:line | 内容 | 与缺陷的关系 |
|---|---|---|
| `strategy.py:222` | `def screen_stocks(today_df, history_df, target_date=None, override_params=None):` | 入口 |
| `strategy.py:231-232` | `if target_date is None: target_date = history_df['日期'].max()` | 缺省＝历史最大日（不传时"碰巧"安全） |
| **`strategy.py:234`** | `print(f"[STRATEGY] Screening for date: {target_date}")` | **全函数唯一消费点＝日志** |
| `strategy.py:239-242` | `hist = history_df.copy()` → `astype`/`zfill` → `pd.to_datetime` → `sort_values(['代码','日期'])` | **没有任何按 target_date 的截断** |
| `strategy.py:257-258` | `hist_counts = hist.groupby('代码').size()`；`new_stock_codes = set(hist_counts[hist_counts < 60].index)` | 新股门按**全期**计数（应 as-of） |
| `strategy.py:244-256` | ST／市值／停牌退市过滤全部取自 `today_df`（`:236-237`） | 与 hist 窗口无关，但见第四节口径错位 |

⇒ 后段的 MA／RSI／量比／MACD 都在**未截断的 hist 子集**上算 ⇒ 传入历史日期时读到该日期之后的数据（未来函数实锤）。

**两处文档行号已漂移**（两份设计稿是 09-16/17 写的，其间 `strategy.py` 有改动；评审以本包为准）：

| 设计稿原引 | 磁盘实况（09-19） |
|---|---|
| `quant-futurefunction-design-20260917.md:19`「`:229-230` if target_date is None…」 | 现为 **:231-232**（`:229` 已是 `_vol_ratio_min` 行） |
| 同稿 `:20`「`:231` print…」 | 现为 **:234** |
| 同稿 `:21`「`:238-241` hist 构建／`sort_values`」 | 现为 **:239-242**（`sort_values` 在 **:242**） |
| 同稿 `:40`「新股门 `hist_counts < 60`（`:236` 一带）」 | 现为 **:257-258**（差 21 行） |

## 二、现有冻结断言（测试侧已把契约钉死，修复必须满足它）

`tests/test_strategy_core.py:219-235`，**`strict=True`**（一旦 XPASS 就红，不会静默烂掉）：

```python
219  @pytest.mark.xfail(
220      strict=True,
221      reason="screen_stocks 的 target_date 目前只用于日志，没有截断历史数据，存在未来函数",
222  )
223  def test_screen_stocks_does_not_read_after_target_date(monkeypatch):
224      seen_lengths = []
225      _patch_indicators_and_market(monkeypatch)
227      def record_rsi(close, period=14):
228          seen_lengths.append(len(close))
229          return pd.Series(50.0, index=close.index)
231      monkeypatch.setattr(strategy, "calc_rsi", record_rsi)
232      history = _history(periods=70)
233      target_date = history.iloc[60]["日期"]
234      strategy.screen_stocks(_today(), history, target_date=target_date)
235      assert seen_lengths == [61]        # ← as-of 契约：只准读到 target_date 当日（含）共 61 期
```

当前实测（`strict` xfail 仍在原位、没被偷偷删）：

```
$ python -m pytest tests/test_strategy_core.py -q
19 passed, 1 xfailed in 2.08s
$ python -m pytest tests/ -q
708 passed, 4 skipped, 1 xfailed in 13.08s      # 全仓唯一那条 xfail 就是它（详见 quant-xfail-census-20260918.md）
```

注意断言形状：`seen_lengths == [61]` 要求 **calc_rsi 只被调用一次且窗口 61**。
修复若变成"逐只股票多次调用"或窗口含头含尾口径不同，这条会红——评审时需明确这就是想要的契约。

## 三、已载方案（磁盘上只有一个候选，无第二方案可比）

- 主稿：`docs/insights/quant-futurefunction-design-20260917.md`（n916d-17，53 行，§三给 diff 草案）
- 交叉引用稿：`docs/insights/quant-screenstocks-futurefunc-design-20260916.md`（n916e-06，35 行）
  —— 该稿 `:4` 自己声明「本单与 n916d-17 同题，完整设计材料已落盘 …futurefunction-design-20260917.md，本报告为交叉引用＋当前时点复核」，
  其 `:14` 复核结论「与 n916d-17 复现完全一致，状态未变」——本包 09-19 复核**同样成立**（见第二节实测）。

草案（n916d-17 §三，**单点插入、不改任何指标公式/阈值/参数**），插入点按当前磁盘应为 `strategy.py:242` 之后：

```diff
     hist = hist.sort_values(['代码', '日期'])          # ← 现 :242
+    # 未来函数修复（n916d-17 草案）：历史窗口按 target_date 截断（含当日），
+    # 指标与新股门均按 as-of 口径；today_df 由调用方保证为 target_date 当日快照
+    _td = pd.to_datetime(target_date)
+    hist = hist[hist['日期'] <= _td]
```

`quant-futurefunction-design-20260917.md:35` 已注：`pd.to_datetime` 与上方 `hist['日期']` 的转换口径一致（现 `:241`）。
**除此之外仓内没有第二候选方案**（无"在指标层传窗口"或"仅回测层修"的替代稿）——评审若想要对照组，需要现场提。

## 四、本单新增取证：调用方全盘点，以及一条比"截断"更要紧的错位

生产码里 `screen_stocks` **只有两个调用方**（`grep -rn "screen_stocks(" --include=*.py` 去掉 .venv/archive/backup）：

| 调用方 | 传 target_date 吗 | 后果 |
|---|---|---|
| `multi_strategy.py:58-59`（`TrendFollowingStrategy.screen`，惰性 import） | **不传** | 走 `:231-232` 缺省＝`history_df['日期'].max()` ⇒ 多策略路径下"as-of＝最新"，**这条路径本身不吃未来函数**（但也意味着它永远只筛最新日） |
| `strategy.py:545`（`main(target_date)` 内） | 传（来自 CLI） | 见下 |

而 `strategy.main` 的数据装载与 `target_date` **是两套时间来源**：

```python
508  def main(target_date=None):
515      today_str = datetime.now().strftime('%Y%m%d')                 # ← 用"今天"，不看 target_date
516      today_file = os.path.join(DATA_DIR, f'stock_{today_str}.csv')
518      if not os.path.exists(today_file):
520          files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
524          today_file = files[0]                                     # ← 兜底＝目录里最新的快照
527      today_df = pd.read_csv(today_file, dtype={'代码': str})
545      results = screen_stocks(today_df, history_df, target_date, override_params=override_params)
...
600  if __name__ == '__main__':
601      target = sys.argv[1] if len(sys.argv) > 1 else None           # ← CLI 明摆着接受任意历史日期
602      sys.exit(main(target))
```

⇒ **`python strategy.py 2026-08-01` 这类回填/复跑用法，today_df 拿的是"今天（或目录最新）"的快照，
只有 target_date 是 8-01，而 target_date 目前只进日志（`:234`）**。
这条直接回答了 n916d-17 §四第 3 点那句「若存在 target_date 早于 today 日期的调用方…需日间确认」——
**入口是存在的（`strategy.py:600-602` 的 CLI），且它不受草案影响**：

> ⚠ 关键推论：**只补 hist 截断，修不了这个错位**。草案截的是 hist；`today_df` 仍来自 `:515-516` 的"今天"。
> 若评审目标是"任何日期都能正确复跑"，那还需要一并决定 `:515-524` 的快照选择口径（按 target_date 取 `stock_YYYYMMDD.csv`？取不到时怎么办？）。
> 若评审目标只是"每日盘后正常选股别读未来"，则现状（today_str＝今天）本就自洽，草案够用。
> ——这是两个不同的修复边界，**必须先选一个**，否则改完仍留半截。

## 五、影响面（沿用 n916d-17 §四，逐条补当前证据）

| # | 影响 | 现证据 | 状态 |
|---|---|---|---|
| 1 | 回测/选股数字全面变化（MA/RSI/量比/MACD 按截断窗口重算） | `strategy.py:239-242` 无截断属实；指标段在其后 | 【需拍板】是否接受口径切换＋重跑全部回测基线 |
| 2 | 新股门 `< 60` 由全期计数变 as-of 计数 | 现为 `:257-258` | 【需拍板】次新股判定会变向 |
| 3 | `today_df` 语义 | **本包第四节已把问题具体化**：CLI `:600-602` 提供过去日期入口，而 `:515-524` 恒取今天/最新快照 | 【需拍板】选修复边界（第四节末） |
| 4 | 需重跑的用例 | `tests/test_strategy_core.py` 全 19 例（现 1 xfailed）；`multi_strategy.py:59` 路径（其测试见 `tests/test_characterization_multi_strategy.py`）；调用 screen_stocks 的回测/流水线脚本 | 【需列全】见第六节 Q5 |
| 5 | xfail 解除条件 | 草案落地后 `:235 assert seen_lengths == [61]` 满足 ⇒ 摘掉 `:219-222` 装饰器入正测 | 可机械执行 |

## 六、评审问题清单（建议逐条签字，前两条不答不能开工）

1. **修复边界选哪个？**（A＝只修 hist 截断，承认 CLI 复跑仍不准；B＝一并规定 `main` 的快照按 target_date 装载）→ 决定第四节那条半截问题是否本轮解决。
2. **口径切换的代价是否接受？** 全部历史回测数字会变（不是 bug 修正后的"预期变化"这么轻——参数进化器 `evolve_daily_light`／反馈权重都建立在旧数字序列上，需确认是否连带重算或作废旧状态）。
3. as-of 契约的形状确认：`seen_lengths == [61]` 要求"单次调用＋含当日 61 期"（第二节），是否符合预期？
4. `< 60` 新股门改 as-of 后，是否需要同步调整阈值（**注意：阈值本身是策略参数，属红线域，需多模型评审，不能顺手改**）。
5. 需要重跑/连带的清单由谁出：`core/pipeline.py` 注册表里哪些步骤吃 screen_stocks 输出？（本包只确认了生产码内 2 个调用点，未清点流水线步骤。）
6. 是否要求"旧口径结果"留档可追（例如报告里标注 `caliber=pre-truncation`）——否则历史报告与新报告数字不可比。
7. 拍板后由谁落地、以什么验收：见第七节命令链（含"摘 xfail"这一步的明确动作）。

## 七、拍板后的验收链（照抄即可，本单未执行任何一步）

```bash
cd /d/code/my-quant-system-v8
python -m pytest tests/test_strategy_core.py -q            # 期望：20 passed, 0 xfailed（xfail 转正）
#   ↓ 同时删除 tests/test_strategy_core.py:219-222 的 @pytest.mark.xfail 装饰器（strict 留着会 XPASS 红）
python -m pytest tests/ -q                                 # 全量：0 failed；xfail 计数应 1 → 0
python -m pytest tests/ -q --cov=strategy --cov-report=term-missing   # 覆盖率不因摘桩而掉
```
（xfail 现状基线：`708 passed, 4 skipped, 1 xfailed in 13.08s`；解释器口径＝系统 python＋pytest 9.1.1，
quant 的 `.venv` 未装 pytest——见 `docs/insights/quant-xfail-census-20260918.md` 与 q918-39 报告。）

## 八、零改动证据

- 本包是 quant 仓唯一新增文件；`git diff --stat` 仅该 md 未跟踪新增（工作树里 `AGENTS.md`/`auto_heal.py`/`data_loader.py` 的改动是**别的班次的脏树**，本单未 add）。
- 未改 `strategy.py`、未改 `tests/test_strategy_core.py`、未删未改任何 xfail/skip 标记、未动任何参数值与阈值。
- 引用的两份设计稿与 sync 报告均为**只读**引用（含其行号漂移，本包第一节末已列表更正，未回头修改原文）。
