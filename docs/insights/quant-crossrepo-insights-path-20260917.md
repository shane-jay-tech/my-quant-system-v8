# quant 跨仓 docs/insights 引用解析口径核验（916p-a1-019，2026-09-17，只读）

## 一、抽取命令与计数（同段）

```
$ grep -rnoE 'docs/insights/[A-Za-z0-9_.\-]+\.md' PLAN.md README.md docs/insights/*.md | wc -l
13 行命中（其中 quant-coverage-caliber-trace-20260916.md:24 一行含 2 处匹配，按引用点计 = 14 点；
唯一被引名 10 个）。对照表行数按引用点展开＝14。
```

## 二、双根存在性判定（Test-Path 双查；A=只根仓 B=只量化仓 C=双无 D=双有）

| # | 被引名字 | 引用点 file:line | 根仓 | 量化仓 | 类 | 建议写法 |
|---|---|---|---|---|---|---|
| 1-2 | quant-coverage-caliber-20260914.md | quant-coverage-caliber-trace-20260916.md:24（同行 2 处） | ✗ | ✓ | B | 已在仓内，写「docs/insights/…（量化仓）」 |
| 3 | s4-cd-r2-diff-review-20260911.md | s4-cd-r2-diff-review-20260911.md:71（自指） | ✗ | ✓ | B | 同上 |
| 4 | s4-cd-r2-diff-review-20260911.md | quant-s4-r2-minor-20260911.md:3 | ✗ | ✓ | B | 同上 |
| 5 | empty-remark-nan-repro-20260914.md | quant-gitignore-noise-20260917.md:10 | ✗ | ✓ | B | 同上 |
| 6 | quant-bark-2fail-20260916.md | quant-frozenclock-targets-sentinel-20260917.md:8 | ✗ | ✓ | B | 同上 |
| 7 | quant-write-path-matrix-20260914.md | quant-dryrun-fetch-design-20260916.md:3 | ✓ | ✗ | **A** | 该文档自注「（根仓）」✓；建议统一 `D:\code\docs\insights\quant-write-path-matrix-20260914.md` |
| 8 | quant-coverage-recheck-20260914.md | quant-coverage-caliber-trace-20260916.md:3 | ✓ | ✗ | **A** | 统一根仓绝对路径写法 |
| 9 | quant-coverage-caliber-trace-20260916.md | 同文件 :31（自指） | ✗ | ✓ | B | 同上 B 类写法 |
| 10 | quant-coverage-caliber-20260914.md | quant-coverage-caliber-trace-20260916.md:10 | ✗ | ✓ | B | 同上 |
| 11 | quant-worktree-diff-attribution-20260917.md | quant-agents-symbol-refs-20260917.md:8（a1-017 报告引 a1-015 报告） | ✗ | ✓ | B | 同上 |
| 12 | quant-s5-test-design-20260912.md | midnight-fixture-spec-20260913.md:3 | ✓ | ✗ | **A** | 统一根仓绝对路径写法 |
| 13 | quant-test-baseline-20260911.md | h912-04-quant-cov-batch-a-20260912.md:3 | ✓ | ✗ | **A** | 统一根仓绝对路径写法 |
| 14 | PLAN.md:11 的 quant-test-baseline-20260911.md（`docs/insights/…` 同形态） | PLAN.md:11 | ✓ | ✗ | **A** | 写「根仓 D:\code\docs\insights\…」——PLAN.md 已自述「根仓」，建议补绝对路径 |

对照表 14 行＝引用点计数 14 ✓（唯一被引名 10 个）。

## 三、C/D 类

- **C（双无真悬空）＝0 个**（无一个名字双根皆缺，无需 Test-Path 双 False 样例）。
- **D（两边都有歧义）＝0 个**。
- 分布：A（只根仓）5 点、B（只量化仓）9 点。PLAN.md:11 与 quant-dryrun-fetch-design:3 是 A 类中已自注「根仓」的两处，属写法正确示范。

## 四、可直接替换示例

```
- 上游：…（`docs/insights/quant-write-path-matrix-20260914.md`，根仓）
+ 上游：…（`D:\code\docs\insights\quant-write-path-matrix-20260914.md`，根仓绝对路径）
```

口径建议：量化仓文档引用根仓材料一律用根仓绝对路径；引用仓内材料一律写 `docs/insights/…（量化仓）` 或裸文件名，杜绝无根限定形态。

## 五、零改动自证

`git diff -- PLAN.md docs/` 输出为空 ✓（仓内）。只读；不 push。
