# 量化 coverage 口径统一说明（d914-15 / 2026-09-14，只读+出稿，配置零改动）

## 一、现状口径表

| 口径 | 命令 | 命中范围 | 实测 | 耗时 |
|---|---|---|---|---|
| **A 双主包**（本批建议口径） | `python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov-report=term` | multi_strategy.py + bark_sender/*（8 模块） | **TOTAL 84%**（1321 stmts / 206 miss），545 passed+2 xfailed | 26.1s |
| B 历史单模块（PLAN.md 62% 口径） | `python -m pytest -q --cov=multi_strategy --cov-report=term` | 仅 multi_strategy.py | 86%（443/61 miss）——**62% 已过期**（历史 441 collect/439 passed 时代） | 24.0s |
| C 定点抽查（各 cov batch 单口径） | `--cov=bark_sender.parsers` 等逐模块 | 单模块 | 见 quant-cov-batch-a/b1/b2 三份报告 | ~20s |

- 仓内**无** pytest.ini / pyproject / setup.cfg（coverage 全靠命令行 --cov，无 addopts，无 --cov 配置持久化）；`scripts/` 与 `tests/` 均不在任何现有口径的统计范围内（tests 自身不计、scripts 除非显式 --cov）。
- 实测命令与输出片段均在表内；全量套件 545 passed+2 xfailed 与 d913b-36 后口径一致。

## 二、与历史 baseline 的差异

- PLAN.md 写死的「441 collect / 439 passed / 62%」系 9/11 时代快照：当前 collect=547、passed=545、multi_strategy 单模块覆盖已 86%（d913b-36 时敏批等贡献）。62% 数字**已失真**，plan-baseline-ref-20260913 已把它降级为历史说明（正确），但「最新 baseline 文档」指向的 `quant-test-baseline-20260911.md` **在盘缺失**（指针悬空）。
- 本批（d913b-36/d914-06）新增用例只增不改：无覆盖回退。

## 三、待拍板项（≥3，各注影响面）

1. **统一口径选 A 还是 C**：A（双主包 84%）可作单一数字入 baseline；影响面=S5 例行化命令与门槛线设定。选 C 则继续逐批定点（无单一数字）。
2. **baseline 文件机制**：恢复 `quant-test-baseline-<日期>.md` 惯例并重算首份（内容=上表 A 口径全量 term 输出），还是改为「PLAN.md 指向 git 内固定 commit 的报告」；影响面=PLAN.md 步骤 1 措辞 + 未来报告的可追溯性（当前指针悬空已证实弊端）。
3. **scripts/ 是否纳入**：night_brain/bridge_sweep 等根仓脚本不在本仓；本仓 scripts/（如 ingest-english2-staging.py）现不统计。纳入则 84% 会被摊薄（分母变大）；影响面=门槛线与批次目标的公平性。
4. **门槛线**：是否设「TOTAL 不低于 N%」的防回退线（如 82%）；影响面=每批验收多一条硬检查，低覆盖模块（formatters 72% 等）的批次排期压力上升。

## 四、验收证据

- 命令原文与输出片段：表 A/B（`545 passed, 2 xfailed`、`TOTAL 1321 206 84%`、`multi_strategy.py 443 61 86%`）。
- 配置 diff=0（pyproject/pytest.ini 本就缺失，未新增）；本单仅新增本报告 1 份。
