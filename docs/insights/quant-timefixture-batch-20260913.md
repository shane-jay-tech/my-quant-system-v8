# quant 时敏 fixture 规范化 + 三组高危补测（d913b-36，2026-09-13）

任务：conftest 增确定性时钟 fixture；按 0913-0510-06 遗留的三组高危未覆盖项各补 ≥3 条 characterization 用例；不改生产码。

## 一、fixture（tests/conftest.py 追加 `frozen_clock`）

- 工厂式用法：`frozen_clock('2026-09-13 23:59:59')` 冻结后返回 fixed datetime；探针时刻惯例 = `23:59:59`（翻转前）与次日 `00:00:01`（翻转后）。
- 机制：三靶点模块均为模块内 `from datetime import datetime(, date)` 直引，故做**模块级名字绑定替换**（FrozenDateTime/FrozenDate 子类，now/today 冻结、strftime/strptime/比较运算原生继承），monkeypatch 自动还原，不污染全局 datetime。
- 靶点注册表 `FROZEN_CLOCK_TARGETS`：newbie_protection(datetime)、multi_strategy(datetime)、position_sizer(datetime, date)。

## 二、三组高危项用例（tests/test_timefixture_characterization.py，19 项全绿）

**A 组 newbie_protection（today±days cutoff）**
- A1 学习访问 7 天 cutoff 边界翻转：访问日 09-06，时钟 09-13 23:59:59 → 计 1；09-14 00:00:01 → 计 0。
- A2 心理日记 cutoff **秒级边界**翻转：日记 09-07 00:00，cutoff 09-06 23:59:59 → 计 1；cutoff 09-07 00:00:01 → 计 0。
- A3 record_learning_visit 落盘日期 = 冻结 today（09-13 / 09-14）。

**B 组 multi_strategy（now() 打日期落盘）**
- B1 strategy_weights.json 历史 record date = 冻结日期（两探针各一）。
- B2 同进程跨午夜两次更新 → 记录日期 [09-13, 09-14] 各归各钟、不串档。
- B3 generate_comparison_report 报告头「生成时间」= 冻结日期。

**C 组 position_sizer（date.today() + trading-day 文件名日历）**
- C1 窗口零交易日 → 两时钟一致维持 last_regime。
- C2 窗口 2 交易日 ≥ hysteresis-1 → 两时钟一致真切档。
- C3 首次启动 candidate_first_seen_date = 冻结 today（午夜后换日写盘）。
- **C4 真·午夜翻转（timebomb 实证）**：candidate 首见 09-12、仅存在未来一天文件 stock_20260914.csv——23:59:59 时窗口 (09-12, 09-13] 空 → 维持 neutral；00:00:01 后窗口含 09-14 → 达标切 weak_bull。同一磁盘状态、结果随时钟翻转。

## 三、验收

- 两探针时刻时敏子集各跑一次：**58 passed 两次结果一致**；characterization 文件单独两跑 19/19 一致。
- 全量 `python -m pytest -q`：**544 passed + 2 xfailed，0 failed**。
- 新增用例 19（≥9 ✓）；生产码 diff=0；无资金数值断言；未联网。

## 四、风险清单（落盘）

| 模块 | 时敏面 | 风险 | 覆盖 |
|---|---|---|---|
| newbie_protection:306/:323 | cutoff=now-Ndays | 边界日数据午夜后消失（A1/A2 实证） | ✓ fixture 化 |
| newbie_protection:44/:289-296 | 记录打 today | 午夜跨日记录归错天（A3 实证） | ✓ |
| multi_strategy:505/:532/:632/:702 | now() 命名/落盘 | 报告与历史按换日错档（B1-B3 实证） | ✓ |
| position_sizer:94/:116-140 | today + 文件名日历 | **午夜达标切换**（C4 实证：23:59:59→neutral、00:00:01→weak_bull，同盘面） | ✓ |
| multi_strategy_main 测试 helper `_write_today_stock` | 测试侧 now() | 跨午夜日变（㊻f 既有教训） | 本批未动（属测试代码，留日间统一迁 frozen_clock） |
