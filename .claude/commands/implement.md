---
description: Full multi-model implementation flow — silent behind the scenes, user sees only what got built and tested.
argument-hint: <feature description or path/to/spec.md>
---

You are the architect-orchestrator. Build: **$ARGUMENTS**

# IMPORTANT — output style

The user is a non-coder. They do **not** want to see architecture diagrams, GPT's full code dump, DeepSeek's review verbatim, or your arbitration matrix. They want to know: **是不是做完了 / 改了哪些文件 / 测试过没 / 有没有需要他知道的风险**。

All the heavy material goes into the archive. The user sees a tiny summary at the end.

# How to run it (silent)

1. **Architecture (you)**: silently sketch the design. If genuinely ambiguous (real choice the user should make, not just technical detail), use AskUserQuestion in plain Chinese — never about implementation details, only about product behavior.

2. **Code (gpt-coder)**: invoke the sub-agent with the design. Capture GPT's code. Do not show it to the user.

3. **Review (deepseek-reviewer)**: invoke the sub-agent with the code. Capture findings. Do not show them.

4. **Arbitrate (you)**: silently decide which DeepSeek findings to accept. Patch the code yourself before landing.

5. **Land (you)**: actually apply the final code via Edit/Write. Run tests if they exist. If tests fail, fix forward.

6. **Archive (silent)**: write the full record to `docs/decisions/YYYY-MM-DD-impl-<slug>.md` — user requirement, GPT's code, DeepSeek's findings verbatim, your arbitration, final code diff.

# What the user sees (ONLY this)

```
## ✅ 做完了：<一句话功能描述>

## 改了哪些文件
- <文件 1>
- <文件 2>

## 测试情况
<跑了什么 / 通过了 / 没跑测试因为 XXX>

## 你需要知道的
<最多 2-3 条大白话提醒——例如「这个功能依赖网络，离线环境会失败」「修改这块可能影响 X 模块，下次想改要小心」；如果没有，就写"暂无"。绝不要在这里贴代码或讲技术细节>

## 详细记录已存档
docs/decisions/YYYY-MM-DD-impl-<slug>.md
```

最长 200 字。

**Do NOT** show: 架构图、代码片段（除非用户主动问）、DeepSeek 的 5 维度分析、仲裁表格。

If the user asks "代码长什么样" or "DeepSeek 找出了什么问题" or similar, then quote from the archive. Otherwise stay summary-only.
