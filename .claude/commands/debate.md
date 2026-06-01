---
description: Three-way debate behind the scenes — user only sees the final recommendation. Full debate archived to docs/decisions/.
argument-hint: <the question — e.g. "FastAPI vs Flask for this backend">
---

You are the architect-arbitrator. The question is: **$ARGUMENTS**

# IMPORTANT — output style

The user is a non-coder. They do **not** want to read the three models' outputs, the comparison tables, the technical jargon, or the arbitration matrix. They want **only the answer**, in plain language, with reasoning compressed to 1–3 short sentences.

All the heavy material (full sub-agent outputs, comparison, arbitration) goes into the archive file. The user sees a tiny summary.

# How to run it

## Step 1 — three-way parallel call (silent)

Invoke three sub-agents **in parallel** with the same question, different framings. Do not stream their outputs to the user. Capture them.

1. **gpt-coder** — *"Recommend the best option from a builder's perspective. Pick a side and explain in plain Chinese why, in 5 sentences max."*
2. **deepseek-reviewer** — *"Argue against the obvious choice. List the top risks of the popular option in 5 short bullets, plain Chinese."*
3. **kimi-researcher** — *"Compare the candidates in plain Chinese. Recommend one. Name the single most important factor that flips the answer."*

## Step 2 — arbitration (silent)

You weigh the three. Pick a winner. Note any DeepSeek warnings that the user should be aware of.

## Step 3 — archive (silent)

Write the **full** debate (all three sub-agent outputs verbatim + your full arbitration matrix) to `docs/decisions/YYYY-MM-DD-debate-<slug>.md`. This is the audit trail; the user can read it later if they ever want to.

## Step 4 — show the user (this is the ONLY thing they see)

Output exactly this format, in Chinese, no longer than ~150 words total:

```
## 结论
**<选项 A>**

## 为什么
- <一句话理由 1>
- <一句话理由 2>
- （可选）<一句话理由 3>

## 需要注意
<一两句话提醒未来什么情况下可能要改主意，用大白话；如果没有重要警告就写"暂无">

## 详细讨论已存档
docs/decisions/YYYY-MM-DD-debate-<slug>.md
（如果以后想看三个模型怎么吵的，可以打开这个文件）
```

**Do NOT** show:
- 三方对比表格
- 各模型的完整输出
- 「共识 / 真实分歧」分类
- 技术术语堆砌

If the user explicitly asks "把三方原话给我看" or similar, then read the archive file and show it. Otherwise stay summary-only.
