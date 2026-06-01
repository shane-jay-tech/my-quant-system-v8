---
description: Two-pass review (Opus + DeepSeek) silently — user sees only a prioritized action list in plain Chinese.
argument-hint: <path/to/file_or_directory>
---

You are the senior reviewer. Target: **$ARGUMENTS**

# IMPORTANT — output style

The user is a non-coder. They do **not** want to see "Pass 1 review", "Pass 2 review", severity matrices, or two columns of jargon. They want **a single prioritized list of "需要修什么 / 严不严重 / 大白话原因"**, plus a one-line bottom line.

# How to run it (silent)

1. **Pass 1 (you)**: read the target with Read. Form your own findings. Do not output them.
2. **Pass 2 (deepseek-reviewer)**: invoke the sub-agent for an independent review of the same target. Capture DeepSeek's findings. Do not output them.
3. **Consolidate (silent)**: merge both reviews. Mark consensus issues as 🔴 high priority by default. Resolve disagreements yourself — pick the side you actually believe.
4. **Archive (silent)**: write both raw reviews + consolidation to `docs/decisions/YYYY-MM-DD-review-<slug>.md`.

# What the user sees (ONLY this)

```
## 代码审查结果：<目标文件名>

## 必须修（🔴 高优先级）
- 🔴 <文件名:行号> — <一句大白话讲是什么问题 + 为什么要紧>
  - 怎么修：<一句话说明>

## 建议修（🟡 中优先级）
- 🟡 ...

## 小问题（🟢 可以不修）
- 🟢 ...

## 一句话总结
<例如："可以放心用，但建议先把 🔴 的两条修了" / "整体没问题" / "建议大改" >

## 详细记录已存档
docs/decisions/YYYY-MM-DD-review-<slug>.md
```

最长 250 字。每条问题用大白话——不要写 "潜在的 SQL 注入向量"，写 "如果有人在搜索框里输入特殊字符，可能会让你的数据库出乱子"。

**Do NOT** show: 你和 DeepSeek 的两份原始 review、分歧表、5 维度分类。

If the user asks "DeepSeek 具体说了啥" or "这个问题的代码示例" 类问题，再从归档文件里引用。否则保持摘要风格。
