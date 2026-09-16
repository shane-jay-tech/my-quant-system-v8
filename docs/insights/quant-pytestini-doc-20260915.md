# quant pytest.ini 与文档/CI 口径核对（n915-67，只读）

- 任务：n915-67-quant-pytestini-doc（created 2026-09-15T23:39:01，软预算 ≤20 分钟）
- 执行：sweep-20260915-2300（GLM-5.3-Flash），2026-09-16 03:0x
- **结论：无 CI 配置（.github/workflows 不存在）；文档命令与 pytest.ini 兼容（addopts 仅禁缓存，不改变收集路径）；无漂移项。**

## 一、pytest.ini 原样（6 行）

```ini
[pytest]
testpaths = tests
norecursedirs = logs archive tmp build dist .venv node_modules
addopts = -p no:cacheprovider
```

## 二、文档/口径命中对照表（file:line｜原文｜判定）

| 位置 | 原文 | 与 pytest.ini 关系 | 判定 |
|---|---|---|---|
| README.md:79 | `python -m pytest`（单元与回归测试） | 继承 testpaths=tests 与 addopts | **一致** |
| PLAN.md:28 | `python -m pytest -q` | `-q` 与 addopts 叠加（-p no:cacheprovider 保留） | **一致** |
| PLAN.md:29-30 | `python -m coverage run --branch --source=. -m pytest -q` ＋ `coverage report` | coverage 直调 pytest，testpaths 经 `pytest -q` 生效；`--source=.` 比 c7db 复跑用的 `--source=bark_sender` 更宽（含全仓） | **一致**（口径宽窄差异已在 915-35 报告披露） |
| .github/workflows | 不存在 | 无 CI 口径需对齐 | — |

## 三、声明

未改 pytest.ini/CI/文档；不 push。

## 遗留问题

无（PLAN.md:29 `--source=.` 会把 coverage 统计拉进 scripts/app 全仓——如需干净报告可改 `--source=core,bark_sender`，仅建议不实施）。
