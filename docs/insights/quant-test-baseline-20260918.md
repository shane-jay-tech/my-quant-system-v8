# 量化测试覆盖率基线快照（2026-09-19）

> 口径定版依据不变：`quant-test-baseline-20260915.md`（**位于根仓 `D:\code\docs\insights\`**）第一节四项默认——
> 口径 A ／ 快照按日期＋固定 A 口径 ／ `scripts/` 与 `tests/` 不纳入 ／ 门槛线 **82%**。
> 本快照由夜班 q918-23 产出，按任务书落在 **quant 仓 `docs/insights/`**（与前三份不同仓，见第五节的口径链风险）。

## 一、本次实测（2026-09-19 14:40，系统 python 3.12.9 / pytest 9.1.1 / coverage win32）

```
$ python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov-report=term
Name                        Stmts   Miss  Cover
-----------------------------------------------
bark_sender\__init__.py         6      0   100%
bark_sender\builders.py       232     21    91%
bark_sender\channels.py       113      2    98%
bark_sender\config.py          19      5    74%
bark_sender\formatters.py     213     19    91%
bark_sender\parsers.py        155      6    96%
bark_sender\push.py            52      2    96%
bark_sender\rebalancer.py      88     80     9%
multi_strategy.py             443     56    87%
-----------------------------------------------
TOTAL                        1321    191    86%
714 passed, 4 skipped, 3 xfailed in 33.83s
```

**TOTAL = 86%**（1321 语句 / 191 未覆盖）。门槛线 82% ⇒ **达标，缓冲 4 个百分点**（上次为 2 个百分点）。

⚠ 解释器口径：`.venv/Scripts/python.exe -m pytest` 在本仓**跑不起来**（`No module named pytest`，
`requirements.txt:27-28` 声明了 pytest 却没装进 `.venv`，详见 `quant-dryrun`/`q918-39` 报告）；
本快照数字来自系统 python。**生产日终流水线用的却是 `.venv`（`daily_pipeline.bat:5`）**——这条不一致与覆盖率无关，但会影响"谁能复跑本快照"。

## 二、与上一份 A 口径快照（20260915）逐项对照

| 文件 | 09-15 Miss/Cover | 09-19 Miss/Cover | Δ | 归因（本轮哪一单） |
|---|---|---|---|---|
| `bark_sender\channels.py` | 11 / 90% | **2 / 98%** | **−9 语句** | q918-34 渠道注册表钉桩 15 例（`tests/test_bark_channels_sign_charac.py`） |
| `multi_strategy.py` | 61 / 86% | **56 / 87%** | −5 语句 | q918-37 `StrategyVoter` 并列票型＋钩子 13 例 |
| `bark_sender\builders.py` | 21 / 91% | 21 / 91% | 0 | — |
| `bark_sender\formatters.py` | 19 / 91% | 19 / 91% | 0 | — |
| `bark_sender\parsers.py` | 6 / 96% | 6 / 96% | 0 | — |
| `bark_sender\push.py` | 2 / 96% | 2 / 96% | 0 | — |
| `bark_sender\config.py` | 5 / 74% | 5 / 74% | 0 | 未动 |
| `bark_sender\rebalancer.py` | **80 / 9%** | **80 / 9%** | 0 | **仍是全包最大黑洞**：88 语句只覆盖 8 条，占本次全部未覆盖数（191）的 **42%** |
| `bark_sender\__init__.py` | 0 / 100% | 0 / 100% | 0 | — |
| **TOTAL** | **205 / 84%** | **191 / 86%** | **−14 语句，＋2pp** | 两个文件的改动贡献了全部增量 |

`Stmts` 总数两份快照**完全相同（1321）** ⇒ 这 4 天里 `multi_strategy.py` 与 `bark_sender/*` 的**生产码规模零增长**，
提升全部来自测试侧。用例面：`581 passed / 2 xfailed`（09-15）→ `714 passed / 4 skipped / 3 xfailed`（09-19），收集数 +138。

## 三、xfailed 从 2 变 3 的说明（避免被误读成"退步"）

| 快照 | xfailed | 构成 |
|---|---|---|
| 09-15 | 2 | `screen_stocks` 未来函数 ＋ portfolio_risk 单持仓 `correlation=None` |
| 09-19 | 3 | **前者仍在**（`tests/test_strategy_core.py:219-222`，strict，故意保留为缺陷指针）；**后者已转正**（`736a778`／n916d-16）；**新增 2 条测试先行的期望桩**（q918-31 `tests/test_kb_missing_sentinel.py:40-43`，两个模块各一条，钉"KB_FILE 双缺失应告警"这一未实现期望） |
⇒ 明细与复现见 `docs/insights/quant-xfail-census-20260918.md`（q918-35）。4 条 skipped 也在那份里定性：
`FROZEN_CLOCK_TARGETS` 参数化的"该模块未登记 `date`"N/A 跳过，**不是缺口**。

## 四、门槛判定与下一步

- **达标**：86% ≥ 82%，且较上次 ＋2pp，不触发「不许退步」红线。
- 想再往上走，性价比最高的单点还是 **`rebalancer.py`（9%）**，但它是资金再平衡逻辑——
  按根配置属"改/测 buy-sell 决策"级，补测前需先解禁"资金数值断言"或由人工确认口径（沿用 2026-09-05 盘点与
  `h912-04-quant-cov-batch-a-20260912.md:46` 的同一判断，本快照不改这个结论）。
- `bark_sender/config.py` 74%、`builders/formatters` 91% 属可自然补齐的一档。
  `config.py` 那 5 条未覆盖全部落在 `_load_bark_tokens()`（def 在 `:22`，体到 `:31`）的分支里——
  该函数在 `:34` 于 **import 期只跑一次**，一次测试会话只会命中其中一条路径，其余分支结构性不可达。
  补齐方式很干净：monkeypatch `core.secrets.get_secret_list/get_secret` 的返回值后 `importlib.reload(bark_sender.config)`，
  **不需要读真实 `data/secrets.json`**（凭据域零触碰）。

## 五、口径链风险：这份快照放错了"仓库"

定版机制（`quant-test-baseline-20260915.md:13`）说「每份快照…按日期命名；`PLAN.md` 以最新一份为准」，
而 `PLAN.md:11` 指向的位置是 **根仓 `D:\code\docs\insights\`**，前三份（0911/0913/0915）也都在那里。
本单按任务书 `产出：docs/insights/quant-test-baseline-20260918.md（本仓 docs/insights/）` 落到了 **quant 仓**
⇒ 从 `PLAN.md` 的视角看，"最新一份"仍是 09-15 的 84%，**86% 这次提升不会被自动引用**。
处置建议（二选一，本单都不做）：① 把本文件挪/复制到根仓 `docs/insights/` 并保留此处为指针；
② 改 `PLAN.md:11` 的指向为 quant 仓。**别两边各留一份不同步的**——那正是今晚反复出现的"锚点手抄漂移"的成因。

## 六、复跑命令

```
cd /d/code/my-quant-system-v8
python -m pytest -q --cov=multi_strategy --cov=bark_sender --cov-report=term
# 末行 TOTAL 与门槛 82% 比较；本份应为 86%（1321 / 191）
```

> 脱敏：本文档不含任何密钥或凭据；`bark_sender/config.py` 的未覆盖 5 条与 token 读取有关，本文只报覆盖数，不涉值。
