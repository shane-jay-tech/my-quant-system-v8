# quant 时敏 fixture 第二组落地：multi_strategy_main（q916-06，2026-09-16）

- 上游：q914-34 附录第②组点名 `tests/test_characterization_multi_strategy_main.py:36,52,56` today 同形态；共享夹具＝conftest `frozen_clock`（d913b-36 建档，q916-03 已入库提交）。
- **发现**：第②组改造在工作区已由 d914-06 备好（未提交）——本单做的是核对夹具复用、回归验证与落地提交，未新造第二套夹具。

## 一、改造内容（工作区既有，本单核验）

1. `_write_today_stock(data_dir, today=None)`／`_write_history(data_dir, days=40, today=None)`：today 由调用方显式传入（默认保留真实日），消除构造数据与被测码读时不一致。
2. `test_main_runs_with_minimal_data`／`test_mid_low_tier_strategies_instantiable_and_runnable`：注入 `frozen_clock('2026-09-14 12:00:00')`（共享夹具，复用非新造）＋ today='20260914' 显式传参——two-side 冻结（数据构造与 multi_strategy 模块读时一致，FROZEN_CLOCK_TARGETS 已登记 multi_strategy）。
3. 新增 `test_write_today_stock_cross_midnight_no_date_bleed`：23:59:59 与 00:00:01 两探针，文件名不串日（q914-34 附录骨架的落地形）。

## 二、验收证据（命令与数字同段）

```
$ python -m pytest tests/test_characterization_multi_strategy_main.py -q
....                                                                   [100%]
4 passed in 1.49s      （退出码 0；改前 HEAD 3 条全数保留，+1 条跨午夜新增，无用例丢失）

$ python -m pytest tests -q
596 passed, 2 xfailed, 12 warnings in 11.32s    （failed=0）
```

## 三、改动仅限测试文件与共享夹具

- 本单提交：tests/test_characterization_multi_strategy_main.py（测试文件）＋本报告。共享夹具 conftest.py 已随 q916-03（e370c36）先行入库，本单零改动。
- 生产代码零改动：`git diff --stat -- multi_strategy.py` 为空；未碰资金计算；不 push。
