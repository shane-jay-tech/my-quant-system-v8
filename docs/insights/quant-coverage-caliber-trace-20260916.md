# quant coverage 口径待拍板项逐条对照（q916-02，2026-09-16，零计算转录）

- 上游：d914-15 权威稿 `my-quant-system-v8/docs/insights/quant-coverage-caliber-20260914.md（量化仓）` §三；p913-48 核记 `zcode-bridge/done/p913-48-quant-coverage-caliber-unify.result.md`；q914-35 复跑 `docs/insights/quant-coverage-recheck-20260914.md（量化仓）` §一/§二；拍板材料 `docs/decisions/2026-09-15-material-quant-coverage-caliber.md`。
- 本单约定：下表所有数字均为**原文转录**（含「转引」标记与出处），无任何新算出的百分比或门槛值。

## 一、四项对照表

| # | 主张（原文转录） | 出处 file:节 | 当前状态 | 复跑命令 |
|---|---|---|---|---|
| 1 | 「统一口径选 A 还是 C：A（双主包 84%）可作单一数字入 baseline；选 C 则继续逐批定点（无单一数字）」；拍板材料建议默认 **A** | `my-quant-system-v8/docs/insights/quant-coverage-caliber-20260914.md（量化仓）` §三 第 1 条；`docs/decisions/2026-09-15-material-quant-coverage-caliber.md` §第 1 项 | **待拍板**。A 口径已两次独立复跑（84%→82%，差异归因见 q914-35 §二），但用户未裁定 | `python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov-report=term` |
| 2 | 「baseline 文件机制：恢复 `quant-test-baseline-<日期>.md` 惯例并重算首份（内容=A 口径全量 term 输出），还是改为 PLAN.md 指向 git 内固定 commit」；拍板材料建议默认 **按日期快照+A 口径** | 同上 §三 第 2 条；`docs/decisions/2026-09-15-material-quant-coverage-caliber.md` §第 2 项 | **待拍板**。在盘已有两份快照（20260911、20260913）但口径不一（转引：62% 与 55%，见拍板材料 §第 2 项「现状」） | `dir docs\insights\quant-test-baseline-*.md`（或 `ls docs/insights/quant-test-baseline-*`） |
| 3 | 「scripts/ 是否纳入：纳入则 84% 会被摊薄（分母变大）」；拍板材料建议默认 **本次先不纳入** | 同上 §三 第 3 条；`docs/decisions/2026-09-15-material-quant-coverage-caliber.md` §第 3 项 | **待拍板**。现状 scripts/ 与 tests/ 均不在统计范围（d914-15 §一） | `python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov=scripts --cov-report=term` |
| 4 | 「门槛线：是否设 TOTAL 不低于 N% 的防回退线（如 82%）」；拍板材料建议默认 **82%**，并提示「9/15 复跑正好顶着线，若不想被打扰可降到 80%」 | 同上 §三 第 4 条；`docs/decisions/2026-09-15-material-quant-coverage-caliber.md` §第 4 项 | **待拍板**。目前无任何门槛线，覆盖率回落无告警（拍板材料 §第 4 项「现状」） | 同第 1 项命令（线值本身无命令，验证=对照 TOTAL 列） |

## 二、各项目前缺的决策输入

1. **口径选定**：缺用户拍板本身（A 或 C）。材料侧输入已齐（两轮复跑、影响面对照）。
2. **baseline 机制**：缺用户拍板（①日期快照 vs ②git commit 钉死）。附带缺口——两份在盘快照口径不一，若选①需注明「重算首份时统一用 A 口径」。
3. **scripts/ 纳入**：缺用户拍板（纳入/不纳入）。材料建议不纳入＋另开评估单，该评估单**尚未建**。
4. **门槛线**：缺用户在 82% / 80% / 不设 三者中选一；材料已给出「顶着线会误报」的提醒，无其他缺口。

## 三、转录与锚点漂移披露（非计算）

- p913-48 结果称权威稿在 `docs/insights/quant-coverage-caliber-20260914.md（量化仓）`（根仓路径）——**该路径不存在**，实际在 `my-quant-system-v8/docs/insights/quant-coverage-caliber-20260914.md（量化仓）`。引用时以仓内路径为准。
- d914-15 §一「仓内无 pytest.ini」表述已过期：p913-40 已落地 pytest.ini（无 --cov addopts，行为零影响，见 p913-48 结果「漂移披露」节）。
- q914-35 §二 的涨跌判定（↑/↓2/↓3 及归因）为该报告原文结论，本单只转录不改判。

## 四、自证：产物内百分号全部为转引

```
$ rg -n '%' docs/insights/quant-coverage-caliber-trace-20260916.md（量化仓，自指）
10:| 1 | 「统一口径选 A 还是 C：A（双主包 84%）…（表行，转引自 d914-15 §三.1 与拍板材料 §第 1 项）
11:| 2 | …（转引：62% 与 55%…（表行，转引自拍板材料 §第 2 项「现状」）
12:| 3 | 「scripts/ 是否纳入：纳入则 84%…（表行，转引自 d914-15 §三.3）
13:| 4 | …（如 82%）…82%…80%…（表行，转引自 d914-15 §三.4 与拍板材料 §第 4 项）
20:4. **门槛线**：缺用户在 82% / 80% / 不设 三者中选一…（转引拍板材料选项）
31:$ rg -n '%' …（本自证命令自身）
```

逐行核对：命中 6 行，全部为带出处标记的原文转录或自证命令本身，**新算命中 0 行**。

- 禁止事项核对：未重算覆盖率、未裁定门槛常量、未改 CI 配置、未 push。
