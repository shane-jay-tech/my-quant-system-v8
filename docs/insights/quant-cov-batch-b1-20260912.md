# quant 补测批 B1 报告（h912-10，2026-09-13 夜班）：parsers 畸形容错＋formatters 格式化边界

任务：基线 §四 第 2/5 行两模块特征化补测（零生产码改动）。两测试文件与 h912-04 产出（test_bark_parsers_h912_04.py 等）案例面不重叠。

## 覆盖率前后（原值与新值并列）

```
python -m pytest -q --cov=bark_sender.parsers --cov=bark_sender.formatters --cov-report=term
前值：formatters 213 stmts 104 miss 51%   parsers 155 stmts  67 miss 57%（基线原值 34% / 12%，其中 parsers 已被 h912-04 提到 57%）
后值：formatters 213 stmts  59 miss 72%   parsers 155 stmts  19 miss 88%
```

## 新增测试（2 文件 21 条，全绿）

- `tests/test_bark_parsers_charac.py`（8 条）：空文件截断容错、无效 UTF-8 编码异常传播、**短行 IndexError 真缺陷冻结**（见下）、ORDERS_DIR 缺失 FileNotFoundError 冻结、空目录→[]、买入行千分位价格＋非买入/节外行跳过、exit_advisor 今日文件节解析与 ## 截断、短行评分跳过。
- `tests/test_bark_formatters_charac.py`（13 条）：全空字段回退句、均线多头分支、大数量比（999）大资金分支、RSI 黄金区间、负涨幅不产涨幅点、强趋势/MACD 信号追加、信号点截断规则（[:4]）、回顾三分支＋±.2f 大数格式化、零候选不崩溃、梯队 97/94 阈值＋电力集中度≥3、风控四象限（小/大资金×强熊/常态）、real_trades.csv 缺失/损坏容错。

用例名与基线补测点对应：截断→parsers 畸形容错；编码异常→同；字段缺失→同；大数/负数/空值→formatters 格式化边界（各用例名可见）。

## 全量回归

`python -m pytest -q` → **495 passed, 2 xfailed, 0 failed**（h912-09 后 474 + 本批 21）。

## 真缺陷发现（禁止条款：只记录不改码）

**parsers.parse_report_full 对列数不足的短行抛 IndexError**（`float(parts[3])` 的 try 只捕 ValueError，IndexError 直接穿透）——畸形报告行会让整个解析崩溃。已用 `test_parse_report_full_short_row_raises_indexerror` 冻结现行为，修复建议：except 捕获 `(ValueError, IndexError)` 或行先验列数校验，留日间。

## 遗留问题

- 上节 IndexError 容错缺口（修复=1 行，待授权批次顺带）。
- formatters 剩余未覆盖：build_personalized_section 持仓汇总主体（需构造 real_trades.csv＋stock 行情夹具，体量大留批 B2）、build_tomorrow_guide 的 max_consecutive_loss 行。
- parsers 剩余：_parse_exit_advisor_sells 的畸形数值行（float 解析失败穿透）。
