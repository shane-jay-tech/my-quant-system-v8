# quant 工作区在途脏文件归属 triage（n916d-20，只读）

- 班次：sweep-20260916-2300（9/17 08:1x 段）
- 结论：6 项脏文件＝**4 M 同属「文档对齐＋静默异常治理」家族（推测 9/13–9/15 白天批，未登记在途）＋ 2 ?? 运行产物（应 gitignore）**；本班零触碰（运行前后 porcelain 一致）

## 一、porcelain 实录（命令在前）

```
$ git status --porcelain
 M AGENTS.md
 M README.md
 M auto_heal.py
 M data_loader.py
?? .coverage
?? tmp/
（共 6 行）
```

## 二、triage 表（6 行＝porcelain 行数，逐行归属）

| 文件 | 状态 | diff 摘要 | 归属 | 建议动作 |
|---|---|---|---|---|
| AGENTS.md | M | +6/−6：协作方法「v2 三模型」→「v3 双通道 2026-09-13 精简」＋退役名单；自检表述「147 项」→「项数见 ops/health.py」 | 文档对齐族（9/13 阵容精简落地伴随改） | 提交（docs 类） |
| README.md | M | +6/−4：`_self_check.py`→`ops/health.py` 路径对齐＋追加「2026-09-04 夜间注记」块（bat 行尾修复史） | 文档对齐族（同上） | 提交（docs 类） |
| auto_heal.py | M | +1/−1：备份失败 `pass` → `log('WARN','Backup before recreate failed')` | 静默异常治理族 | 提交（可观测性，语义安全） |
| data_loader.py | M | +8/−8：两处情绪指标 `except: pass` → 打印 `[DATA] sentiment: … unavailable (类型: 异常)` | 静默异常治理族（同上） | 提交（可观测性，语义安全） |
| .coverage | ?? | pytest-cov 运行产物 | 运行产物（非代码） | 加 .gitignore【需日间确认】或删除 |
| tmp/ | ?? | 临时目录 | 运行产物 | 加 .gitignore【需日间确认】或清理 |

「无法归属」项：**无**——4 个 M 文件均可归入同一意图家族（文档/可观测性硬化，非业务数值改动）；但**无法唯一到单条任务号**（推测 9/13–9/15 白天批文档订正＋异常治理伴随产物，佐证＝AGENTS.md 精简文案的 2026-09-13 时点、README 注记的 9/4 时点），属「已授权方向的未登记在途」，留日间按家族整体提交。

## 三、零触碰证据

运行前后 `git status --porcelain` 输出逐字节一致（本单只读 diff 与状态，未 commit/stash/checkout/clean/改文件）。

——本单产物仅本报告；不 push。
