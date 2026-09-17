# test_health_s4cd4 UnicodeDecodeError 线程告警处置（n916d-17 顺延单）

- 班次：sweep-20260916-2300（9/17 08:1x–08:2x 段）
- 结论：解码点定位为**生产读取**（ops/health.py 两处 schtasks 调用），最小修复＝显式 `encoding='utf-8', errors='replace'`；-k s4cd4 **4 passed 零告警**；全量 **664 passed / 4 skipped / 1 xfailed / 0 failed**

## 一、复现（命令在前）

```
$ python -m pytest -k s4cd4 -q
3 passed, 665 deselected, 12 warnings in 4.21s
告警原文（traceback 尾段）：
  File "D:\Program\Lib\subprocess.py", line 1601, in _readerthread
    buffer.append(fh.read())
  File "<frozen codecs>", line 322, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc8 in position 1: invalid continuation byte
（pytest.PytestUnhandledThreadExceptionWarning）
```

## 二、定位与判定（file:行）

| 点 | 判定 |
|---|---|
| ops/health.py:262 与 :271（修前行号）：`subprocess.run(['schtasks',...], capture_output=True, text=True, timeout=10)` | **生产读取**——`text=True` 未显式 encoding；本机 UTF-8 运行模式下按 utf-8 解码 schtasks 的 GBK 输出（0xc8＝GBK 首字节），subprocess 读线程抛 UnicodeDecodeError |

## 三、最小修复（逐行标注）

```diff
 ops/health.py:262（别名循环内）
-  r = subprocess.run([...], capture_output=True, text=True, timeout=10)
+  # n916d-16 同族解码防御：schtasks 输出为 GBK，UTF-8 模式下 text=True 读线程会炸
+  r = subprocess.run([...], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
 ops/health.py:271（QuantMorningPipeline 直查）
-  _r = subprocess.run([...], capture_output=True, text=True, timeout=10)
+  _r = subprocess.run([...], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
```

策略选择：`errors='replace'` 保证读线程永不抛（任务名等 ASCII 字段原样保留，中文列置换显示不影响存在性判断）；不改任何阈值/数值口径、无行为分支变化。

## 四、锁定用例（新增 1 条）

`test_schtasks_decode_no_thread_warning`：`@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")` 标记下完整跑 `health.run_all()`——修复前该标记会把读线程告警升为失败，修复后自然通过（防回潮）。

## 五、验收（命令在前）

```
$ python -m pytest -k s4cd4 -q
4 passed, 665 deselected in 5.17s          （3→4，全绿；grep UnicodeDecodeError/thread = 0 处）
$ python -m pytest -q
664 passed, 4 skipped, 1 xfailed in 11.67s  （failed=0；1 xfail＝screen_stocks 未来函数既有件，n916d-17 已出修复材料）
```

`git diff` 仅 ops/health.py（2 行调用＋2 行注释）与 tests/test_health_s4cd4_h912_09.py（新用例）；AGENTS/README/auto_heal/data_loader 4 文件为班前遗留（n916d-20 已 triage），本班未触碰。

——完。
