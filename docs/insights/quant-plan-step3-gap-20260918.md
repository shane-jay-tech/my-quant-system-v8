# quant PLAN.md 步骤3（多模型流程）留痕核对（q918-24，只读检索）

- 执行：2026-09-19 14:3x（夜班 `qoder-rev-20260919-1020`）。**零代码 diff、零文档改动**（PLAN.md 一字未动，只给建议文案）。
- 锚点：`PLAN.md:13` 原文「3. 通过项目多模型入口让 GPT 提出补测方案、DeepSeek 独立复核。」✓ 逐字命中。
- 结论先给：**步骤 3 自计划锁定以来只有 1 行留痕，且那 1 行是"降级说明"而不是"执行记录"；
  但真正的问题不是"没做"，而是 PLAN.md 的步骤 3 与 2026-09-13 之后的阵容/流程已经对不上**（角色写反、留痕位置未定义）。

## 一、检索命令与命中计数

```bash
cd /d/code/my-quant-system-v8
for kw in 多模型 GPT DeepSeek 双实现 独立复核 评审官 第二方案 Opus; do
  printf "%-8s 本仓 %s 根仓 %s\n" "$kw" \
    "$(grep -rl "$kw" docs/insights/*.md 2>/dev/null | wc -l)" \
    "$(cd /d/code && grep -rl "$kw" docs/insights/*.md 2>/dev/null | wc -l)"
done
```

| 关键词 | 本仓命中文件数 | 根仓命中文件数 |
|---|---:|---:|
| 多模型 | 6 | 2 |
| GPT | 5 | 4 |
| DeepSeek | 2 | 4 |
| 双实现 | 3 | 2 |
| 独立复核 | 1 | 3 |
| 评审官 | 1 | 0 |
| 第二方案 | 1 | 0 |
| Opus | 0 | 0 |

⚠ **命中≠留痕**。逐行读完 24 处命中后分类：
- **本仓 6 个"多模型"文件里，4 个是今晚我自己写的报告**（`quant-func-matrix` / `quant-kb-drift-check` / `quant-xfail-census` / `quant-strategycore-review-pack`），
  用法一律是「这事**需**多模型评审 ⇒ 留给日间」——即"引用规则把活儿推出去"，不是"执行了步骤3"。
- 唯一把步骤 3 当**核对对象**的文档只有 1 份：`docs/insights/quant-coverage-plan-closure-audit-20260905.md:12`
  （`grep -rl "步骤3\|步骤 3" docs/insights/*.md PLAN*.md` → 全仓仅此 1 文件）。
- `评审官/第二方案` 各 1 处，出自 `quant-worktree-diff-attribution-20260917.md:58`，内容是**阵容变更说明**（评审官＝711ev 中转 GPT-5.6；09-13 起 v4-pro/百炼/kimi/claude/vision/万象退役），也不是执行留痕。
- `Opus` 全仓 **0 命中** ⇒ 09-13 定稿的"L4/L5 第二独立评审"角色在 quant 仓文档里没有任何落地痕迹。

## 二、六步骤留痕对照（含 09-05 那次盘点的结论是否仍成立）

| PLAN 步骤 | 留痕载体（file:line） | 现状核对（2026-09-19） |
|---|---|---|
| 1 覆盖率基线 | 根仓 `docs/insights/quant-test-baseline-20260911/20260913/20260915.md`；`PLAN.md:11` 已改为"以最新一份为准" | ✓ 有连续三份。**但口径与 PLAN 不符**：`PLAN.md` 步骤1 写「口径=branch」，而定版基线 `:18` 的命令是 `python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov-report=term`，输出列是 `Stmts/Miss/Cover` ⇒ **语句覆盖率，且只测 2 个包**。branch 口径从未按 PLAN 测过 |
| 2 风险排序＋人工核对关键分支 | `docs/design/decision-core-spec.md`（11453 B，mtime 09-05 01:33），R1–R15 每条带 文件:行号 | ✓ 成立（09-05 盘点判"已落地（决策核心范围）"，今天复核文件仍在、内容未回退） |
| **3 多模型提方案＋独立复核** | **`PLAN-REVIEW-LOG.md:12`（全仓唯一一处）**：「规格偏差：多模型中转因环境缺少三模型变量而不可用，按 AGENTS.md 例外降级单模型。」 | ✗ **该文件仅 13 行，且自 `befbad4` 之后无任何提交**（`git log --oneline --all -- PLAN-REVIEW-LOG.md` → 1 条）。09-05 盘点当时就判"部分落地（例外降级）"，**14 天后仍是同一行**，没有第二条记录。降级理由（缺三模型变量）在 09-13 阵容定稿后已不再成立，但没人回来更新这条 |
| 4 只在 tests/ 与测试配置/归档文档新增 | `bd61004`（test: characterization R1/R7/R8）、`340bb59`（stale/fallback 红线），二者 `--stat` 仅 tests/ | ✓ 成立；今晚夜班 50+ 单同样全部精确路径提交，未碰生产（本仓各单 result 均有 `git show --stat` 留痕） |
| 5 写完立即单跑、失败≤5 轮 | 过程性条款；载体是各报告里的"单跑命令＋数字" | △ **无法静态核验**（09-05 同样判"无法静态核验"）。今晚形态有改善：几乎每单 result 都写了单跑命令与轮次，但没有汇总台账，PLAN 也没规定留痕位置 |
| 6 全量测试＋分支覆盖率＋工作区污染 | 全量：今晚每单跑（714 passed/4 skipped/3 xfailed/0 failed）；污染：`quant-dirty-triage-20260917.md`＋本批 q918-26/25 已把 M/?? 清零（现仅剩 `?? tmp/`） | △ 全量与污染 ✓；**分支覆盖率 ✗ 从未按 PLAN 口径产出**（同步骤1）。`coverage run --branch --source=.` 这条 PLAN.md 验收命令里的命令，在 09-05 之后无产物；`.coverage` 还被 q918-27 加进了 `.gitignore`（正确做法，但意味着产物不入库＝不可事后核验） |

