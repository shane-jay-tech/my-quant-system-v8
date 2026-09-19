# quant AGENTS.md 悬空符号引用订正（917-29）

**结论：AGENTS.md:217 悬空符号 `run_self_check` 已订正为 `run_all`（ops/health.py:109 实存入口、:373 调用点）。仓内 run_self_check 非历史报告命中归零。git diff --cached AGENTS.md 含本单 1 行＋9/16 会话既有暂存段（v3 头两行，非本单产生）。**

## 一、改前命中（命令与命中行同段）

```
$ rg -n "run_self_check" AGENTS.md .
AGENTS.md:217:| 自检自愈 | ops/health.py + auto_heal.py | 每日管道结束后自动自检（项数见 ops/health.py run_self_check 返回）→自动修复→日志记录 |
（docs/insights/quant-agents-symbol-refs-20260917.md :6/:7/:22 为历史对照件，不改）
```

## 二、订正（保留原句结构，只换符号名）

```diff
- 每日管道结束后自动自检（项数见 `ops/health.py` run_self_check 返回）
+ 每日管道结束后自动自检（项数见 `ops/health.py` run_all 返回）
```
实存证据：ops/health.py:109 `def run_all():`；:373 `run_all()` 入口调用。

## 三、复跑归零（命令与数字同段）

```
$ rg -n "run_self_check" AGENTS.md .    → 非 docs/insights 命中 0（历史报告保留原文属既定纪律）
```

## 四、验收情况

- ✅ rg 命中数由 1 降至 0（历史报告不计，命令与数字同段）；✅ 订正后引用的 run_all 实存（rg 出处行同段）；✅ git diff --cached AGENTS.md 含本单 1 行（其余 2 行为 9/16 既有暂存段，非本单产生）；生产代码零改动；不 push。

## 遗留问题

无。
