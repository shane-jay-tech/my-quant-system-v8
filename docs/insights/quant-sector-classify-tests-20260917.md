# sector_classifier.classify_sector 补测报告（916p-a1-004，2026-09-17）

## 验证（命令与数字同段）

```
$ python -m pytest tests/test_sector_classifier_classify.py -q
9 passed in 1.28s
$ python -m pytest -q
627 passed, 2 xfailed, 12 warnings in 11.81s   (failed=0)
$ git diff -- sector_classifier.py → 空（生产码零改动）
$ grep -c -E 'max_sector|total_capital|position_sizer|0\.30' tests/test_sector_classifier_classify.py → 0（红线自证零命中）
```

## 用例对照（9 条，≥8 达标）

| # | 断言 | 对应实现 |
|---|---|---|
| 1 | name 空/None → 其他综合 | :106 早返回 |
| 2 | 601398 工商银行 → 银行金融 | :111 银行特征 |
| 3 | 601 末字「行」→ 银行金融 | :111 `'行' == name[-1]` |
| 4 | 600 码「某某医药事业」→ 医药生物＝关键词优先于代码兜底 | :115-118 词表循环先于 :122 |
| 5 | 600/000 无关键词 → 其他综合 | :124-125 |
| 6 | 002/003 → 高端制造 | :126-127 |
| 7 | 300/301/688 → 科技TMT | :128-131 |
| 8 | 非 6 位码（'12345'/''）不抛异常有兜底 | :110 zfill＋:134 else |
| 9 | 601 无关键词→兜底银行金融；含词表「油」→食品饮料＝词表先于 601 兜底 | :115 先于 :122-123 |

## 为什么不测 apply_sector_cap 的数值分支（资金红线）

`apply_sector_cap` 与 `detect_sector_concentration` 的产出直接是仓位/上限/集中度数值，属工作区红线「资金与统计数值计算」禁域：断言其数值即等于复算并固化资金数值结论，且测试改写可能诱导后续调整生产上限。AGENTS.md 亦载明小资金账户跳过板块集中度限制——该分支的数值语义不在当前交易系统的实际约束面。本单只钉 `classify_sector` 的纯映射，零数值断言（红线自证 grep 零命中）。

## 失败处理记录（规格与实现的两处偏差，均按现状断言）

1. 词表实为 **157 键**且含高频词（「科技」「比亚迪」「油」），测试用名须避撞多关键词——初版 2 条用例因此红，已按词表现状修正用名并补第 9 条专门钉「词表先于 601 兜底」。
2. 与注释不一致处：无（classify_sector 行为与注释/任务书 ①-⑧ 全部一致）。

## 遗留问题

无。
