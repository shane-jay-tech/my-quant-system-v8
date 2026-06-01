# 2026-08-24 — 数据完整率升级为逐交易日覆盖（Round 9）

## 元数据

- 任务类型：指标口径增强（goal_metrics 数据完整率）
- 难度评分：影响面 1 + 风险领域 0 + 歧义度 1 + 新颖度 1 + 不可逆性 0 + 长程影响 1 = **4 → L2**
- 模型：Flash quick 评审；Pro 本会话实施与复核。
- override：0
- 测试：pytest **302 passed / 2 xfailed**（基线 301，净增 1 个测试函数，但目标测试文件 17 项）；smoke 48/48；py_compile 通过
- API：本轮 Flash 0.0028 元；今日累计 6.96 元 < 20 元

## 原始需求

GOAL 验收要求「数据完整率」。旧口径只有最新 data_health 报告的加权快照（nonzero/volume），看不到某一天 stock 快照是否缺失。本轮加逐交易日覆盖：最近 5 个实际交易日，`data/stock_YYYYMMDD.csv` 是否都存在且行数 >= 4000。

## Flash 评审（verbatim）

同意。

补充风险：用 history.csv 的 distinct 日期作为“实际交易日”存在循环依赖——若 history.csv 本身缺了某个真实交易日（当天完全无记录），该日期就不会出现在期望列表中，导致 expected_days 偏小，覆盖率可能虚高。


## 采纳与风险处理

- 采纳。补充风险「history.csv 与 stock 文件名都不是独立交易日历，若两者都缺某天则无法发现」成立；实现上把期望日定义为 history.csv 日期 ∪ stock 文件日期，优先 history（持久），至少能发现「stock 快照丢失/不足但 history 仍在」的故障。两者都缺的场景只能靠流水线成功率与外部交易日历兜底，已记录为残留。
- 覆盖融合：coverage<80 → FAIL；<100 → DEGRADED；=100 才允许 OK。

## 修复

- `goal_metrics.py`：新增 `_collect_recent_trading_dates` / `_count_csv_rows` / `compute_data_coverage`；`compute_data_completeness(reports_dir, data_dir)` 融合快照与覆盖；报告新增 coverage_pct / expected / missing。
- 测试：`tests/test_goal_metrics.py` 新增完整/缺失两天场景；现有测试注入 `_ok_coverage` 隔离生产 data 目录。

## 实跑证据（2026-08-24）

`python goal_metrics.py` → 数据完整率 99.95% **OK**；coverage_pct=**100%**，expected=20260817..21，missing=无。
关键含义：20260818/19 的流水线虽被手动重跑截断、没生成 data_health 报告，但 `stock_20260818.csv` / `stock_20260819.csv` 都在且行数达标——**报告缺失 ≠ 数据缺失**，新口径把这两件事分开了。

## 风险

1. 期望日来自本地 history/stock 文件，两者都缺的交易日不可恢复（需要外部交易日历才能根治）。
2. 行数统计只数行数，不做列名/价格/成交量质量校验；质量仍由 data_health 快照负责，两者互补。
3. `_count_csv_rows` 假设 CSV 无多行字段；当前 stock csv 由系统生成满足该假设。

## 下一轮候选

- pytest 每日落盘接入测试通过率。
- 引入交易日历（若允许）根治缺失日发现。
- 强熊空仓端到端 dry-run。
