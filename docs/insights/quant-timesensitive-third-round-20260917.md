# quant 时敏测试第三轮核验（916p-a1-009，2026-09-17，零生产码改动、零测试硬化需求）

## 一、固定命令与计数（同段）

```
$ grep -rn -E 'date\.today|datetime\.now' tests/*.py | wc -l
16
```

判定表行数＝16＝命中计数 ✓（分布：test_characterization_multi_strategy_main.py 2／
test_conftest_frozen_clock_targets.py 7／test_stallwatchdog_contract.py 1／
test_strategy_feedback.py 1／test_timefixture_characterization.py 2／
test_v87_post_cleanup_regressions.py 3）。

## 二、逐条判定表（16 行）

类型列：代码＝运行时命中；注释/docstring＝无运行时风险。判定：①已冻结／②相对量或已注入无风险／③需硬化。

| # | file:line | 类型 | 命中内容摘要 | 判定 | 理由 |
|---|---|---|---|---|---|
| 1 | test_characterization_multi_strategy_main.py:37 | 代码 | `today = (today or datetime.now().strftime(...))` | ②已注入 | d914-06 后全部调用方显式传 today＋frozen_clock；默认真实日仅兼容保留、零调用方依赖（见下专项核验） |
| 2 | 同上 :53 | 代码 | `datetime.now()` 兜底 | ②已注入 | 同上 |
| 3 | test_conftest_frozen_clock_targets.py:47 | docstring | 说明文字 | 注释 | — |
| 4 | 同上 :51 | 代码 | frozen 断言 datetime.now()==固定日 | ①已冻结 | frozen_clock 覆盖（本行即验证冻结本体） |
| 5 | 同上 :55 | docstring | 说明文字 | 注释 | — |
| 6 | 同上 :59 | 代码 | position_sizer.date.today()==固定日 | ①已冻结 | 同上 |
| 7 | 同上 :68 | 代码 | trade_analyzer real now（反证） | ②相对量 | 与 datetime.now() 互为相对比较（差 <5s），两侧同源真实时钟，午夜只平移差值不变 |
| 8 | 同上 :70 | 代码 | datetime.datetime.now() 参照 | ②相对量 | 同上 |
| 9 | 同上 :79 | 代码 | frozen 断言 | ①已冻结 | frozen_clock 覆盖 |
| 10 | test_stallwatchdog_contract.py:86 | 代码 | `today=date.today().strftime(...)` | ②相对量 | 该值塞进 monkeypatch 的 `_latest_date` 桩：生产日期源被整体替换，today 变量单向自洽流动，无混合时钟窗口；午夜翻转仅平移 lag=0 语义不变 |
| 11 | test_strategy_feedback.py:218 | 代码 | `now - 31d` 构造旧 mtime | ②相对量 | 只比较 mtime 远旧程度，翻转引入秒级偏差与 31 天量级无关 |
| 12 | test_timefixture_characterization.py:6 | docstring | 说明 | 注释 | — |
| 13 | 同上 :7 | docstring | 说明 | 注释 | — |
| 14 | test_v87_post_cleanup_regressions.py:307 | 代码 | `yesterday=(now-1d)` | ②相对量 | 断言「不回退昨日文件」：production_today ≥ 测试 now−1s ＞ 测试 yesterday，任意翻转组合下 yesterday≠production_today，断言语义不变 |
| 15 | 同上 :318 | 代码 | 同上 | ②相对量 | 同上 |
| 16 | 同上 :508 | 注释 | 桩值说明 | 注释 | — |

**③需硬化＝0。**专项核验 #1/#2：`grep -n '_write_today_stock\|frozen_clock'` 显示全部调用点已按 d914-06 显式传 today＝'20260914' 并配 `frozen_clock('2026-09-14 12:00:00')`，且有专门跨午夜用例（test_write_today_stock_cross_midnight_no_date_bleed）——默认真实日分支无任何调用方依赖。

## 三、验证（命令与数字同段）

```
$ python -m pytest -q
660 passed, 4 skipped, 2 xfailed in 19.37s   （failed=0；零文件改动，与上一单基线一致）
```

本单零测试文件改动、零生产码改动（无需硬化；`git status` 仅新增本报告）。

## 四、验收对照

- ✅ 判定表 16 行＝命令计数 16，命中原文摘要逐条在表。
- ✅ ①/②/③三类齐备；③=0，#1/#2 专项核验证据（调用点 grep＋跨午夜用例行号）已列。
- ✅ 全量 failed=0（命令与数字同段）。
- ✅ 生产码/conftest 登记表零改动；不 push。
