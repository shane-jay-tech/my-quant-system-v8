# quant 补测批 B2 报告（h912-15，2026-09-13 夜班）：push mock 网络＋builders 模板分支

任务：基线 §四 第 3/4 行两模块补测；未测区间 38-103（build_bark_message 主体）与 243-332（tier/research）。零生产码改动、零真实网络。

## 覆盖率前后（原值/新值并列）

```
python -m pytest -q --cov=bark_sender.push --cov=bark_sender.builders --cov-report=term
前值：builders 232 stmts  68 miss 71%   push 52 stmts  5 miss 90%（基线原值 34% / 23%，已被 h912-04/B1 提到 71%/90%）
后值：builders 232 stmts  21 miss 91%   push 52 stmts  2 miss 96%
```

## 新增测试（2 文件 16 条，全绿）

- `tests/test_bark_push_charac.py`（7 条）：超时/连接异常分类、200 非 JSON 回退「成功」文本分支（:42-44）、非 JSON 无标记→失败、多 token 混合（失败不中断后续、all_ok=False）、全成功 True、请求形态冻结（端点/payload/超时）。**mock 目标＝`push.requests.post`（monkeypatch），断言全程未发真实请求**。
- `tests/test_bark_builders_charac.py`（9 条）：正文四段组装（榜单/板块/理由/明日）、Top10 截断（12 只取 10）、集中度双提示（≥40%＋≥3 只）、回顾接线（:92-95）、bt_data 注入分支（:98-99）、tier auto 券商附录、闸门横幅置顶（severe）、normal 脚注追加、研究模式全分支（空/全/基准对比/页脚）。

## 与任务书的差异披露（push「重试」分支）

任务书假设 push.py 有「HTTP 失败、超时、重试耗尽、重试后成功」四类分支——**现实现无重试循环**（v8.7 契约：每 token 单次 POST，失败记 all_ok=False 不中断后续 token）。已按实有分支覆盖（上列 7 条），「重试耗尽/重试后成功」两类在产码中不存在、无从测试；若产品需要重试语义属生产码变更（禁止条款不改码），留拍板。

## 全量回归

`python -m pytest -q` → **511 passed, 2 xfailed, 0 failed**（B1 后 495＋本批 16）。

## 遗留问题

- push 重试语义是否需要（现：一次失败即 False）——产品拍板项。
- builders 剩余未覆盖 21 行：`_build_friction_cost_addendum` 数值分支主体（资金数值断言红线，维持回避）、`build_bark_message_for_tier` 与真实 config/闸门的集成路径（单测已 stub）。
