# 2026-08-24 — 流水线日志 append-only + 多段终态分类（Round 8）

## 元数据

- 任务类型：自动化日志可靠性修复
- 难度评分：影响面 1 + 风险领域 0 + 歧义度 0 + 新颖度 1 + 不可逆性 0 + 长程影响 1 = **3 → L2**
- 模型：Flash quick 评审；Pro 本会话实施与复核。health_check 全 OK。
- override：0
- 测试：pytest **301 passed / 2 xfailed**（基线 297，净增 4）；smoke 48/48；py_compile 通过
- API：本轮 Flash 0.061 元；今日累计 6.96 元 < 20 元

## 证据链（systematic-debugging）

- 症状：goal_metrics 把 `pipeline_20260818/19`、`20260723` 等计为 failed，但计划任务 15:37 应有当日运行。
- 证据：计划任务 LastRunTime 每天 15:37；而 20260818 日志首行时间 18:07、20260723 首行 20:19，且无终态（部分带 ^C）——说明每日日志被后来手动重跑用 `>` 截断覆盖，定时运行记录丢失。
- 根因：`daily_pipeline.bat` 用 `>` 截断写单一 LOGFILE；`goal_metrics` 按整份文本顺序取第一个终态标记，append 后无法区分多段运行。
- Canonical owner：daily_pipeline.bat 的日志重定向 + goal_metrics 分类器。
- PatchShape：无新增 fallback/分支扩散；Decision=fix owner。

## Change Necessity

- User-visible need：定时运行与手动重跑都必须留痕，流水线成功率不能被截断日志污染。
- No-change option：无（继续截断会持续丢审计证据）。
- Why code change：append 与按 RUN START 分段是日志可靠性的最小修复。
- Minimum boundary：bat 一处 `>` → `>>` 并加 RUN START 标记；goal_metrics 加分段解析与 interrupted 类别。
- Decision: code-change

## Flash 评审（verbatim）

同意。append + 按最后终态分类能解决“截断导致手动重跑覆盖定时日志”的污染问题，`^C` 单独设类也合理。

补充风险：**append 后缺少“运行段起始标记”，导致“最后一次终态”不一定等于“最后一次运行的终态”**。  
例如：定时运行成功写了 `Pipeline complete`；之后手动重跑刚启动就被强杀，且没有留下 `^C`。日志最后位置是手动运行的中间输出，没有任何新终态，按“终态位置最大者”会命中前面的 `Pipeline complete`，从而误判为 `success`，而不是 `in_progress` / `interrupted`。

建议在 `daily_pipeline.bat` 每次运行开头输出类似 `=== RUN START [timestamp] ===` 的段分隔符；`_classify_log` 先定位最后一段，再在该段内查 SKIP / FATAL / complete / PAUSED / `^C`，否则 append 后多段日志仍然无法可靠切分。


采纳其补充风险：append 后必须按最后一段运行分类，否则“上一段 success + 新段无终态”会被误判 success。已实现 `_last_run_segment()`：无 RUN START 的旧日志整段解析；有新标记的只解析最后一段。

## 修复

- `daily_pipeline.bat`：`call :main >> LOGFILE`（append-only），每次运行在段首输出 `=== RUN START [date time] ===`。
- `goal_metrics.py`：`_last_run_segment` + 按最后终态标记分类；新增 `interrupted`（^C，不计 attempts 分母）；报告显示 interrupted。
- `tests/test_goal_metrics.py`：+4 项（last failure wins / last success wins / interrupted / 空尾段不复用前段终态）。

## 实跑证据

`python goal_metrics.py`：
- 旧口径：attempts=16 success=10 failed=6 → 62.5%
- 新口径：attempts=14 success=10 failed=4 skipped=4 **interrupted=2** → **71.43%**（2 个 ^C 不再计失败，4 个失败里 2 个是已修 summary 契约 bug 的历史日志，2 个是无终态截断）

## Retirement

- 旧截断重定向已移除；旧日志（无 RUN START）仍被兼容解析，无需迁移。

## 风险

1. 截断发生在新代码部署前的那 2 份无终态日志仍计 failed，是保守口径（无法证明是用户打断还是进程死亡）。
2. append 会让日志文件长期增大；archive 策略未来需按大小/天数轮转。
3. RUN START 标记依赖 bat 调用路径；若用户直接 `python daily_pipeline.py`（不走 bat），日志不会带分段标记，分类器回退整段逻辑仍可用。
