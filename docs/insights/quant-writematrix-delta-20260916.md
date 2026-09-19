# capacity_collect 49/84 vs q914-32 48/83 差 1 归因（n916x-20，只读）

**结论：差 1 ＝ `scripts/capacity_collect.py` 自身被扫中——其 :15 `PAT = r"open\(.*['\"](w|a)|to_csv|to_sql|executemany|INSERT INTO|UPDATE "` 模式串文本含关键词，被 collector 的 rg 自匹配＝1 个假阳性写点。归因链：14e3ea2（9/16 06:05）把脚本从 tmp/ 迁入 scripts/ 后，q914-32（9/16 00:10 跑，48/83）之后的所有 collector 运行都把自己计入。真实写点口径 48/83 与矩阵一致。**

## 一、复跑三数（命令与输出同段）

```
$ python scripts/capacity_collect.py   → EXIT=0
scripts-with-write: 49 | total-points: 84 | dryrun-flagged: 0 | prior-d91437-covered: 0
```
（dryrun=0 说明：collector 的 dryrun 列来自外部名单文件 %TEMP%\q32_dryrun.txt——现已为空集（916p-a1-020 自包含化后缺省按空集）；矩阵的 6 是 q914-32 以 `rg -l "dry.?run"` 自测口径。两口径不同源，不构成第二处差异。）

## 二、差 1 归因（精确到 file:line）

```
$ rg -n "open\(.*['\"](w|a)|to_csv|to_sql|executemany|INSERT INTO|UPDATE " scripts/capacity_collect.py
15:PAT = r"open\(.*['\"](w|a)|to_csv|to_sql|executemany|INSERT INTO|UPDATE "
```
- **新增脚本**：scripts/capacity_collect.py（矩阵 48 名单无它——14e3ea2 9/16 06:05 才从 tmp/ 迁入 scripts/，晚于矩阵扫描 9/16 00:10）。
- **新增写点**：capacity_collect.py:15——PAT 常量字符串含 `to_csv`/`UPDATE ` 等被匹配词＝**自匹配假阳性**，非真实写盘语句（该脚本自身只读名单＋print，916p-a1-020 改造后无写盘）。
- 排除法佐证：矩阵 A 段 14＋B 段 34＝48 名单与今日 collector 输出的其余 48 名单一一对应，无第二处增减。

## 三、是否应纳入判定

- 机械 rg 口径：49/84 如实反映（含 1 假阳性）——collector 统计逻辑无错。
- 语义口径：capacity_collect.py:15 **不应计入**（非取数/落盘写点，是检测模式串）；真实写点口径＝48/83，与 q914-32 一致。
- 建议（本单不改脚本）：collector 加 `-g "!scripts/capacity_collect.py"` 自排除，或把 PAT 行拆串（如 `"to_" + "csv"`）避开自匹配；顺带可把 dryrun 列改为自动检测（rg -l "dry.?run"）替代外部名单，三处都是统计逻辑变更，留日间拍板。

## 四、验收情况

- ✅ 复跑 EXIT=0，三数与报告一致（命令同段）；✅ 归因到 file:line（scripts/capacity_collect.py:15，非「代码演进」式表述）；✅ 只读未改脚本未 push。

## 遗留问题

无。collector 自排除/自动 dryrun 检测两项建议留日间拍板。