**09-05 那份盘点的 4 条结论，今天复核：步骤1 由"部分落地"升级为"有连续快照但口径不符"；步骤3 原地未动；验收3（覆盖率提升）现在可判了但判的是语句覆盖率，不是 PLAN 要的分支。**

## 三、附带查到的一个仓库级陷阱（影响一切 `git log` 取证）

`befbad4`（标题「chore: 初始化版本库」，212 files / 47184 insertions）：
```
author date = 2026-06-01 22:15:05 +0800
commit date = 2026-09-02 11:25:05 +0800      ← 相差 3 个月
```
⇒ 本仓 09-02 之前的历史是**一次带回溯日期的导入**，`git log --format=%ad` 读到的"6 月"日期不可信；
凡按 author date 做归因/时序判断（今晚 n918-03 那类"时钟超前"审计同样吃这类亏）应以 `%cd`（commit date）为准。
复现：`git log -1 --format="%ad | %cd" --date=iso befbad4`；`git show --stat befbad4 | tail -1`。
本单因此**不**把"PLAN-REVIEW-LOG.md 停在 befbad4"解读成"6 月写完就没动过"，而是解读成"09-02 导入后 17 天零更新"。

## 四、步骤 3 的判定与建议修订文案（**未落地，PLAN.md 未改**）

判定：**步骤 3 目前是"条款在、流程不在"——称不上形同虚设（步骤 2/4 的产物确实是它服务过的对象），但已失效**：
① 角色写反（现阵容是 DeepSeek Flash 执行＋GPT-5.6 评审，条款写的 GPT 提方案/DeepSeek 复核）；
② 触发条件没写（哪些补测必须走双模型？现在全靠各单自觉，实际结果是人人引用它来**推迟**决策）；
③ **留痕位置没规定** ⇒ 这就是 17 天只有 1 行的直接原因。

建议文案（供日间拍板后替换 `PLAN.md:13`；本单不改）：

```diff
-3. 通过项目多模型入口让 GPT 提出补测方案、DeepSeek 独立复核。
+3. 涉及断言"产品数值对不对"的补测（红线包：buy/sell、止损止盈、仓位、回测核心），
+   必须由 711ev 中转 GPT-5.6 出方案、官方 DeepSeek Flash 独立复核（结论不一致时升 Claude Opus 5 做第三评审）；
+   纯行为钉桩（characterization，只锁现状不判对错）可单模型执行，但须在 result 的「验收情况」里
+   写明本条属于"单模型（钉桩）"还是"双模型（数值判断）"。
+   留痕位置：`PLAN-REVIEW-LOG.md` 每条追加「日期 | 单号 | 档位(单/双/三) | 方案出处 | 复核结论」，缺一即视为步骤3 未执行。
```
同一处理由：**步骤 1/6 的"branch"要么兑现要么改字**——
若维持现定版口径，把 PLAN.md 里的「口径=branch」改成「语句覆盖率（`--cov` A 口径，范围＝multi_strategy＋bark_sender），门槛 82%」；
若坚持 branch，则补一次 `coverage run --branch --source=. -m pytest -q` 并把产物数字入基线报告（注意 `.coverage` 已被 gitignore，需另存文本输出）。

## 五、本单改动

**零改动**（未改 PLAN.md、未改 PLAN-REVIEW-LOG.md、未跑任何生产/回测脚本、无任何资金数值断言）。
本仓 porcelain 在上一单 q918-25 收口时已是「仅 `?? tmp/`」1 行，本单只新增本报告这一个文件（随后精确路径提交），
除它之外没有任何工作树变化。
