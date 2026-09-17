# quant xfail① generate_risk_report correlation=None 崩溃最小修复（n916d-16）

- 班次：sweep-20260916-2300（9/17 08:0x 段）
- 结论：**修复落地——目标文件 22 passed 零 xfail（改前 19 passed＋1 xfailed）**；全量 663 passed / 4 skipped / 1 xfailed（残留 xfail 在 test_strategy_core.py 既有件，数不增）/ **0 failed**；diff 仅防御分支＋测试，零公式/阈值改动

## 一、改前复现（命令在前）

```
$ python -m pytest tests/test_portfolio_risk.py -q
..................x.    [100%]
19 passed, 1 xfailed in 2.02s
```

xfail 用例 `test_generate_report_supports_single_position`（:202-215，strict=True）：单持仓 state ⇒ `generate_risk_report` 内 `report.get('correlation', {}).get('warning')`（portfolio_risk.py:291）——correlation **key 存在且值为 None** 时 `dict.get` 的默认 `{}` 不生效，`None.get('warning')` 抛 AttributeError＝崩溃形态。

## 二、修复（逐行标注，仅防御分支）

`portfolio_risk.py:291`：

```diff
-    if report.get('correlation', {}).get('warning'):
+    # correlation=None（单持仓/无数据）时 dict.get 的默认 {} 不生效——or {} 兜底
+    # （n916d-16 最小修复：只防空，不改任何数值口径）
+    if (report.get('correlation') or {}).get('warning'):
```

语义：`or {}` 同时兜住「键缺失」与「键存在值为 None」两种态；告警分支（correlation 非 None 时）行为逐字节不变——无数值计算、阈值、统计定义改动；VaR/CVaR、换手、回撤、波动各段零触碰。

## 三、测试改造（xfail 转正＋2 边界用例）

```
$ python -m pytest tests/test_portfolio_risk.py -q
......................    [100%]
22 passed in 1.30s        （19→22：xfail 转正 1＋新增 2；xfail 数 1→0）
```

1. `test_generate_report_supports_single_position`：**xfail 装饰器移除转正**（断言原样：correlation is None、actions==[]）＝「单持仓」边界。
2. `test_generate_report_empty_positions`（新增）：空持仓列表 ⇒ correlation=None、零崩溃＝「相关性缺失」边界·空态。
3. `test_generate_report_correlation_calc_none`（新增）：双持仓但 `calc_correlation_matrix` 返回 None（monkeypatch）⇒ correlation=None、**不进 VaR/CVaR**、无相关性告警＝「相关性缺失」边界·计算空态。

## 四、全量回归

```
$ python -m pytest -q
663 passed, 4 skipped, 1 xfailed, 12 warnings in 27.69s
```

- failed=**0** ✓；xfail 数不增（改前全量同样 1 xfailed，位于 `tests/test_strategy_core.py` 既有件，与本单无关）✓
- `git diff --stat` 中本单仅 `portfolio_risk.py`（+4/−1，即上述防御分支）与 `tests/test_portfolio_risk.py`（+32/−4，转正＋新用例）；另见 AGENTS.md/README.md/auto_heal.py/data_loader.py 4 文件为**班前遗留脏树**（本班未触碰，data_loader.py 的 16 行改动非本单产物，留日间归属核验）。

## 五、红线声明

未改任何数值口径、阈值、统计定义；未碰持仓/下单/风控参数；不 push。

——完。
