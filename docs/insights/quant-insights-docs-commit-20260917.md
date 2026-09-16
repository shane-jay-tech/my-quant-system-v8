# 20 份未入库 insights＋tests-isolation-norm.md 成批入库（916p-a1-013，2026-09-17）

## 一、清单复现（命令与输出同段）

`git status --porcelain docs/`＝**21 行**（20 份 insights＋1 份 tests-isolation-norm.md；任务书快照的「20 份已在库」实测现为 **30 tracked**——本夜 a1-001~012 各单报告已先行入库 10 份，快照漂移如实注记）。清单见提交 7921692 提交体（21 files changed, 634 insertions）。

## 二、入库前逐份核验（21/21 全过非空＋UTF-8；引用抽查结果分三档）

| 抽查结果 | 份数 | 明细 |
|---|---|---|
| 引用全可解析 | 14 | 如 empty-remark-nan-repro-20260914.md、quant-r6-pin-20260913.md（上游材料两份）等 |
| 引用省略目录前缀、全仓可解析 | 5 | paths.py→core/paths.py（×2 文档）、test_sim_trade.py→tests/、test_position_sizer.py→tests/、pages.py→app/、test_timefixture_characterization.py→tests/ |
| **无法解析（只记录不改）** | 2 | ①quant-coverage-caliber-20260914.md 引用 `ingest-english2-staging.py` 全仓无此文件（疑 kaoyan 仓脚本或已删临时件）；②quant-ops-analyzer-cov-20260913.md 引用 `test_ops_analyzer_characterization.py`——盘内实际名 `test_ops_analyzer_charac.py`（命名漂移） |

每份字符计数（非空证据）已由核验脚本输出留档（zcode-bridge/tmp/verify_docs_a1_013.py，最小 379 字符/最大 3595 字符，全部 UTF-8 可读）。

## 三、提交与复验（命令与数字同段）

```
$ git show --stat --oneline HEAD → 21 files changed, 634 insertions(+)
$ git status --porcelain docs/ | wc -l → 0
$ git ls-files docs/insights | wc -l → 50（任务书预期 40＋本夜 10 份漂移＝50，一致）
$ python -m pytest -q → 660 passed, 4 skipped, 2 xfailed（提交前 660 passed——文档提交零影响）
$ git status -sb → ## main...origin/main [ahead 16]（未 push）
```

## 四、验收对照

- ✅ 提交后 status docs/＝0。- ✅ ls-files 计数同段（漂移已注记）。- ✅ show --stat＝21 项。- ✅ pytest 前后零变化 failed=0。- ✅ 不 push；精确路径无 -A/-u/.。
