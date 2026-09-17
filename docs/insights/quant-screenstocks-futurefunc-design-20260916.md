# quant screen_stocks target_date 未来函数——影响评估＋修复设计（n916e-06）

- 班次：日间续班（用户令继续）
- **状态备注：本单与 n916d-17 同题**——完整设计材料已落盘 `docs/insights/quant-futurefunction-design-20260917.md`（本日 12:4x 提交）。本报告为交叉引用＋当前时点复核，零生产码改动

## 一、复现（命令在前，当前时点）

```
$ python -m pytest tests/test_strategy_core.py -q
.................x..    [100%]
19 passed, 1 xfailed in 1.47s
```

xfail 行：`test_screen_stocks_does_not_read_after_target_date`（tests/test_strategy_core.py:219-232，strict=True）——70 期 history、target_date=iloc[60]，断言 calc_rsi 仅见 61 行（as-of 截断），现实现读全量 ⇒ 失败＝xfail。**与 n916d-17 复现完全一致，状态未变。**

## 二、target_date 全部使用点（file:line）

| file:行 | 性质 |
|---|---|
| strategy.py:229-230 | 缺省赋值（history 日期 max） |
| strategy.py:231 | **仅日志打印**（唯一实际使用点） |
| :238-241 hist 构建、:285+ 指标段 | **无任何截断** ⇒ 影响样本集＝全量 history（未来函数实锤） |

## 三、修复设计（详见 n916d-17 报告 §三）

截断生效点＝`hist = hist.sort_values([...])`（:241）之后单点插入 `hist = hist[hist['日期'] <= pd.to_datetime(target_date)]`；「无截断 vs 有截断」定性对照——无截断：MA/RSI/量比/MACD 读到未来数据、次新股门按全期计数；有截断：全指标 as-of、次新门按 target_date 口径、回测数字整体改变（需重跑基线）。

**验收命令（修复落地后）**：`python -m pytest tests/test_strategy_core.py -q` ⇒ 原 xfail 转 pass（0 xfail）；随后全量回归＋回测基线重跑。

## 四、边界与拍板点

- 不改口径数值、不 apply（红线邻域：统计口径变更）；today_df 语义（target_date 早于 today 的调用方）需日间确认。
- `git diff --stat` 现存 4 文件＝班前遗留脏树（n916d-20 triage 在案），本班零新增生产改动，本单产物仅本报告。

——完。
