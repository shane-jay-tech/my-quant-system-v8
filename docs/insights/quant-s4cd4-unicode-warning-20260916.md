# quant test_health_s4cd4 UnicodeDecodeError 线程 warning 成因核验（n916g-03，只读）

- 班次：日间续班（用户令继续）
- **状态备注：本单核验的 warning 已由 n916d-21 修复清零**（提交 cb62427，2026-09-17 凌晨段：ops/health.py 两处 schtasks `subprocess.run` 补 `encoding='utf-8', errors='replace'`＋锁定用例）。本报告＝成因结论存档＋当前时点复核，零改码

## 一、当前时点复核（命令在前）

```
$ python -m pytest -k s4cd4 -q -rw
（4 passed；输出零 warning 段、零 UnicodeDecodeError/thread 字样——grep 计数 0）
$ python -m pytest -k s4cd4 -q | grep -c "UnicodeDecodeError"
0
```

修前形态（n916d-21 报告 quant-s4cd4-decode-20260917.md §一 原样存档）：`3 passed, 12 warnings`＋`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc8`（subprocess `_readerthread` 线程堆栈）。

## 二、成因结论（file:line 可核）

- **触发点＝生产码**：`ops/health.py:262/:271`（修前行号）`subprocess.run(['schtasks',...], capture_output=True, text=True, timeout=10)`——`text=True` 未显式 encoding；本机 UTF-8 运行模式下按 utf-8 解码 schtasks 的 GBK 输出（0xc8＝GBK 首字节）⇒ 读线程抛 UnicodeDecodeError ⇒ pytest 转为 PytestUnhandledThreadExceptionWarning。
- 复跑命令：`rg -n "schtasks" ops/health.py`（修后两行带 `encoding='utf-8', errors='replace'`）。
- 所读内容实际编码：GBK/CP936（Windows 中文 schtasks 输出；0xc8 为其首字节特征）。

## 三、归属与影响判定

1. **归属＝生产码缺 `encoding=`**（非测试侧读非 UTF-8 产物）——测试只是经 `health.run_all()` 间接触发 schtasks 查询。
2. **是否吞真实失败**：warning 属线程异常的事后通报，**不改变用例断言结果**（修前 3 passed＋warnings 同现）；但在 `-W error` 严格模式下会转为失败＝未来真实回归可能被该噪声掩盖。修复后此路径清零。
3. 修复验证：锁定用例 `test_schtasks_decode_no_thread_warning`（`filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")`）常驻防回潮。

## 四、零改码自证

本单零改码；`git diff --stat` 现存 4 文件（AGENTS/README/auto_heal/data_loader）＝班前遗留脏树（n916d-20 triage 在案）；ops/health.py 的修复已在 cb62427 提交，工作树无未提交改动。

——完。
