# quant 低覆盖模块真实补测批 A 报告（h912-04，2026-09-12 夜班）

任务：按根仓基线 `D:\code\docs\insights\quant-test-baseline-20260911.md` §四，取覆盖率升序前 3 个模块补 characterization 测试（零生产码改动）。

## 模块选择与不相交声明

- **选定**：`bark_sender/parsers.py`（12%）、`bark_sender/push.py`（23%）、`bark_sender/builders.py`（34%）。
- **排除 #1 rebalancer.py（9%）与 #7 trading_calendar.py（52%）**：基线标注资金相关「只列不改」，本单禁令「不写资金数值断言、不碰 S7 资金核心」→ 红线回避。
- **排除 #10 scripts/newbie_protection.py**：其他任务单认领的 scripts/ 新bie 升级链对象（基线 #10），本单不取。
- **与 h912-14（colony 域）不相交**：本单三个模块全在 `bark_sender/` 包，与 h912-14 的 colony 对象零交集；与 h912-10/h912-15（后续批 B）的选取需各自避开本单三模块。

## 覆盖率前后对比（命令原文在册）

```
前值：python -m pytest -q --cov=bark_sender.parsers --cov=bark_sender.push --cov=bark_sender.builders --cov-report=term
  builders.py  232 stmts  154 miss  34%
  parsers.py   155 stmts  136 miss  12%
  push.py       52 stmts   40 miss  23%
  （448 passed, 2 xfailed——一次跑带三个 --cov 等价记录三模块前值）

后值：同命令复跑
  builders.py  232 stmts   68 miss  71%   （+37pp）
  parsers.py   155 stmts   67 miss  57%   （+45pp）
  push.py       52 stmts    5 miss  90%   （+67pp）
```

## 新增测试（3 文件，23 条用例，全绿）

- `tests/test_bark_parsers_h912_04.py`（7 条）：报告表格板块列自动侦测双格式、缺日期→「未知」、缺文件→None、honest_eval 正则抽取、exit_advisor 缺今日文件→[]、pick 评分畸形→50 兜底。
- `tests/test_bark_push_h912_04.py`（7 条）：无 token→False（v8.7 契约）、mock 200+code 80000000→True、服务端错误码→False、HTTP 500→False、网络异常吞并→False、newbie bark 文件缺/解析。**全部 mock requests，零真实外发**。
- `tests/test_bark_builders_h912_04.py`（9 条）：空列表短路双模板、simple 风险三档映射（40/60/85）、摩擦成本附录缺文件→空串与 0 金额跳过（仅结构断言）、组合风控附录缺/有 risk_report.json、券商订单附录缺目录、tier 路由 beginner→simple / pro→standard（stub ETF 闸门）。

characterization 纪律：全部行为/结构断言，零资金数值断言（摩擦成本只验证行结构与 0 金额短路，不验算金额）。

## 全量回归

`python -m pytest -q`（含 cov 同跑输出）→ **471 passed, 2 xfailed, 0 failed**；班前同环境 448 passed → 通过数 +23，无新增失败（≥ 基线 439 达标）。

## git diff 自查

- 本单新增仅 3 个 `tests/test_bark_*_h912_04.py`（untracked，已精确路径提交）；生产码 0 改动。
- 工作树既有脏项（班前已在，本单未触碰）：` M README.md`、untracked `backup/ tmp/ docs/insights/refactor-* tests/test_characterization_multi_strategy.py tests/test_newbie_upgrade_chain.py .coverage`（步骤 1 留证）。

## 遗留问题

- rebalancer（9%）、trading_calendar（52%）：资金域，补测需先解禁「资金数值断言」或走双实现对照，本单红线回避。
- builders 剩余未覆盖：`build_bark_message_for_tier` 的 auto 分支附录接线、research 模板——可入批 B 候选。
- parsers 剩余：`parse_report_full` 异常编码文件、`_parse_daily_orders_buys`（需 ORDERS_DIR 夹具）。
