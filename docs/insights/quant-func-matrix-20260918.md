# quant multi_strategy 函数×测试矩阵 ＋ 评分/并列票型补测（q918-37，执行 2026-09-19）

> 红线自查：本单**不改 `multi_strategy.py` 一行**，也不写"这个评分/名次产品上对不对"的期望。
> 所有数字都是把构造输入喂进现有函数后**实测回填**（探针见第五节），属 characterization（锁现状）。
> 资金/统计结论的判断留给日间与根配置要求的多模型评审。

## 一、口径

- 函数清单：`grep -n "^class \|^    def \|^def " multi_strategy.py`（723 行，14 个可调用体）
- 直接测试：测试函数体内出现对该函数/方法的**显式调用**（不是仅构造对象）
- 断言数：对应测试函数体内 `grep -c 'assert '` 求和（口径粗，只用来分辨"薄/厚"）
- 涉及测试文件（5 个）：
  `test_characterization_multi_strategy.py`(18 例/57 断言)、`test_characterization_multi_strategy_main.py`(4/9)、
  `test_s4e_no_base_joins.py`(4/3，与本矩阵无关，扫 base 拼接)、`test_timefixture_characterization.py`(10/10)、
  **本单新增** `test_multi_strategy_score_charac.py`(13/32)

## 二、矩阵

| 函数（定义行） | 直接测试 | 间接/委托 | 断言数（存量→本单） |
|---|---|---|---|
| `BaseStrategy.__init__` :34 | 无 | 三个子类的 `super().__init__()` 全走它 | 0（子类默认值由 `test_strategy_defaults` 断） |
| `BaseStrategy.screen` :39 | **本单补 1 例**（桩 `raise`） | — | 0 → 1 |
| `BaseStrategy.score_stock` :43 | **本单补 1 例**（桩 `raise` ＋ 三子类未覆写） | — | 0 → 2 |
| `TrendFollowingStrategy.__init__` :52 | **无**（`name='趋势跟随'` 从未被断言，见第四节 F-9） | `test_screen_delegates…` 顺带构造 | 0 |
| `TrendFollowingStrategy.screen` :56 | 存量 1 例（`:349`，打假 `strategy` 模块验委托） | `main()` | 1 |
| `MeanReversionStrategy.__init__` :73 | 存量 1 例（`:96` name/weight/MCAP_MIN） | 多处 | 1 |
| `MeanReversionStrategy.screen` :78 | 存量 3 例（`:199/:220/:237`：全门槛排除、含 schema、降序） | `main()`、`_main:85` | 9 |
| `LowVolatilityStrategy.__init__` :237 | 存量 1 例（同上 `:96`） | 多处 | 1 |
| `LowVolatilityStrategy.screen` :242 | 存量 4 例（`:157/:175/:181/:188`：常量序列精确分、高波动排除、跌势排除、短历史排除） | `_main:85` | 12 |
| `StrategyVoter.__init__` :374 | **本单补 1 例**（`initial_weights` 短于策略数时 zip 静默截断） | 存量只构造不断言参数效果 | 0 → 2 |
| `StrategyVoter.vote` :381 | 存量 4 例（`TestVoterExact` 3 ＋ 全空 1）；**本单补 10 例** | `main()`、报告测试 | 10 → **37** |
| `update_strategy_weights` :457 | 存量 3 例（`:257` softmax+平滑精确值、`:275` 记录截 60、`:291` 无前向文件） | `_main`、timefixture | 10 |
| `generate_comparison_report` :527 | 存量 2 例（`:312` 结构/重叠矩阵、`:337` 空策略段） | timefixture | 9 |
| `main` :626 | 存量 4 例（`_main` 文件：无数据 fatal、最小数据正常、中低档可实例化、跨午夜不串日期） | — | 9 |
| 模块常量 `TOP_N_PER_STRATEGY/FINAL_TOP_N/WEIGHT_WINDOW/WEIGHT_SMOOTH` | 存量 `test_pins` | — | 4 |

