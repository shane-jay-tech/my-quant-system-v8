# AGENTS.md 符号引用悬空核验（916p-a1-017，2026-09-17，只读）

## 一、自证命令与输出（同段）

```
$ git grep -n run_self_check
AGENTS.md:217:| 自检自愈 | `ops/health.py`（原 _self_check.py）+ `auto_heal.py` | 每日管道结束后自动自检（项数见 `ops/health.py` run_self_check 返回）→自动修复→日志记录 |
docs/insights/quant-worktree-diff-attribution-20260917.md（量化仓）:60:+「自动自检（项数见 ops/health.py run_self_check 返回）」
```

→ 代码内 **0 处**；文档命中 2 处＝AGENTS.md:217 原文＋a1-015 报告的引文（后者系本夜审计报告对原文的转录，非独立使用）。ops/health.py 实际入口＝`def run_all():`（:109），另有 check(:22)/warn(:30)/_scan_hardcoded_bark_token(:39)/is_non_trading_day(:52)。

## 二、引用抽取（命令与计数同段，唯一化后 10 条）

```
$ grep -oE '`[a-z_]+/[a-z_]+\.py`[^|]{0,30}' AGENTS.md | sort -u
（10 条唯一引用，逐条见下表）
```

| # | 主张原文（引用形态） | 落点/核验 | 是否成立 | 建议改法 |
|---|---|---|---|---|
| 1 | `ops/health.py` run_self_check 返回 | ops/health.py 全文无该符号（def 清单见上） | **✗ 悬空** | 改为 `run_all`：「项数见 `ops/health.py` run_all 返回」 |
| 2 | `ops/health.py`（原 _self_check.py） | 文件存在；_self_check.py shim 从 ops.health 导入 run_all/check/warn | ✓ | — |
| 3 | `ops/health.py` 的 morning task 提示 | ops/health.py:269 `_morning_found` 段 | ✓ | — |
| 4 | `auto_heal.py` | 文件存在（d914-47 域） | ✓ | — |
| 5 | `core/pipeline.py` DAG 注册表 | :35 `PIPELINE_STEPS = {` | ✓ | — |
| 6 | `core/llm.py` | 文件存在 | ✓ | — |
| 7 | `core/config.py`（v7.6 标注） | 文件存在；「v7.6」版本字样与现状是否一致未深究（文档口径，非符号） | ✓（文件级） | 版本字样建议日间顺手核 |
| 8 | `core/config.py` 的 `evolve_priority.*` | core/config.py:161 "evolve_priority" | ✓ | — |
| 9 | `bark_sender/channels.py` | 文件存在（渠道注册表） | ✓ | — |
| 10 | `bark_sender/config.py` 硬编码 token 回退 | 文件存在；_scan_hardcoded_bark_token（ops/health.py:39）即扫此文件 | ✓ | — |

对照表行数＝10＝第 1 步唯一化引用计数 ✓。

## 三、零改动自证

`git diff -- AGENTS.md ops/health.py` 输出为空 ✓。本单只读，不 push。

## 四、验收对照

- ✅ run_self_check 对照证据（AGENTS.md 一处＋引文一处 vs 代码零处，命令与命中行同段）。
- ✅ 对照表 10 行＝抽取计数 10，每条判定含依据。
- ✅ 至少对 run_self_check 给出可替换措辞（run_all）。
- ✅ 零改动；不 push。
