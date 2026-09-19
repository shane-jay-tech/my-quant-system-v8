# quant fetch_minute_kline.py --dry-run 切片2 落地（n916x-18，q916-04 设计稿）

**结论：--dry-run 落地（W1 写文件/W2 降级标记写/W2' 删标记/W3 状态写四点全部短路，含删除副作用显式 return 保证），5 用例全绿；全量 674 passed 零新增 failed；默认行为等价。**

## 一、实现要点（对照设计稿§二 fetch_minute 专属）

- **W1**（save_minute_data）：`[DRY-RUN] W1 would-write -> {MINUTE_DIR}/{code}.csv (N rows)`，to_csv 短路、仍返回 filepath（调用方计数流不受扰）。
- **W2**（降级标记写）：`[DRY-RUN] W2 would-write -> .minute_degraded (marker)`；成功率判断照常计算，仅不落标记。
- **W2'**（删标记）：`[DRY-RUN] W2' would-delete -> .minute_degraded`——**DRY 分支下 os.remove 不可达（显式 return/else 保证）**，is_minute_degraded() 读取逻辑未动。
- **W3**（_fetch_status.json）：`[DRY-RUN] W3 would-write ... (status json)`。
- W2/W2'/W3 三点自 fetch_all_hs300 尾部抽为 `_write_fetch_outcomes()`（行为等价重构，使可测）；收尾汇总行 `[DRY-RUN] would-write: N 个写点…`。
- argparse：`[code]` 位置参数（可选，保持单股用法）＋`--dry-run` 旗标；`python fetch_minute_kline.py --help` EXIT=0。

## 二、测试与验证（命令与数字同段）

```
$ python -m pytest tests/ -k minute_kline -q  → 5 passed（新增 5 ≥3）
$ python -m pytest -q                         → 674 passed, 4 skipped, 1 xfailed（零新增 failed）
```
用例：①dry-run W1 零写盘＋打印＋DRY_HITS 登记；②默认 W1 照写；③dry-run 降级分支 W2/W3 短路、统计打印照常；④**dry-run 清除分支不删文件**（既有 marker 字节级不变）；⑤默认写/删/状态等价三连。目录级「文件计数与 mtime 清单一致」以④的 marker 字节不变＋①/③的非存在断言承载（真实 main 级端到端因「不真实抓取」禁止条款未跑，与切片1 同口径）。

## 三、验收情况

- ✅ `-k minute_kline` 全绿 5 passed（≥3）；✅ 全量 674 绿零新增 failed；✅ 删除路径 dry-run 下完全不执行（else 分支隔离＋字节不变断言）；✅ 未真实抓取、未删任何真实数据、未碰资金计算路径；代码精确路径 git add，未 push。

## 遗留问题

无。切片3（--dry-run-plan 零网络档＋两脚本全量回归）待后续单。