## 三、矩阵读出来的三个"最弱"

1. **`score_stock` 这一整条是空气**（详见 F-1）——任务书要"评分带直测"，实测这里没有评分带可测。
2. `vote()` 的**并列/退化票型**全无覆盖：存量 4 例都是"分数各不相同的正常输入"，同分、零权重、同码重复、
   名字不匹配、排名列口径这五类一个都没有。本单补 10 例。
3. `TrendFollowingStrategy.__init__` 的 `name` 无人断言，而 `vote()` **把 name 当数据键用**（F-9）——最薄的一环恰好最要命。

## 四、实测发现（F-1…F-9，全部已钉进 `tests/test_multi_strategy_score_charac.py`）

| # | 现状 | 证据 |
|---|---|---|
| **F-1** | `BaseStrategy.score_stock`(:43) 只有 `raise NotImplementedError`，**三个子类一个都没覆写**，全仓**也没有任何调用方**（`grep -rn score_stock --include=*.py` 去掉 .venv 只剩：本定义 ＋ `strategy.py:154` 那个**同名但不同签名**的函数）。⇒ 任务书锚点「评分带只被间接覆盖」方向对但对象错：multi_strategy 侧的评分逻辑其实**内联在两个 screen() 里**（MeanRev :143-196 `score += 25/15/10…`、LowVol :294-305 `+= 35/28/18…`），真正的评分带单测在 `tests/test_strategy_core.py:150`，测的是 `strategy.score_stock` | 用例 `test_score_stock_is_unimplemented_stub_on_every_strategy` |
| **F-2** | **组内同分不等于同分**：三只股票 `综合评分` 全为 50，百分位被 `argsort` 摊成 **100 / 50 / 0**（:404-411 `ranks[order]=arange(1,n+1)`）。同分之间凭空拉开 100 分极差 | `test_equal_scores_inside_one_strategy_are_spread_0_to_100` |
| **F-3** | 且同分之间的先后**不是**注释承诺的"按出现顺序"：输入 600001/2/3 → 输出 **600003/2/1（相反）**。因为 :408 用 `scores.argsort()` 的默认 `quicksort`（numpy 文档明确非稳定），而 :407 注释写「用numpy argsort稳定排名（ties按出现顺序，近似处理）」——注释给了算法不提供的保证 | 同 F-2 用例的第二条断言 |
| **F-4** | 跨策略互为对方主场时 `最终得分` 相同（50.0 vs 50.0），并列先后由 `sorted()` 稳定性 ＋ `vote_map` 插入序决定＝**先被看到的代码在前**，与分数无关 | `test_cross_strategy_reversal_ties_keep_first_seen_order` |
| **F-5** | 全员权重 0 时走 :446-447 else，`最终得分` 被写成 **int `0`**（其余分支是 `round(...,1)` 的 float）⇒ 同一列 int/float 混型，且全员并列、排序退化为出现顺序 | `test_all_zero_weights_collapse_every_score_to_int_zero` |
| **F-6** | 同一策略的 df 里代码重复时不去重：`权重和` 1.0+1.0=**2.0**、`各策略排名` 被后一行覆盖（留 2 而非 1）、`最终得分` 变两次百分位的平均 50.0 | `test_duplicate_code_in_one_strategy_double_counts_weight_and_overwrites_rank` |
| **F-7** | `各策略排名` 存的是**行序**（`rank_in_strat = i + 1`，:419），百分位存的是**分序**（:404-411）⇒ df 未预先排序时两列互相矛盾（实测：满分位 100 的那只记"排名 2"）。`vote()` 隐含前置：screen() 必须已按 `综合评分` 降序（MeanRev :222 / LowVol :365 确实做了；TrendFollowing 委托 `strategy.screen_stocks`，**其排序未在本单核实**） | `test_rank_column_is_row_order_while_percentile_is_score_order` |
| **F-8** | `共识度` 分母取 `self.n_strategies`（注册数），不是本轮真出票的策略数：注册 3 个、1 个非空 → 写 **"1/3"**；空 df 与 None 都被 :399-400 `continue` 静默跳过 | `test_consensus_denominator_counts_registered_not_participating` |
| **F-9** | 策略名与 `all_results` 的 key 对不上时该策略**静默不参与**（:398 `all_results.get(strat.name)` → None → continue），结果等价于"全空"（返回 0 行 0 列），没有任何报错或警告。三个 name 是中文串且被当数据键使用 | `test_strategy_name_mismatch_silently_drops_that_strategy` |
| 附 | 全空输入返回 `pd.DataFrame()`（**0 列**，不是带表头的空表）⇒ 下游按列名取数会 `KeyError` | `test_all_strategies_empty_yields_columnless_frame` |
| 附 | `vote()` docstring 仍在宣传 v8 已删的东西：文档写「最终得分 = 百分位排名 × 共识加成」「1/3共识=0.8」，而 :439-442 注释明确「v8: 删除 consensus bonus…共识度仅作信息列」 | `test_vote_docstring_still_advertises_the_deleted_bonus`（故意钉住漂移：谁改 docstring 谁看见它） |

