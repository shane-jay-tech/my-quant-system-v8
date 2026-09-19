# quant 流水线步数口径文档订正（917-31，真值 44）

**结论：复算真值 44 ✓（PIPELINE_STEPS len=44；daily 35／month-end 3／monday 2／friday 2／wednesday 1／thursday 1）。按 a1-016 修订草稿落地两落点（AGENTS.md:412 24步行→注册表口径 44 条目＋12 游离 key 显式点名；:348 v7 历史节标题后补 v8 指针）。12 游离 key 逐条结论＝12/12 均为「已注册运行的 daily 条目、仅链路叙述未列」（非废弃、非待接线）。git diff 仅 AGENTS.md 文档。**

## 一、复算真值（命令与输出同段）

```
$ python -c "import sys; sys.path.insert(0,'.'); from core.pipeline import PIPELINE_STEPS as P; print(len(P))"
44  ← 与 a1-016 报告真值一致
```

## 二、订正落地（逐处 file:line）

| 落点 | 原文 | 订正后 |
|---|---|---|
| AGENTS.md:412（:412-413 段） | 「24步日终流水线（0-24）：数据→…→每周任务」 | 「日终流水线：v8 起为注册表驱动（44 条目：daily 35/month-end 3/monday 2/friday 2/wednesday 1/thursday 1…）」＋12 游离 key 显式点名 |
| AGENTS.md:348（:348-349） | 「## 系统架构 v7（仅作历史参考…）」 | 节后补一行 v8 指针（防新会话误当现状） |

## 三、12 游离 key 逐条结论（12/12 齐）

归类＝**「已注册运行、仅链路叙述未列」**（非废弃非待接线）：exit_advisor、evolve_daily_light、llm_analyst、broker_export、cost_tracker、portfolio_sync、behavior_log、digest、decision_replay、goal_metrics、newbie_protection、archive——逐 key 复算均在 PIPELINE_STEPS 且 schedule=daily（脚本核验输出同段）。

## 四、验收情况

- ✅ 复算命令与 44 同段；✅ 订正处逐条 file:line（AGENTS.md:348-349/:412）；✅ 游离 key 结论 12 条齐；✅ git diff 仅 AGENTS.md 文档；不 push。

## 遗留问题

无。
