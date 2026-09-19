# quant『冻结缺陷测试同步』流程固化核验（n916x-22，全仓只读清点）

**结论：全仓缺陷标记测试仅 2 处 rg 命中（xfail×1 活标记＋1 处转正注记），mark.skip/skipif/known_bug 命名均 0。唯一活标记（strategy_core 未来函数 xfail）实跑仍 xfailed＝生产未修、标记准确，无需同步；『生产已修但测试仍标缺陷』清单＝空。bark 失败 A 同族（断言过时型）已由 q916-03 同步完毕，无残留。**

## 一、缺陷标记清点（命令与数字同段）

```
$ rg -n "xfail|known_bug" tests/   → 2 文件 2 行
$ rg -n "mark\.skip|skipif" tests/ → 0 命中
$ rg -n "known_bug" tests/         → 0 命中（无 test_*_known_bug 命名）
```

| file:line | 标记 | 实跑判定 | 生产已修？ | 证据 |
|---|---|---|---|---|
| tests/test_strategy_core.py:219 | `@pytest.mark.xfail(strict=True, reason="screen_stocks 的 target_date 只用于日志，没有截断历史数据，存在未来函数")` | **xfailed（仍失败）** | ❌ 未修——标记准确，无需同步 | 本班实跑 `pytest tests/test_strategy_core.py tests/test_portfolio_risk.py -q` → `41 passed, 1 xfailed`（若已修会 XPASS 报错，strict=True 兜底）；缺陷处置在案＝9/17 晨拍板 #6「screen_stocks 未来函数留日间评审，夜间不动」 |
| tests/test_portfolio_risk.py:203 | 无活标记（docstring 注记「原 xfail 转正」） | passed | ✅ 已修且已同步 | n916d-16（单持仓 correlation=None 不再崩溃，xfail 转正）——同步动作已发生，docstring 属历史注记 |

补充清点：`pytest.skip(...)` 运行时条件跳过 5 处（test_conftest_frozen_clock_targets.py:41/:49 冻结时钟登记表、test_s4e_no_base_joins.py:81 基线收敛、test_goal_metrics.py:57/test_ops_analyzer_charac.py:64 场景命名含 skip）——**非缺陷标记**，属环境/前置条件守卫，不计入同步对象（已识别形态外的说明，非 partial 事由：其性质为守卫而非「标记已知缺陷」）。

## 二、「生产已修但测试仍标缺陷」清单

**空。** 历史同族案例已闭环：bark 失败 A（test_bark_parsers_charac 短行断言过时，生产 d913a-37 已修）已由 q916-03 同步断言为修复后行为（quant-bark-2fail-20260916.md §二）；portfolio_risk xfail 转正同毕。当前唯一 xfail 的生产缺陷（未来函数）确认未修且在评审管道中，标记与实况一致。

## 三、流程固化建议（防复发，本单不改任何测试）

同步判据（供日间形成惯例）：①修生产缺陷的 commit 必须同班改/删对应 xfail/过时断言（同 commit 同职责）；②strict=True 的 xfail 天然防「已修未同步」（XPASS 即报错）——建议新增缺陷标记一律带 strict=True；③晨报/日间把「xfailed 计数变化」纳入巡检（xfailed 减少而非 XPASS＝有人动了被测码）。

## 四、验收情况

- ✅ 清单行数＝rg 命中数（2=2，命令与数字同段）；✅ 每条附生产已修证据（实跑 xfailed＋拍板在案；hash/docstring）；✅ 零测试改动未 push。

## 遗留问题

无。strategy_core 未来函数缺陷本体按 9/17 拍板 #6 留日间评审（非本单范围）。
