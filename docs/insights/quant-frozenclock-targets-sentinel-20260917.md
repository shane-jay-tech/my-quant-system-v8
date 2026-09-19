# FROZEN_CLOCK_TARGETS 键位可解析性哨兵（916p-a1-008，2026-09-17）

## 防的是什么事故

conftest.py:45-50 注释原文：「给时敏测试加了 frozen_clock，但**漏登记本表 → fixture
静默不 patch 任何东西**，测试用冻结日期拼文件名、被测代码仍取真实日期（parsers.py:128
/ push.py:53）→ 跨日必挂」（2026-09-15 bark 两失败根因，修复记录
docs/insights/quant-bark-2fail-20260916.md（量化仓））。本哨兵把「登记表三契约」变成收集期即可
红的断言：键可导入／属性存在／冻结真实生效。

## 验证（命令与数字同段）

```
$ python -m pytest tests/test_conftest_frozen_clock_targets.py -q
19 passed, 4 skipped in 1.94s      （collected 23 ≥5 达标；4 skip＝只登记 datetime
                                    未登记 date 的键对 date 参数化按设计跳过）
$ python -m pytest -q
660 passed, 4 skipped, 2 xfailed   （failed=0；641+19 与本单新增一致）
$ git diff -- tests/conftest.py → 空（夹具与登记表零改动，不回填不新增）
```

## FROZEN_CLOCK_TARGETS 逐键对照表

| 键 | 模块可导入 | 属性存在 | 冻结生效（datetime.now==固定日） |
|---|---|---|---|
| bark_sender.parsers | ✓ | datetime ✓ | ✓ |
| bark_sender.push | ✓ | datetime ✓ | ✓ |
| multi_strategy | ✓ | datetime ✓ | ✓ |
| newbie_protection | ✓ | datetime ✓ | ✓ |
| position_sizer | ✓ | datetime ✓ + date ✓ | ✓（datetime 与 date.today 双验） |

## 用例构成（collected 23）

①键可导入×5；②属性存在 datetime×5＋date×5（4 skip）；③冻结生效 datetime×5＋
position_sizer.date.today()×1；④未登记模块不受影响（trade_analyzer.datetime 仍走真实
时间且与 now 差 <5s）×1；⑤第二次 freeze 覆盖第一次×1。

## 实现注记

conftest 不能以普通模块名导入（pytest 特殊加载），哨兵用
`importlib.util.spec_from_file_location` 按路径载入取 FROZEN_CLOCK_TARGETS——
登记表改动（增删键）会被本哨兵的参数化自动跟随，无需维护第二份清单。

## 遗留问题

无。
