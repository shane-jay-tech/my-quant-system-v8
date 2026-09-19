# quant xfail/skip 盘点 ＋ 基线「2 xfailed」口径复核（q918-35，执行 2026-09-19）

> 红线自查：`test_strategy_core.py:219` 那条 lookahead xfail 直指"未来函数"，属资金决策数值域——
> **本单只钉桩、不修复、不改任何参数或切断逻辑**。全部结论都来自 `-rs/-rxX` 实测输出与读码，
> 未对"该不该有未来函数""哪个方案好"下判断。

## 一、当前实测（2026-09-19 13:3x，系统 python／pytest 9.1.1）

```
$ python -m pytest tests/ -q
693 passed, 4 skipped, 1 xfailed in 16.99s
```

| 类别 | 数量 | 来源 |
|---|---:|---|
| xfail | **1** | `tests/test_strategy_core.py:219` 唯一一个 `@pytest.mark.xfail(` |
| skip | **4** | 全部来自 `tests/test_conftest_frozen_clock_targets.py:41` 的参数化分支（同一条用例的 4 个参数） |

⇒ 任务书两条锚点都成立：`grep -rn xfail tests/*.py` 只有 2 行命中——`:219` 是真标记，
`test_portfolio_risk.py:203` 那行已是**注释性质的"原 xfail 转正"说明文字**（转正提交 `736a778`，n916d-16）。

## 二、xfail 清单（1 条）

| 用例 | 标记处 | reason 原文（`:219-224`） | 现状核实 | 去留建议 | 责任落点 |
|---|---|---|---|---|---|
| `test_screen_stocks_does_not_read_after_target_date` | `tests/test_strategy_core.py:219-222`（含 **`strict=True`**——一旦 XPASS 就红，不会静默烂掉） | 原文：「screen_stocks 的 target_date 目前只用于日志，没有截断历史数据，存在未来函数」 | ✓ 读码复核：`strategy.py` 里 `target_date` 参与的是取数窗口与日志，未见历史截断（本单**没去补切断**，那是决策数值域） | **保留**。它是一条"已知缺陷的可见指针"，删掉等于把未来函数问题藏回暗处 | 与 `screen_stocks` 未来函数是同题：仓内已有交叉引用（`53097e7` 存档把 `screen_stocks` 未来函数指向 n916d-17 设计稿；`69c8601` 记 n916e-05/n916d-16 一族）——**修复需走多模型评审，不属夜班权限** |

## 三、skip 清单（4 条，逐条到参数）

机制：`tests/test_conftest_frozen_clock_targets.py:36-42` 把
`FROZEN_CLOCK_TARGETS`（`tests/conftest.py:51-60`，5 个键）× `["datetime","date"]` 做笛卡尔参数化，
`:40-41` 对**该模块没登记的那个属性**主动 `pytest.skip(f"{mod_name} 未登记 {attr}")`。

| # | 参数组合 | 缺的属性 | 是否缺口 | 核实依据（读码） |
|---:|---|---|---|---|
| 1 | `bark_sender.parsers` × `date` | date | ✗ 设计内 N/A | `bark_sender/parsers.py:2` 只 `from datetime import datetime`；模块内无 `date` 名字 |
| 2 | `bark_sender.push` × `date` | date | ✗ 设计内 N/A | `bark_sender/push.py:2` 同上 |
| 3 | `multi_strategy` × `date` | date | ✗ 设计内 N/A | `multi_strategy.py:13` 导的是 `datetime, timedelta`；`:37` 那个 "date" 只是注释里的字段名 |
| 4 | `newbie_protection` × `date` | date | ✗ 设计内 N/A | `newbie_protection.py:15` 导 `datetime, timedelta` |

⇒ **4 条 skip 全是"该模块本来就不用 `date`"的正常跳过**，不是覆盖缺口、不需要处理。
唯一登记了 `date` 的是 `position_sizer`（`conftest.py:54`），也与读码一致：
只有它 `from datetime import datetime, date`（`position_sizer.py:14`）并用 `date.today()`（`:94`）。

