# 扫描器＋隔离哨兵成对入库（916p-a1-012，2026-09-17）

## 一、耦合关系复现（命令与输出同段）

```
$ git ls-files pytest.ini tools/audit_test_isolation.py tests/audit_test_isolation_scan.py
pytest.ini                                  ← 快照漂移：a1-007（95c2a69）已先行入库
（其余两路径空＝未入库，tests/audit_test_isolation_scan.py:11 依赖 tools/ 才能跑）
$ python -m pytest tests/audit_test_isolation_scan.py -q
6 passed in 1.39s                           ← 提交前（依赖 tools/ 在盘）
```

## 二、提交（1a2a2a9）

```
$ git show --stat --oneline HEAD
 tests/audit_test_isolation_scan.py | 69 ++++
 tools/audit_test_isolation.py      | 122 ++++
 2 files changed, 191 insertions(+)
$ git ls-files pytest.ini tools/audit_test_isolation.py tests/audit_test_isolation_scan.py
pytest.ini / tests/audit_test_isolation_scan.py / tools/audit_test_isolation.py   ← 各 1 行
```

- 精确路径 add（pytest.ini 已在库自动跳过），无 -A/-u/.；不 push（ahead 14）。

## 三、提交后复验（与提交前零变化）

```
$ python -m pytest tests/audit_test_isolation_scan.py -q → 6 passed in 1.31s（前 6 passed）
$ python -m pytest -q → 660 passed, 4 skipped, 2 xfailed（failed=0，与提交前一致）
```

全新 checkout 缺件问题闭环：哨兵与其被测扫描器同库可复跑。

## 四、验收对照

- ✅ ls-files 三路径各 1 行。- ✅ 哨兵 6 passed 前后一致。- ✅ 全量 failed=0 且数字一致。- ✅ show --stat 清单＝2 项（快照漂移注记：pytest.ini 由 a1-007 处理）。- ✅ ahead 未推。
