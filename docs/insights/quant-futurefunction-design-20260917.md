# quant xfail② screen_stocks 未来函数修复方案材料（n916d-17，零改码）

- 班次：sweep-20260916-2300（9/17 08:0x 段）
- 结论：未来函数实锤——`target_date` 目前**只用于日志打印**，历史数据（hist）从不按其截断，MA/RSI/量比等指标读到 target_date 之后的数据；修复＝hist 按 `日期 <= target_date` 截断（diff 草案在案）；**因回测数字全面变化＋涉及统计口径，不建议夜间落地，留日间评审拍板**

## 一、复现（命令在前，原样输出）

```
$ python -m pytest tests/test_strategy_core.py -q
.................x..    [100%]
19 passed, 1 xfailed in 1.47s
```

xfail 用例（tests/test_strategy_core.py:219-232，strict=True，reason「screen_stocks 的 target_date 目前只用于日志，没有截断历史数据，存在未来函数」）：构造 70 期 history，target_date=iloc[60]；monkeypatch calc_rsi 记录每次收到的 close 长度；断言 `seen_lengths == [61]`（即只读到 target_date 当日）——现实现读到全量 70 期，断言失败＝xfail。

## 二、定位（file:行）

- `strategy.py:222` `def screen_stocks(today_df, history_df, target_date=None, ...)`；
- `:229-230` `if target_date is None: target_date = history_df['日期'].max()`；
- `:231` `print(f"[STRATEGY] Screening for date: {target_date}")`——**target_date 唯一使用点＝日志**；
- `:238-241` `hist = history_df.copy(); ...; hist = hist.sort_values(['代码','日期'])`——**无任何按 target_date 的截断**；
- `:285+` 指标段对 `stock_hist`（＝hist 全量子集）计算 MA/RSI 等 ⇒ 读到未来数据。

## 三、最小改法（diff 草案，不落地）

```diff
--- strategy.py（:241 hist 排序行之后）
     hist = hist.sort_values(['代码', '日期'])
+    # 未来函数修复（n916d-17 草案）：历史窗口按 target_date 截断（含当日），
+    # 指标与新股门均按 as-of 口径；today_df 由调用方保证为 target_date 当日快照
+    _td = pd.to_datetime(target_date)
+    hist = hist[hist['日期'] <= _td]
```

单点插入、不改任何指标公式/阈值/参数；`pd.to_datetime` 与上方 hist['日期'] 的转换口径一致。

## 四、影响面（逐条，标「需日间确认」）

1. **回测/选股数字会变**：MA/RSI/量比/MACD 全部按截断窗口重算，历史回测结果整体改变（这正是修未来函数的预期代价）——【需日间确认】是否接受口径切换并重跑全部回测基线。
2. **新股门变化**：`hist_counts < 60`（:236 一带）在截断后按 as-of 计数，次新股判定与现行为不同——【需日间确认】。
3. **today_df 语义**：截断只管 hist；`today_df` 须由调用方保证＝target_date 当日快照。若存在 target_date 早于 today 日期的调用方，其 today_df 含未来数据，本草案不覆盖——【需日间确认】是否在函数内加 `today 日期 == target_date` 断言或告警。
4. **需重跑用例**：tests/test_strategy_core.py 全件（19 用例）、test_risk_consistency_end_to_end.py、以及任何调用 screen_stocks 的回测/流水线脚本。
5. **xfail 解除条件**：本草案落地后 `test_screen_stocks_does_not_read_after_target_date` 自动转正（seen_lengths==[61] 满足）；届时移除 xfail 装饰器并入正测。

## 五、不建议夜间落地的理由

回测数字全面变化＝统计口径变更，触及红线邻域（资金与统计数值计算），且 today_df 语义确认（影响面 3）未闭环。夜间单边落地会静默改变全部历史回测口径——**留日间评审拍板后按草案执行**。

## 六、零落码证据

本班在 quant 仓零新增代码改动（本报告为唯一产物）；`git diff --stat` 现存 4 文件（AGENTS.md/README.md/auto_heal.py/data_loader.py）均为此前班次遗留脏树（n916d-16 报告 §四已登记），非本单产物。

——完。
