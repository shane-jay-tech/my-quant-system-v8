# quant fetch_history.py --dry-run 切片1 落地（n916x-17，q916-04 设计稿）

**结论：按设计稿契约落地 --dry-run（argparse 骨架＋W0/W1/W2/W3 四拦截点＋W0 备份副作用拦截＋收尾汇总行），5 用例全绿；全量 669 passed 零新增 failed；默认路径（无旗标）行为逐字节不变。**

## 一、实现要点（对照设计稿§二契约）

- `--dry-run` 无值旗标（argparse，fetch_history.py `_parse_args`）；模块级 `DRY/DRY_HITS`。
- **W0**（备份副作用）：`[DRY-RUN] W0 would-backup -> <history.csv>.bak`，copy2 短路。
- **W1**（EM fastpath 追加）：`[DRY-RUN] W1 would-append -> <history.csv> (N rows, mode=append)`，to_csv 短路、**照常返回内存代码集**（后续计数不受扰）；OK 行改 DRY 措辞防误导。
- **W2**（save_increment）：`[DRY-RUN] W2 would-append ... mode=<mode>`，短路返 None。
- **W3**（最终去重）：块抽为 `final_dedupe()` 函数（行为等价重构，使可测），DRY 下打印 `[DRY-RUN] W3 would-rewrite ... (N rows, mode=rewrite)` 并跳过 tmp+os.replace；Step5 验证段照常读盘（不加前缀，区分「现有/将写」）。
- 收尾汇总：`[DRY-RUN] would-write: N 个写点, 目标=…; 实际写盘 0 字节`。

## 二、测试与验证（命令与数字同段）

```
$ python -m pytest tests/ -k fetch_history -q  → 5 passed（新增 5 ≥3）
$ python -m pytest -q                          → 669 passed, 4 skipped, 1 xfailed（零新增 failed）
$ python fetch_history.py --help               → EXIT=0（argparse 骨架冒烟）
```
用例：①dry-run save_increment 零写盘＋W2 打印＋DRY_HITS 登记；②默认 save_increment 照常落盘、无 DRY-RUN 输出、DRY_HITS 空；③fastpath（三点 stub 零网络）拦截 W0/W1——`.bak` 不存在、history.csv **read_bytes 逐字节不变**（含 sha256 语义）、返回代码集不变；④W3 短路——重复行原样保留、无 .tmp 残留、打印将压平行数；⑤默认 W3 去重照常执行。

**真实 main() 的端到端 dry-run 未执行**：任务书禁止条款「不做真实抓取」与设计稿「网络照常」在 main 级冲突，按禁止条款从紧——以写点级 stub 测试的逐字节比对＋CLI 冒烟替代（main 级验证可在授权抓取窗口补做）。

## 三、⚠ 设计外发现（存量缺陷，本单未修——改即变默认行为）

`final_dedupe` 内 `tmp_path = HISTORY_FILE + '.tmp'`：HISTORY_FILE 自 S4-b 路径收敛起为 **pathlib.Path**，`Path + str` 抛 TypeError→被 try/except 吞成 `[WARN] Final dedupe failed`→**Step4.5 去重自迁移以来静默 no-op**（生产 history.csv 实际未被压平）。本单保持原语义（测试用 str 口径验证 W3 逻辑），修复一行（`str(HISTORY_FILE)+'.tmp'` 或 Path 拼接）属默认行为变更，**留日间拍板**。

## 四、验收情况

- ✅ `-k fetch_history` 全绿 5 passed（≥3，命令与数字同段）；✅ 全量 669 绿零新增 failed；✅ dry-run 零写盘以 read_bytes 逐字节断言（sha256 等价语义，命令与结果同测试段）。
- ✅ 未联网抓取（fastpath 三点 stub）；未碰持仓/下单/风控；代码精确路径 git add（fetch_history.py＋tests/test_fetch_history_dryrun.py），未 push。

## 遗留问题

W3 Path+str 存量缺陷待日间拍板修复（§三）；main 级 dry-run 端到端待授权抓取窗口补验；切片2（fetch_minute_kline.py）与切片3（--dry-run-plan）待后续单。
