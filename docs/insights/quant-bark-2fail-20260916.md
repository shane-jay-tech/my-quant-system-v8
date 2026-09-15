# quant bark 域 2 个班前既有失败：根因定位与修复落地（q916-03，2026-09-16）

## 一、终态

```
$ python -m pytest tests -q
590 passed, 2 xfailed, 12 warnings in 12.33s   （退出码 0，failed=0）
```

修复内容**此前已由前序班次备好在工作区（未提交）**：本单做的是根因定位＋复现实证＋最小集合落地提交（5 文件，见第四节），未新写一行修复码。

## 二、逐失败根因（各一句话＋证据）

**失败 A：`tests/test_bark_parsers_charac.py::test_parse_report_full_short_row_raises_indexerror` —— 测试断言过时。**
生产缺陷（短行 `float(parts[3])` 抛 IndexError）已由 d913a-37 修复（`bark_sender/parsers.py` except 改捕 `(ValueError, IndexError)`），但「真缺陷冻结」版测试仍断言崩溃 → 实跑复现：

```
$ git stash push -- <两个测试文件> && python -m pytest tests/test_bark_parsers_charac.py tests/test_bark_push_h912_04.py -q
E       Failed: DID NOT RAISE IndexError
FAILED tests/test_bark_parsers_charac.py::test_parse_report_full_short_row_raises_indexerror
1 failed, 14 passed in 2.27s
```

修复（工作区既有）＝断言重写为修复后行为：短行安全跳过、正常行 `600000` 照常解析。

**失败 B：bark 两个时敏测试（`test_send_from_newbie_file_parses_title_and_body`／`test_parse_exit_advisor_sells_reads_today_file_and_stops_at_next_section`）—— fixture 漏登记致冻结时钟静默失效。**
d914-30 给两测试注入 `frozen_clock`（冻结 2026-09-14），但 `tests/conftest.py` 的 `FROZEN_CLOCK_TARGETS` 漏登记 `bark_sender.parsers`／`bark_sender.push` → fixture 不 patch 任何东西，测试用冻结日拼文件名、被测码取真实日期（`parsers.py:128`／`push.py:53`）→ 冻结日之后任何一天必挂。根因自证（conftest.py 工作区注释原文）：

> 「2026-09-15 日间修复（根因）：d914-30 给 bark 两个时敏测试加了 frozen_clock，但漏登记本表 → fixture 静默不 patch 任何东西……→ 跨日必挂。」

修复（工作区既有）＝`FROZEN_CLOCK_TARGETS` 补登记两模块。本日 HEAD 版测试（真实时钟）复跑通过，与该根因自洽——失败 B 只在「冻结日≠当日」时复现，故今日以 HEAD 版无法直接复现，以 conftest 注释＋diff 为准证。

## 三、归因判定

| 失败 | 归因 | 依据 |
|---|---|---|
| A | 测试断言过时（生产已修、测试未同步） | 复现输出 DID NOT RAISE ＋ parsers.py diff 一行 |
| B | 时敏 fixture 漏登记（在途改动自带缺陷，9/15 日间已根修） | conftest diff 注释原文 ＋ 两测试 diff 的 frozen_clock 注入（d914-30 标注） |

两处均非环境问题；均未触碰任何价格/阈值/统计数值定义。

## 四、改动清单（git diff --stat，本单落地提交）

测试（3 文件）：
```
tests/conftest.py                 | 71 +++++++++（frozen_clock fixture＋FROZEN_CLOCK_TARGETS 补登记 bark 两模块）
tests/test_bark_parsers_charac.py | 19 ++++++-----（短行断言重写＋1 测试时钟冻结）
tests/test_bark_push_h912_04.py   |  4 +--（1 测试时钟冻结）
```
生产（2 文件，各 1 行，bark 域内）：
```
bark_sender/parsers.py            | 2 +-（except (ValueError, IndexError)，d913a-37 修复体）
bark_sender/formatters.py         | 2 +-（备注列 fillna('') 防 NaN，empty-remark-nan-repro-20260914.md 记录的缺陷）
```
合计 5 文件 86 insertions / 12 deletions。附带收益：conftest 入库后，今夜已提交的 d43e46e／a758e14（依赖 frozen_clock fixture 的两个测试文件）在全新 checkout 亦不再缺 fixture。

## 五、验收情况

- ✅ `python -m pytest tests -q` 退出码 0，failed=0（第一节命令与数字同段）。
- ✅ 每失败根因一句话＋证据（复现输出／diff／注释原文）。
- ✅ git diff --stat 测试与生产分别标注。
- 禁止事项：未改价格/阈值/统计数值定义、未 push、未装依赖、未顺手重构。

## 六、遗留问题

- 工作区仍有本单范围外的在途脏文件（auto_heal.py、data_loader.py、README、AGENTS.md、test_characterization_multi_strategy_main.py 及若干 untracked 测试/文档）——属其他任务，未动。
- 12 warnings 含 test_health_s4cd4 的 UnicodeDecodeError 线程告警（GBK 控制台解码），非失败，不在本单范围。
