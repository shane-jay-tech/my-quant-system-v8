# 「备注列整列空 → .str 崩」同类点全仓清点＋trade_analyzer 复现钉桩（916p-a1-006，2026-09-17）

## 一、复现证据（造数据片段与实测输出同段）

造数据（临时目录，非真实 real_trades.csv）：

```python
with open(os.path.join(d, 'real_trades.csv'), 'w', encoding='utf-8') as f:
    f.write('日期,代码,名称,方向,备注\n2026-01-01,510300,沪深300ETF,买入,\n')
df, n = ta._load_real_trades(d)
```

实测输出（未捕获，直接冒泡）：

```
实测异常类型: AttributeError
异常原文: Can only use .str accessor with string values, not floating
（trade_analyzer.py:17 '备注' 整列空 → read_csv 推断 float64 → .str 访问器抛出）
```

钉桩：tests/test_trade_analyzer_empty_remark_pin.py **1 passed**（`pytest.raises(AttributeError)`，docstring 注明修复后应改断言持仓保留）。全量 `python -m pytest -q` → **635 passed, 2 xfailed（failed=0）**。

## 二、全仓清点（命令与计数同段，表行数=命中数=23）

命令（Git Bash 等价于任务书 Select-String 管道）：

```
$ grep -rn '\.str\.contains(' --include='*.py' . | grep -vE 'fillna|astype' | grep -vE '^\./(tests|docs)/' | wc -l
23
```

对照（已修形态仅 2 处）：behavior_log.py:102（astype(str)）、bark_sender\formatters.py:262（fillna('').astype(str)，:260-266 防御样板）。

## 三、逐点判定表（23 行）

风险类：A＝输入列可整列空（真风险）／B＝上游来源必为 str 或有守卫（低风险）。

| # | 点位 file:line | 列 | 无 fillna/astype | 风险类 | 判定依据与建议 |
|---|---|---|---|---|---|
| 1 | trade_analyzer.py:17 | 备注 | 是 | **A** | real_trades.csv 用户可整列空＝本单实测炸点；建议补 fillna('').astype(str) |
| 2 | trade_analyzer.py:572 | notes(备注.dropna) | 是 | B* | :564 len==0 早退守卫；但整列空时炸于上游 :563（见下） |
| 3 | trade_analyzer.py:576 | 备注 | 是 | B* | 同上守卫覆盖 |
| 4 | trade_analyzer.py:597 | notes | 是 | B* | 同上 |
| 5 | trade_analyzer.py:601 | 备注 | 是 | B* | 同上 |
| 6 | trade_analyzer.py:632 | notes | 是 | B* | 同上 |
| 7 | app\pages.py:1198 | 备注(rt_df) | 是 | **A** | real_trades 直读展示路径，整列空即抛 |
| 8 | bark_sender\rebalancer.py:32 | 备注 | 是 | **A** | 调仓通知读 real_trades，同族 |
| 9 | exit_advisor.py:97 | 备注 | 是 | **A** | 同族（na=False 救不了 float64 dtype） |
| 10 | newbie_protection.py:336 | 备注 | 是 | **A** | 同族 |
| 11 | newbie_protection.py:351 | 备注 | 是 | **A** | 同族 |
| 12 | newbie_protection.py:369 | 备注 | 是 | **A** | 同族 |
| 13 | sim_trade.py:770 | 备注 | 是 | **A** | 同族 |
| 14 | strategy_feedback.py:272 | 备注 | 是 | **A** | 同族 |
| 15 | ops\health.py:217 | 备注 | 是 | **A** | 同族（健康检查路径，异常即误报健康） |
| 16 | multi_strategy.py:86 | 名称 | 是 | B | 名称来自行情 feed 必为 str |
| 17 | multi_strategy.py:250 | 名称 | 是 | B | 同上 |
| 18 | position_sizer.py:876 | 名称 | 是 | B | 同上 |
| 19 | position_sizer.py:907 | 名称 | 是 | B | 同上 |
| 20 | position_sizer.py:922 | 名称 | 是 | B | 同上 |
| 21 | strategy.py:245 | 名称 | 是 | B | 同上 |
| 22 | strategy.py:255 | 名称 | 是 | B | 同上 |
| 23 | enhanced_backtest.py:296 | 出场原因 | 是 | B | 回测内部生成列，必为 str |

*A 类合计 **10 处**（备注族＝真实用户 CSV 面，即原始定性的事故形态）；B 类 13 处。\*附注（清点外同族发现）：trade_analyzer.py:563 `notes.str.strip()` 在备注整列空时同样炸（float64 空 Series 无 .str）——炸点早于 :572 等 B* 行，属 A 族补刀点。

## 四、建议（修复留日间授权，本单只钉桩）

1. 统一防御形态：全部 备注 列 `.str` 前补 `fillna('').astype(str)`（样板＝bark_sender\formatters.py:262）；A 类 10 处＋:563 优先。
2. 上游修：`_load_real_trades` 读入即 `df['备注'] = df['备注'].fillna('').astype(str)`，下游 10 处可一次性消除。
3. 验收：钉桩用例改为断言「不抛错且持仓保留」，配合 formatters.py:262 既有形态回归。

## 五、验收对照

- ✅ 复现证据（造数据片段＋异常类型与原文同段）。
- ✅ 钉桩 1 passed；全量 635 passed/0 failed（命令与数字同段）。
- ✅ 清单表 23 行＝命令计数 23。
- ✅ 生产码零改动（trade_analyzer.py/formatters.py diff 空）；真实 real_trades.csv/data 零触碰（git status --porcelain 空）；不 push。
