# quant 测试基线与 PLAN.md 数字一致性复核（n915-76，只读）

- 任务：n915-76-quant-baseline-vs-plan（created 2026-09-15T23:39:01，软预算 ≤20 分钟）
- 执行：sweep-20260915-2300（GLM-5.3-Flash），2026-09-16 03:1x

## 一、collect 实跑（附命令）

```
cd D:/code/my-quant-system-v8 && python -m pytest --collect-only -q 2>&1 | tail -3
→ 592 tests collected in 2.05s
```

## 二、PLAN.md:11-13 原文（基线数字行）

> 1. 运行现有测试并记录覆盖率基线（**以最新一份基线报告为准**：`docs/insights/quant-test-baseline-<日期>.md`（根仓 docs/insights/，历史首份=quant-test-baseline-20260911.md，当时 441 collect / 439 passed / 62% 覆盖——该组数字为历史值，勿作当前断言），生成命令见下方验收命令段）。

## 三、对照表

| 数 | 历史首份（20260911） | 本次 collect 实跑 | 判定 |
|---|---:|---:|---|
| collect | 441 | **592** | 漂移 +151（9/11→9/15 各夜补测批新增：data_validator 13、stallwatchdog 5、secrets_warn 4、pedagogy 等＋9/14 夜 quant 批） |
| passed 口径 | 439（当时） | 590 passed / 2 xfailed（全量实跑，见 n915-67 前后记录） | 与 592 collect 一致（592-2 xfail） |

**判定**：PLAN 采用「最新基线报告为准」的动态口径——441 为历史快照且原文已声明「勿作当前断言」，属设计内漂移，非数字错误。建议下次基线报告刷新至 592 collect / 590 passed（coverage 数字随 915-35 复跑口径 93/94/88/88 四模块）。

## 四、声明

未改 PLAN.md；不 push；collect 无报错（未触发 partial）。

## 遗留问题

无（基线报告刷新建议留日间）。
