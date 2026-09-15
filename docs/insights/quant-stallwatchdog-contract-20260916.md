# stall_watchdog 其余公开函数契约 docstring＋边界用例（q916-05，2026-09-16）

- 范式上游：q914-33（weekdays_between 四条显式语义＋5 边界用例＋零逻辑改动）。
- 其余公开函数清点：`weekdays_between` 之外仅 **`parse_yyyymmdd`** 与 **`main`** 两个无下划线公开函数（`_is_holiday`/`_is_trading`/`_latest_date` 为私有不入本单）。

## 一、补钉的契约 docstring（零逻辑改动自证）

```
$ git diff -- stall_watchdog.py | grep -c '^-[^-]'
0        （删行=0，仅 +24 行 docstring）
```

- `parse_yyyymmdd`：参数=YYYYMMDD 串；边界=无位数预校验（短串在 int('') 抛 ValueError）、月日越界由 date() 构造抛 ValueError；返回=date 无第三态；异常=ValueError 一律上抛。
- `main`：参数=argv `--dry-run`/`--threshold`（默认 2）；边界=参照日退化链（stock 缺失→最近交易日，故「无 stock csv」返回 1 分支实际不可达、防御保留；logs+orders 全缺→返回 1；日历三级退化）；返回=0（OK 或 dry-run 未推送）/1（无活动记录），不返回 None；异常=非 dry-run STALL 分支才 import bark_sender，推送异常不捕获上抛。

## 二、新增边界用例（tests/test_stallwatchdog_contract.py，每函数 ≥2）

| 函数 | 用例 | 钉住的边界 |
|---|---|---|
| parse_yyyymmdd | test_parse_yyyymmdd_roundtrip_valid | 正常 8 位 roundtrip |
| parse_yyyymmdd | test_parse_yyyymmdd_invalid_calendar_day_raises | 20260230 → ValueError |
| parse_yyyymmdd | test_parse_yyyymmdd_short_string_raises | 短串 int('') → ValueError |
| main | test_main_no_activity_returns_1 | logs+orders 全缺 → 1 |
| main | test_main_stalled_dryrun_returns_0_without_push | STALL＋--dry-run → 0 且 alert NOT sent（bark 桩防御） |
| main | test_main_ok_returns_0 | 活动日=参照日 → lag 0 → OK 返 0 |

main 用例以 sys.modules 桩隔离 `utils.trading_calendar`（get_trading_days 恒返 None → 内置表退化路径），零网络零盘上依赖。

## 三、验收证据（命令与数字同段）

```
$ python -m pytest tests -q -k stallwatchdog
...........                                                              [100%]
11 passed, 587 deselected in 1.67s        （=原 5 ＋ 新增 6 ✓）

$ python -m pytest tests -q
596 passed, 2 xfailed, 12 warnings in 11.41s   （failed=0，无新增失败 ✓）
```

- 语义分歧检查：两函数 docstring 均可唯一确定行为，无分歧点，不触发 partial 条款。
- 禁止事项：未改函数逻辑（删行 0 自证）、未改既有断言（test_stallwatchdog.py 未触碰）、不 push、不装依赖。
