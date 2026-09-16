# 隔离哨兵纳入 pytest 默认收集（916p-a1-007，2026-09-17）

## 一、现状复现（命令与输出同段）

```
$ python -m pytest --collect-only -q | tail -1
637 tests collected in 1.88s          ← 无 audit_test_isolation_scan（grep 过滤 0 命中）
$ python -m pytest tests/audit_test_isolation_scan.py -q
6 passed in 1.34s                     ← 单跑可跑，但默认收集永远跳过
```

（注：任务书基线 598 为其撰写时点；本夜前序补测已 +39，故现状实测 637，语义一致。）

## 二、落地（pytest.ini 仅追加一行）

```diff
 addopts = -p no:cacheprovider
+python_files = test_*.py audit_*_scan.py
```

`git diff -- pytest.ini` 输出仅上示一行新增，`norecursedirs`/`testpaths`/`addopts` 零改动；哨兵文件名、tools/audit_test_isolation.py 判定、任何测试断言均未动。

## 三、复验（命令与数字同段）

```
$ python -m pytest --collect-only -q | tail -1
643 tests collected in 1.78s          ← 637+6，精确 +6 无同名误收
$ python -m pytest -k audit_test_isolation -q
6 passed, 637 deselected in 1.73s
$ python -m pytest -q
641 passed, 2 xfailed, 12 warnings    ← 比改动前多 6、failed=0
```

**供 916-13 对照**：本单改后的默认 collected 数＝643（其报告中 634/637 基线均为各自时点口径，分母变化不代表覆盖率分子变化——两主包语句数未动，覆盖率应仍为 84%）。

## 四、为何此前一直没被发现（默认收集规则盲区）

1. pytest 默认 `python_files = test_*.py *_test.py`，`audit_test_isolation_scan.py` 以 `audit_` 开头、虽含 `test_` 中段但不匹配任何默认模式——单独指名直跑永远「能过」，只有全量门禁才暴露「从未被收集」；
2. 该哨兵 9/13 落地时验证用的是指名直跑（其报告第七节记录的验证命令即单跑形态），盲区自此埋下；
3. 全量数字一路增长（571→596→634→637）从未与「应收集数」对过账——**教训：新增测试文件必须核对 `--collect-only` 总数增量，数字对不上=没进门禁**。

本次改动只扩大收集范围，不改变任何用例的执行结果（6 条 golden 全绿如旧）。

## 五、验收对照

- ✅ collect 末行 643（=现状 637+6）；-k 选中 6 全绿；全量 failed=0 且 passed +6。
- ✅ git diff -- pytest.ini 仅 python_files 一行。
- ✅ 未重命名/删除哨兵、未改 tools 判定、未动 norecursedirs/testpaths、未碰 --cov 口径；不 push。
