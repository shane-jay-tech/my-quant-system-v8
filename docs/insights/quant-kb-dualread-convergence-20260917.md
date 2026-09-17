# quant KB 双读过渡收敛设计（n916d-19，c453/1ace16e 后续，零落码）

- 班次：sweep-20260916-2300（9/17 08:1x 段）
- 结论：双读回退点**仅 2 处**（evolve/integrate 各一个 `_read_kb_content`），收敛面小而清晰；收敛＝删两处回退分支＋文案更新，单 commit 可回退；**切换属行为变更（KB_FILE 缺失时由静默回退变为空内容），需日间拍板**

## 一、KB 读取点清单（命令在前）

```
$ grep -n "KB_FILE\|quant-kb\|双读\|CLAUDE_MD" core/paths.py evolve_strategy.py integrate_knowledge.py scripts/dedup_claude_md.py CLAUDE.md
```

| file:行 | 角色 | 源 |
|---|---|---|
| core/paths.py:25 | `KB_FILE` 单源常量＝docs/knowledge/quant-kb.md | 新源定义 |
| evolve_strategy.py:38-47 `_read_kb_content` | **双读**：KB_FILE 优先；缺失回退 CLAUDE.md 旧节（stderr 提示） | 回退点① |
| evolve_strategy.py:79-82 / :461-475 | 写 KB_FILE／标记实验状态（:461 缺失即 return） | 已新源 |
| integrate_knowledge.py:195-207 `_read_kb_content` | **双读**：同款回退（:207 stderr 提示） | 回退点② |
| integrate_knowledge.py:215-218 | 写 KB_FILE＋去重基线双读（调 _read_kb_content） | 已新源 |
| scripts/dedup_claude_md.py:42/71 | 读写 KB_FILE | 已新源 |
| CLAUDE.md:14 | 指针行（指令层，声明已迁＋过渡期双读） | 指令 |
| evolve_strategy.py:24 / integrate_knowledge.py:26 | `CLAUDE_MD` 常量（仅作回退源引用） | 旧源遗留 |
| evolve_strategy.py:491 | 日志文案「Reading CLAUDE.md knowledge base...」 | 文案过期 |

## 二、收敛步骤（前置/步骤/验证/回退）

**前置条件**（全满足才动手）：
1. KB_FILE 存在且含 `[待验证]` 条目（现网已满足：evolve/integrate 写路径 1ace16e 起全落 KB_FILE）；
2. CLAUDE.md 旧节已指针化（已满足，:14）；
3. 观察窗口内 stderr 零「回退读取 CLAUDE.md 旧节」提示（回退从未真实触发）——【需日间确认】取最近 2–3 次运行的日志佐证。

**切换步骤**（单 commit）：
1. 删 evolve_strategy.py `_read_kb_content` 的 CLAUDE.md 回退分支（:43-47）→ KB_FILE 缺失直接 `return ''`；
2. 同删 integrate_knowledge.py 回退分支（:203-208）；
3. 清理两文件 `CLAUDE_MD` 常量与 :5/:7/:491 等处「CLAUDE.md 知识库」文案→改指 docs/knowledge/quant-kb.md；
4. CLAUDE.md:14 指针行去掉「过渡期双读」字样。

**验证命令**：
```
python -m py_compile evolve_strategy.py integrate_knowledge.py
grep -c "回退读取" evolve_strategy.py integrate_knowledge.py   # 期望 0 0
grep -c "CLAUDE_MD" evolve_strategy.py integrate_knowledge.py  # 期望 0 0
python -c "from core.paths import KB_FILE; import os; print(os.path.exists(KB_FILE))"  # True
```

**失败回退**：`git revert <收敛commit>`（单 commit 单职责，回退即恢复双读过渡态）。

## 三、「双读告警」可选方案（不落地）

现 stderr 提示已是告警形态（回退真实发生时必现一行）。可选升级：收敛前每次运行统计回退内容行数打 `[WARN] dual-read active: CLAUDE.md fallback <N> 行`——收益有限（现网回退从未触发），**建议不升级**，直接保留 stderr 待拍板后收敛。

## 四、拍板点（显式）

删回退分支＝行为变更：KB_FILE 意外缺失时，系统从「静默回退旧源」变为「读空＋后续写重建」——风险方向是安全的（旧源已指针化无内容可退），但失败模式改变，须日间拍板。建议拍板通过后按 §二单 commit 落地并同夜观察 evolve 全流程。

——本单零落码：KB 数据层、过渡代码零改动；唯一产物为本报告。