**F-2/F-3 要不要修是策略判断，不是本单权限**：改稳定排序（`kind='stable'`）会换出不同的决赛圈名单，
改同分并列（dense rank）会改变所有历史可比分数的百分位——两者都直接影响选股输出，
按根配置属"改 buy/sell 决策逻辑"级，必须走多模型评审。本单只把现状钉住，防止无意识漂移。

## 五、探针与复跑

```bash
# 1) 函数清单 × 桩事实
cd /d/code/my-quant-system-v8
grep -n "^class \|^    def \|^def " multi_strategy.py
grep -rn "score_stock" --include="*.py" . | grep -v "\.venv\|^\./archive\|^\./backup"
# 2) 本单全部用例
python -m pytest tests/test_multi_strategy_score_charac.py -q
# 3) 存量不退
python -m pytest tests/test_characterization_multi_strategy.py tests/test_multi_strategy_score_charac.py -q
```
同分/零权重/重复码等实测值来自一次性探针脚本（构造 `StrategyVoter` ＋ duck-typed 策略替身，
把 `vote()` 输出 dump 成 JSON 后回填断言）；探针不入库，重跑方式即上面第 2 条——用例本身就是可复跑的探针。
（⚠ 别把临时脚本放在解释器的 `sys.path[0]` 里：本单在 `%TEMP%` 放过一个 `bisect.py`，
被 `random.py` 当标准库导入并当场执行，输出混进结果。已删除。）

## 六、锚点核对

| 任务书 | 磁盘实况 |
|---|---|
| `multi_strategy.py:43 def score_stock(self, stock_hist, today_row):` | ✓ 第 43 行逐字一致（但它是 `raise` 桩，见 F-1） |
| 「grep score_stock tests/ 仅命中单策略 strategy 模块的 test」 | ✓ 精确：唯一命中 `tests/test_strategy_core.py:150-151`，测 `strategy.score_stock` |
| 「`TrendFollowingStrategy` 仅有假模块委托测（`test_characterization_multi_strategy.py:354`）」 | ✓ :349 定义该用例、:354 是 `TrendFollowingStrategy().screen(...)` 调用行 |
| 「评分带只被间接覆盖」 | ✗ 修正：multi_strategy 侧**没有评分带**，评分内联在 screen() 里；间接覆盖的说法不成立（该路径无独立函数可覆盖） |
| 完成标准「新增 4+ passed 且存量不退」 | ✓ 新增 **13 passed**，存量 18 例全绿（合跑 31 passed in 1.96s）；全量 **693 passed / 4 skipped / 1 xfailed / 0 failed** |
