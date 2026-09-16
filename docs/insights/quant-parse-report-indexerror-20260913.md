# parse_report_full IndexError：补丁工件与测试锁定（d913b-41）

- **实况**：同缺陷已由 d913a-37（本日先行单）直接修复并落工作树（except 元组化 1 行），冻结 pin 用例同步改写为 characterization（test_parse_report_full_short_row_skipped）。本单按规格补齐工件：
- 补丁：`tmp/patches/parse_report_full-1line.patch`（即 a-37 落地改动的规范 diff；`git apply --check` 在 stash 还原的基线副本上通过 ✓）。
- 修复语义：列数不足短行在 `float(parts[3])` 处不再穿透 IndexError，落 has_sector=True 分支后被 `len(parts)>=12` 校验跳过（越界行=跳过该行，非空值填充）。
- 回归测试：`tests/test_bark_parsers_charac.py::test_parse_report_full_short_row_skipped`（先红后绿记录见 a-37 报告）；`-k parse_report_full` 相关用例全绿。
- 披露：本单与 a-37 属规划双批同题（同 h912-10/E02 源），以 a-37 为主交付，本单补补丁工件；未重复改生产码。
