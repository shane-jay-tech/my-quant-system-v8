# parse_report_full 短行 IndexError 修复记录（2026-09-13）

## 缺陷与修法

- 缺陷（h912-10 批B1 冻结，eb67614）：`bark_sender/parsers.py` parse_report_full 中 `float(parts[3])` 的 try 只捕 ValueError，列数不足的短行抛 IndexError 直接穿透，畸形报告行导致整个解析崩溃。
- 修法（最小改动 1 行）：`except ValueError:` → `except (ValueError, IndexError):`——短行落 has_sector=True 分支，随后因 `len(parts)>=12` 不满足被安全跳过；正常行（含板块/不含板块两格式）行为逐字不变。

## 先红后绿

1. 改前复现：`pytest tests/test_bark_parsers_charac.py::test_parse_report_full_short_row_raises_indexerror` → **1 passed**（冻结现行为=确实抛 IndexError）；
2. 修复 + 冻结用例改写为 characterization（`test_parse_report_full_short_row_skipped`：断言不抛、pick_date 正常、仅正常行入选）；
3. 全量：`python -m pytest -q` → **511 passed, 2 xfailed**（与修前总量一致，零回归）。

## 边界

- 不改资金/风控/回测计算行为（纯解析容错）；不 commit/push；未访问网络。
- 改动：bark_sender/parsers.py（1 行）+ tests/test_bark_parsers_charac.py（冻结用例转 characterization）
