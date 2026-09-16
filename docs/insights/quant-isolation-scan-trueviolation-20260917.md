# 隔离扫描器命中逐条核实＋真违规修复（916p-a1-010，2026-09-17）

## 一、基线实跑（修复前，输出同段）

```
$ python tools/audit_test_isolation.py --root tests
scanned_files=66 findings=17        ← 任务书基线 59/16 为其撰写时点；本夜新增测试
                                      文件 +1 命中（test_file_io_atomic.py docstring）
```

修复后复跑：`scanned_files=66 findings=16`；指向 test_timefixture_characterization.py 的 bare-assign 命中＝**0**（grep -c＝0）。

## 二、16→17 条逐条分类表（现口径 17 条全列）

| # | 点位 | 规则 | 分类 | 理由 |
|---|---|---|---|---|
| 1 | test_timefixture_characterization.py:95 | bare-assign | **真违规（已修）** | 裸赋值不走 monkeypatch、用例结束不还原（norm:16 范式二） |
| 2 | test_bark_push_charac.py:10 | high/net | 误报 | `import requests` 仅取异常类型（requests.exceptions.Timeout/ConnectionError），post 全部 monkeypatch 成假函数（:34/:42/:48），零真实网络 |
| 3-4 | audit_test_isolation_scan.py:60 ×2 | data-path/abs-write | 误报 | golden 用例内嵌的违规样本字符串（自指片段，非真实写） |
| 5 | test_file_io_atomic.py:59 | abs-write | 误报 | 本夜 a1-002 报告性 docstring 文本（内容含 `open('.tmp','w')` 字样），tmp_path 沙箱内执行 |
| 6-14 | test_sim_trade.py:38/54/68/78/140/230/249/269/346 | abs-write | 误报 ×9 | `isolated_sim_trade` 夹具（:16-18）已 monkeypatch RISK_CONFIG_FILE/STATE_FILE → tmp_path，写入路径全在沙箱 |
| 15-17 | test_stallwatchdog_contract.py:55/67/89 | data-path | 误报 ×3 | "data/stock_*.csv" 字符串传给整体 stub 的 `_latest_date`，无真实读/写 data/ |

## 三、修复（仅隔离机制，断言零改动）

```diff
-def test_b2_weight_history_cross_midnight_two_dates(tmp_path, frozen_clock):
-    multi_strategy.DATA_DIR = str(tmp_path)
+def test_b2_weight_history_cross_midnight_two_dates(tmp_path, frozen_clock, monkeypatch):
+    monkeypatch.setattr(multi_strategy, "DATA_DIR", str(tmp_path))
```

同文件 grep 其它裸赋值（`^\s+[a-zA-Z_.]+ *= *str\(tmp_path\)`）＝0，无残留。

## 四、复验（命令与数字同段）

```
$ python -m pytest tests/test_timefixture_characterization.py -q → 19 passed（改前 19 passed，一致）
$ python -m pytest tests/audit_test_isolation_scan.py -q        → 6 passed
$ python -m pytest -q                                           → 660 passed, 4 skipped, 2 xfailed（failed=0）
$ python tools/audit_test_isolation.py --root tests             → findings 17→16，bare-assign(timefixture) 1→0
```

本单足迹＝tests/test_timefixture_characterization.py（+报告）；git diff --stat 中 AGENTS.md/README.md/auto_heal.py/data_loader.py 为班前既有脏项（9/16 晨报已点名，本班零触碰）。

## 五、剩余误报族与规则修正建议（本单不实施）

1. `abs-write` 规则建议识别「写入目标为 monkeypatch 过的模块属性」（跨行上下文已具备，建议补 fixture 关联判定），可一次消除 sim_trade 9 条；
2. `high/net` 建议放行「仅 import 且无 .get/.post 调用」形态（bark_push_charac 型）；
3. golden 自指与 docstring 文本建议按「字符串常量内命中降级 info」（audit_test_isolation_scan:60 与 file_io_atomic:59 型）。

## 六、验收对照

- ✅ 修复前后两次扫描输出同段；bare-assign(timefixture) 1→0。
- ✅ timefixture 19 passed 与改前一致；golden 6 passed；全量 failed=0。
- ✅ git diff --stat 本单足迹仅 tests/ 一文件（+新增报告），班前脏项已注记。
- ✅ 未改扫描器规则、未改 golden 断言、未放宽任何断言；不 push。
