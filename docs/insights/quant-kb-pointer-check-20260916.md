# quant KB 单源化后 CLAUDE.md 指针与双读过渡条件核验（n916x-19，只读）

**结论：本单与 n916d-19 的 quant-kb-dualread-convergence-20260917.md 同题（重复投单）——该报告已给出读取点全清单、双读回退点（仅 2 处）与收敛条件。本单以新鲜命令复核其结论仍成立：KB_FILE 单源常量唯一读取入口、旁路直拼＝0、旧源引用仅存于回退分支与文案。零改动。**

## 一、旧路径/新源引用清单（命令与数字同段；行数与 rg 命中一致）

```
$ rg -c 'KB_FILE|quant-kb' core/paths.py evolve_strategy.py integrate_knowledge.py scripts/dedup_claude_md.py CLAUDE.md tests/test_integrate_dedup.py
scripts/dedup_claude_md.py:4   evolve_strategy.py:13   integrate_knowledge.py:17
CLAUDE.md:1   core/paths.py:1   tests/test_integrate_dedup.py:6        （合计 42 行）
```
分类（逐条 file:line 全表见 n916d-19 报告§一，本单抽核未漂移）：
- **源码读取点**：core/paths.py:25（KB_FILE 单源常量）；evolve_strategy.py:30/:79-82/:461-475 与 integrate_knowledge.py:29/:196-207/:215-218/:264/:398-400（读写走 KB_FILE）；scripts/dedup_claude_md.py:42/:71。
- **文档表述**：CLAUDE.md:14（指针行）；两脚本 docstring/日志文案（evolve :37/:51/:82/:475、integrate :213/:266）。
- **旧源遗留**：evolve_strategy.py:24/:41-45 与 integrate_knowledge.py:26/:203（CLAUDE_MD 常量＋回退分支——双读过渡本体，收敛时删）；evolve :491 文案过期。

## 二、KB_FILE 唯一入口核验＋旁路清单

```
$ rg -n "open\(.*quant-kb|read_csv.*quant-kb|'docs/knowledge'" *.py core/ scripts/ tests/
  → 0 命中＝**旁路直拼路径清单为空**（全部读写经 core.paths.KB_FILE 常量）
$ python -c "from core.paths import KB_FILE; import os; print(os.path.exists(KB_FILE))"
  → True（docs/knowledge/quant-kb.md 在盘）
```
唯一非 KB_FILE 的 CLAUDE.md 读取＝两处回退分支（`open(CLAUDE_MD)`，evolve:42／integrate:203）——即双读过渡本体，非旁路。

## 三、收敛条件建议（何时结束双读过渡）

沿用 n916d-19 §二前置条件＋拍板点，本单复核现状：
1. KB_FILE 在盘 ✓（本单复验 True）；
2. CLAUDE.md 旧节已指针化 ✓（:14）；
3. 观察窗内 stderr「回退读取 CLAUDE.md 旧节」零触发——【仍需日间确认】取最近 evolve/integrate 运行日志佐证（磁盘无运行日志留存＝账面未记录，维持 n916d-19 的待确认状态）；
4. 收敛动作＝删两处回退分支＋CLAUDE_MD 常量＋过期文案，单 commit 可回退；**切换属行为变更（缺失时由静默回退变读空），须日间拍板后落地**。

## 四、验收情况

- ✅ 引用清单行数与 rg 命中一致（42 行，命令与数字同段）；✅ 旁路清单给出（0，附命令）；✅ 零改动未 push。

## 遗留问题

无新增。前置条件③的运行日志佐证与收敛拍板沿用 n916d-19 待办。
