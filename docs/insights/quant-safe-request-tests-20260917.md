# fetch_stock_data.safe_request 重试/退避补测报告（916p-a1-005，2026-09-17）

## 验证（命令与数字同段）

```
$ python -m pytest tests/test_fetch_stock_safe_request.py -q
7 passed in 1.38s          ← <10s 证明 time.sleep 已打桩（否则 2+4+8s 真等）
$ grep -c -E 'https?://' tests/test_fetch_stock_safe_request.py → 1
$ grep -o -E 'https?://...' … → http://example.invalid/quote   （唯一假地址，零真实网络）
$ git diff -- fetch_stock_data.py → 空（生产码零改动）
$ python -m pytest -q → 634 passed, 2 xfailed（failed=0）
```

## 用例对照（7 条，≥6 达标）

| # | 断言 | 对应实现 |
|---|---|---|
| 1 | 首次 200 → 返回响应、恰调 1 次 | :49 短路 |
| 2 | 连续 500×3 → None、恰调 max_retries 次 | :47-53 |
| 3 | 403 → capsys 断言「[WARN] 403 Forbidden on <label>」 | :50-51 专用分支 |
| 4 | 502 → WARN 含状态码 | :52-53 通用分支 |
| 5 | get 抛 ConnectionError → [RETRY] 留痕、不上抛、耗尽 None、异常计入轮次 | :54-58 |
| 6 | max_retries=1 失败 → 只调 1 次即 None（即使第 2 次会 200） | :44 for 范围 |
| 7 | get_sina_headers/get_em_headers 含非空 UA+Referer | :18-37 |

## 实测重试口径

与 docstring/AGENTS.md 一致：异常分支与状态码分支同用 `2 ** (attempt+1)` 指数退避（异常分支额外 +random(0,1) 抖动，:56），耗尽返回 None。

## 遗留问题

无。
