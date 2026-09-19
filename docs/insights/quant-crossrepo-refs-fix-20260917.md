# quant 跨仓 insights 引用口径修订落地（917-32）

**结论：14 点全部就地改写完成（A 类 5 点→根仓绝对路径 `D:\code\docs\insights\…`；B 类 9 点→加「（量化仓）」限定；C/D＝0 无待拍板项）——复刻口径复扫，改后无限定形态残留 0。零代码改动（10 文件均 docs/*.md 与 PLAN.md）。**

## 一、14 点逐条处置（现状与改写同段）

| # | 引用点 | 类 | 处置 |
|---|---|---|---|
| 1-2 | quant-coverage-caliber-trace-20260916.md:24（×2） | B | →（量化仓）标注 |
| 3 | s4-cd-r2-diff-review-20260911.md:71 自指 | B | →（量化仓，自指） |
| 4 | quant-s4-r2-minor-20260911.md:3 | B | →（量化仓） |
| 5 | quant-gitignore-noise-20260917.md:10 | B | →（量化仓） |
| 6 | quant-frozenclock-targets-sentinel-20260917.md:8 | B | →（量化仓） |
| 7 | quant-dryrun-fetch-design-20260916.md:3 | A | → `D:\code\docs\insights\quant-write-path-matrix-20260914.md`（原已自注根仓，补绝对路径） |
| 8 | quant-coverage-caliber-trace-20260916.md:3 | A | → 根仓绝对路径 |
| 9 | 同文件 :31 自指 | B | →（量化仓，自指） |
| 10 | 同文件 :10 | B | →（量化仓） |
| 11 | quant-agents-symbol-refs-20260917.md:8 | B | →（量化仓） |
| 12 | midnight-fixture-spec-20260913.md:3 | A | → 根仓绝对路径 |
| 13 | h912-04-quant-cov-batch-a-20260912.md:3 | A | → 根仓绝对路径 |
| 14 | PLAN.md:11 | A | → 根仓绝对路径（历史首份名补全） |

## 二、改后分级计数（核验命令与数字同段）

```
改后 A/B 级残留（无限定形态的跨仓引用点）：0
（核验脚本：对 11 个引用文件逐行匹配 docs/insights/<name>，
 判「已限定」＝含（量化仓）标注／根仓绝对路径／自指标注三者之一；
 输出＝引用点总数 11（触点文件内），未限定残留 0）
```

## 三、验收情况

- ✅ 14 点逐条现状与处置（改写 14/14；无失效点）；✅ 改后 A+B 残留 0（§二核验）；✅ 零代码改动（10 文件均文档）；git add 已按精确路径暂存；不 push。

## 遗留问题

无。
