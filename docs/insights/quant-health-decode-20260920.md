# ops/health.py 解码口径收敛（q920-11）

- 日期：2026-09-20｜仓库：D:\code\my-quant-system-v8
- 依据：`docs/insights/quant-subprocess-encoding-inventory-20260918.md`（q918-18）`三 / `六.1 的结论
  ——「health 那两处建议收敛成 **errors-only**（改动面是两行参数）」
- 性质：**只动解码参数，不动任何业务逻辑**

## 一、改了什么（两行）

| 位置 | 改前 | 改后 |
|---|---|---|
| `ops/health.py:263`（`TASK_ALIASES` 循环里的 `schtasks /query /fo CSV`） | `text=True, encoding='utf-8', errors='replace'` | `text=True, errors='replace'` |
| `ops/health.py:272`（`QuantMorningPipeline` 查询） | 同上 | 同上 |

改后全仓 `ops/health.py` 内 `encoding='utf-8', errors` 组合 **0 处**（`grep` 实测）；
`auto_heal.py` 三处本就是 errors-only，两套口径至此**统一**。

## 二、为什么 errors-only 才对（机制）

1. **崩溃的充要条件是「严格解码」** ⇒ `errors='replace'` 就够（q918-18 `三实测）。
2. 再叠 `encoding='utf-8'` 会把**本可正确还原**的中文整片换成 `U+FFFD`：
   把「崩溃」换成「日志不可读」，而自愈/排障场景里人只能靠这份日志。
3. **让 `encoding` 缺省（跟随 locale）才与子进程同源**；父子若都在 UTF-8 模式同样同源。

## 三、本单实测：环境会**掩盖**这个缺陷（重要，别被误导）

| 项 | 实测值 |
|---|---|
| 本测试会话 `PYTHONUTF8` | **1**（仅进程级；`[Environment]::GetEnvironmentVariable('PYTHONUTF8','User'/'Machine')` 均为空） |
| 本测试会话 `PYTHONIOENCODING` | `utf-8` |
| 系统活动代码页（`chcp`） | **936** |
| 会话内 `locale.getpreferredencoding(False)` | **utf-8**（被 PYTHONUTF8 改写的假象） |
| 会话内子进程 stdout 原始字节 | `b'\xe4\xb8\xad\xe6\x96\x87...'` = **UTF-8** |

结论：**在我的会话里父子同源（都 UTF-8），新旧两种写法解码结果一样 ⇒ 修复效果被掩盖**。
而 q918-18 当时测到的是 `b'\xd6\xd0\xce\xc4\xb1\xea\xbc\xc7OK'`（cp936）——因为那次**没有** PYTHONUTF8。
生产进程由 Task Scheduler → `daily_pipeline.bat` 拉起，User/Machine 级都没设 PYTHONUTF8，
**走的是 legacy cp936 模式** ⇒ 子进程发 cp936 字节，此时强制 `encoding='utf-8'` 才会解坏。

所以本单的收敛在**生产环境确实是有效修复**，只是在本会话里看不到差异——
因此测试不能依赖环境变量，必须用**字节级确定性对照**（见下）。

## 四、新增测试 `tests/test_health_decode_q920_11.py`（5 例全绿）

| 用例 | 钉什么 |
|---|---|
| `test_两处schtasks调用均为errors_only` | **AST 静态**：两处 `subprocess.run` 含 `text=True`＋`errors='replace'`、**且 `encoding` 缺席**（口径漂回去就红） |
| `test_确定性对照_cp936字节在两种口径下的差异` | **不依赖环境**：构造 cp936 字节 → 严格 utf-8 抛 `UnicodeDecodeError`；`utf-8+replace` 出 `U+FFFD` 且中文丢失；`cp936+replace` 完整还原 |
| `test_子进程路径_errors_only下无替换字符` | 子进程实跑不变量：errors-only 下 stdout 无 `U+FFFD`、中文完整（两种环境模式都成立，不 skip） |
| `test_任务名比对不受解码口径影响` | 行为不变量：任务名是 ASCII，新旧口径对「任务名 in stdout」判定一致 |
| （旧）`test_schtasks_decode_no_thread_warning` | 保持原有「无读线程异常」断言 |

## 五、自证

````
$ python -m pytest tests/test_health_decode_q920_11.py tests/test_health_s4cd4_h912_09.py -q
.........                                                                [100%]
9 passed in 6.24s

$ python -m pytest tests/ -q
852 passed, 4 skipped, 3 xfailed in 22.06s
```

## 六、遗留

1. **同一族还有一处未动**：`scripts/capacity_collect.py:60`（`rg` 调用，路径含中文即触发）。
   q918-18 `二 #9 已判定「唯一还值得动的一处」，本单按任务边界未涉——建议另开小单。
2. **无静态门禁**：q918-18 `四建议「凡 `text=True` 或有 `capture_output=True` 的 subprocess 调用必须带 `errors=`」，
   本单只钉了 health 这两处（AST 用例），**全仓门禁仍未建**。
3. `core/pipeline.py:186` / `daily_pipeline.py:34` 属「当下不读输出」，加 `errors` 无行为；
   若将来补 `capture_output=True` 需同步补 `errors`（同上，靠门禁而非人记）。