**顺带纠正一处文档过度承诺**（只登记，未改测试）：
`test_conftest_frozen_clock_targets.py:6-7` 写「漏登记或写错名会在收集期红，而非跨日才炸」，
实际这条哨兵的用例是 `@pytest.mark.parametrize("mod_name", sorted(FROZEN_CLOCK_TARGETS))` ——
**只对"已登记的键"生成用例**。真漏登记（键根本不在表里）时不会收集、不会红，
而 `frozen_clock` 的 `_freeze`（`conftest.py:98-105`）是"遍历表内键逐个 patch"，漏掉的模块就是静默不 patch，
即 `conftest.py:55-58` 记录的那场 09-15 事故形态。⇒ 它挡得住"写错名"（键在但属性不在→第②条用例红），
挡不住"整个漏登记"。
**今天没有实例**：4 个 `frozen_clock` 消费者（`test_bark_parsers_charac.py:85`、`test_bark_push_h912_04.py:71`、
`test_characterization_multi_strategy_main.py:75/86/95/98`、`test_timefixture_characterization.py:43`）
对应的模块都已登记 ✓，所以这是潜在盲区而非现行缺陷。要堵需要一条"用 `frozen_clock` 的模块 ⊆ 登记表"的完整性断言（本单未写，见第五节）。

## 四、基线「2 xfailed」口径复核（勘误）

`D:\code\docs\insights\quant-test-baseline-20260915.md:32`（**根仓**文件）：

```
581 passed, 2 xfailed in 32.79s
```

| 项 | 09-15 快照 | 2026-09-19 实测 | 变化原因 |
|---|---|---|---|
| xfailed | 2 | **1** | 第二条（portfolio_risk 单持仓 `correlation=None` 崩溃）已由 **`736a778`**（n916d-16）修复并转正为正常断言（`tests/test_portfolio_risk.py:203` 现留一行"原 xfail 转正"说明）；不是被删，是**债已还** |
| passed | 581 | **693** | 4 天里夜班持续补测（净增 112 例）。例：本会话昨晚起的 s 系列每单 5-20 例 |
| skipped | 快照未记 | 4 | 见第三节 |

⚠ **本单没有去改那份根仓文件**：任务书 cwd 是 `D:\code\my-quant-system-v8`，而禁止事项明列
「触碰 cwd 之外的路径」——「向基线快照追加勘误段」这条与它冲突。按协议取严的一侧：
**勘误落在本仓本报告**，根仓那份留待有该 cwd 的班次贴下面这段现成文案：

> 勘误（2026-09-19，q918-35）：本文件 :32 的「581 passed, 2 xfailed」为 09-15 时点值。
> 当前实测 `python -m pytest tests/ -q` → **693 passed, 4 skipped, 1 xfailed**。
> xfail 由 2→1：`portfolio_risk` 单持仓 `correlation=None` 一条已随 `736a778`（n916d-16）转正；
> 唯一现存 xfail 是 `tests/test_strategy_core.py:219`（`screen_stocks` target_date 未来函数，故意保留为缺陷指针）。
> 4 条 skip 均为 `FROZEN_CLOCK_TARGETS` 参数化的"该模块未登记 date"N/A 跳过，非缺口。
> 详见 `my-quant-system-v8/docs/insights/quant-xfail-census-20260918.md`。

## 五、结论与建议（未执行项一律注明）

1. **xfail 维持 1 条不动**（红线：lookahead 修复属资金决策数值域，需多模型评审）。本单连"要不要修"都没表态，只登记现状与责任落点。
2. **4 条 skip 不动**，但建议在盘点表里保留"设计内 N/A"这个标注，免得下一班看到 skip 就以为是缺口去"消灭 skip"。
3. 哨兵的"漏登记"盲区（第三节末）可补一条完整性断言：扫 `tests/` 中调用 `frozen_clock` 的文件所涉及的模块名，
   断言 ⊆ `FROZEN_CLOCK_TARGETS`。属新增测试基建，**本单未写**（超 30 分钟预算，且该盲区今天无实例）。
4. 基线数字一律要带采集时间与解释器口径（本次 693/4/1，系统 python＋pytest 9.1.1；
   quant 的 `.venv` 至今没装 pytest，见同批 q918-39 报告），否则又会漂成下一单的假锚点。

## 六、复跑

```bash
cd /d/code/my-quant-system-v8
python -m pytest tests/ -q                      # 693 passed, 4 skipped, 1 xfailed
python -m pytest tests/ -q -rs   | grep -a SKIPPED   # 4 条 skip 的参数与 reason
python -m pytest tests/ -q -rxX  | grep -a XFAIL     # 1 条 xfail 与 reason
grep -rn "xfail" tests/*.py                      # 2 行：:219 真标记 ＋ portfolio_risk:203 转正说明
sed -n '51,60p' tests/conftest.py                # FROZEN_CLOCK_TARGETS 表
```
（`grep` 需要 `-a`：pytest 输出含 GBK 字节，会被判为二进制而整段跳过——本单踩过。）

## 七、本单改动

- 新增：`docs/insights/quant-xfail-census-20260918.md`（本报告；文件名按任务书字样保留 20260918，执行日 2026-09-19）
- 生产码／测试／xfail 标记／根仓基线文件：**零改动**
