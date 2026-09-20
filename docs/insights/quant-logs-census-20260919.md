# quant logs/ 与 logs/archive 归档现状普查（q920-12）

- 日期：2026-09-19｜仓库：D:\code\my-quant-system-v8
- 性质：**只读普查，零删除、零改动**
- 复跑命令（一条）：
  `python -c "import os,re,collections;from pathlib import Path;L=Path('logs');rows=[(p.relative_to('.').as_posix(),p.stat().st_size) for p in sorted(L.rglob('*')) if p.is_file()];print('archive_exists=',(L/'archive').exists());print('files=',len(rows),'bytes=',sum(s for _,s in rows));print(dict(collections.Counter(re.sub(r'\\d{8}','<date>',Path(n).name) for n,_ in rows)))"`

## 〇、一句话结论

**`logs/archive` 目录根本不存在**——任务书假设的「logs/archive 结构」在本仓没有任何实体，
也没有任何**代码**会创建或写入它。`logs/` 自身没有任何轮转/保留策略，日志只增不减；
但当前体量只有 **9 文件 / 20.5 KiB**，且 `logs/`＋`*.log` 已在 `.gitignore`（:28-29）里排除，**不构成现实风险**。
真正需要写下来的是：**`logs/pipeline_*.log` 有三个运行期消费者，谁想清理它必须先改代码**。

## 一、普查表（只读，复跑一致）

`logs/archive 存在 = False`

| # | 文件 | 字节 | mtime | 文件名日期 |
|---|---|---|---|---|
| 1 | `logs/maintenance_night.log` | 12,345 | 2026-09-19 21:00:05 | —（无日期后缀） |
| 2 | `logs/morning_20260917.log` | 1,129 | 2026-09-17 09:15:09 | 20260917 |
| 3 | `logs/morning_20260918.log` | 1,129 | 2026-09-18 09:15:12 | 20260918 |
| 4 | `logs/morning_20260919.log` | 174 | 2026-09-19 09:15:03 | 20260919 |
| 5 | `logs/morning_20260920.log` | 174 | 2026-09-20 09:15:03 | 20260920 |
| 6 | `logs/pipeline_20260917.log` | 1,652 | 2026-09-17 15:37:03 | 20260917 |
| 7 | `logs/pipeline_20260918.log` | 1,648 | 2026-09-18 15:37:03 | 20260918 |
| 8 | `logs/pipeline_20260919.log` | 600 | 2026-09-19 15:37:03 | 20260919 |
| 9 | `logs/weekly_health_20260920.log` | 2,189 | 2026-09-20 10:01:30 | 20260920 |

**合计：9 文件 / 21,040 字节 = 20.5 KiB = 0.020 MiB。**

| 维度 | 值 |
|---|---|
| 命名族 | `maintenance_night.log` ×1（无日期）／`morning_<date>.log` ×4／`pipeline_<date>.log` ×3／`weekly_health_<date>.log` ×1 |
| 文件名日期集合 | 20260917, 20260918, 20260919, 20260920（**4 个不同日期，跨度 4 天**） |
| mtime 范围 | 2026-09-17 09:15:09 → 2026-09-20 10:01:30 |
| 单文件最大 | `maintenance_night.log` 12,345 B（占全部 59%） |
| `pipeline_*.log` | 3 个，合计 3,900 B，均值 1,300 B/个 |
| `morning_*.log` | 4 个，合计 2,606 B，均值 651 B/个（最近两天各 174 B，明显比前两天小） |
| 子目录 | **无**（`logs/` 是平铺的，`logs/archive` 不存在） |

**日增速估算**：每交易日新增 `morning_*.log`(~0.65 KB) + `pipeline_*.log`(~1.3 KB) ≈ **2 KB/交易日**；
每周另加 `weekly_health_*.log`(~2.2 KB)。按 250 交易日/年算 ≈ **0.5 MB/年**（不含 `maintenance_night.log` 的滚存）。
**结论：按当前写入量，一年也到不了 1 MB——「归档」在本仓不是容量问题。**

## 二、`logs/archive` 为何不存在（三条取证）

1. **目录不存在**：`Test-Path logs\archive` → `False`；全仓 `archive` 目录只有仓库根的一个 `D:\code\my-quant-system-v8\archive`。
2. **归档器不覆盖 logs**：`archive_old_data.py` 的 `targets`（`:127-133`）是
   `('data', stock_csv_keep_days=7) / ('orders', 30) / ('results', 30) / ('reports', 60)`——
   **没有 `logs` 条目**；其 `ARCHIVE_ROOT`（`:23`）是仓库根 `archive/`，产物落 `archive/{YYYYMM}/<子目录>/`。
3. **无人创建**：全仓 `*.py` 里 `logs/` 的引用全部是**读**（见下节），没有任何 `makedirs('logs/archive')`。
   `pytest.ini` 的 `norecursedirs = logs archive tmp ...` 里的 `archive` 指的是**仓库根 archive/**，
   与 `logs/archive` 无关——这大概就是「logs/archive 结构」这一说法的最初来源（**名称撞车造成的误读**）。

## 三、谁会读 `logs/（清理前必读）

````
$ rg -n "logs[\\/]" -g "*.py" -g "!archive/**"
goal_metrics.py:6            扫描 logs/pipeline_*.log 最近 20 个有终态的交易日运行
scripts/ops_analyzer.py:4    Parses logs/pipeline_*.log → data/ops_analysis_<date>.md
stall_watchdog.py:4          比较最近流水线活动（latest logs/pipeline_*.log …）
stall_watchdog.py:125        log_date = _latest_date("logs/pipeline_*.log")
tests/test_stallwatchdog_contract.py:53/65/87   （契约测试桩）
```

**三个运行期消费者全盯着 `logs/pipeline_*.log`**：
- `goal_metrics.py` 要**最近 20 个交易日**的 pipeline 日志才算得出流水线成功率；
- `scripts/ops_analyzer.py` 直接按此 glob 出运维分析报告；
- `stall_watchdog.py` 用最新一份判「流水线是否卡死」——**删早了等于把卡死探测器弄瞎**。

⇒ **任何归档/清理方案，只要移动或改名 `logs/pipeline_*.log`，就必须同步改这三处**。
当前 `logs/pipeline_*.log` 只有 3 份（目标 20 份），说明**日志保留量本身还不够**，
而不是「太多了要清」。

## 四、归档策略评估与建议（本单不执行，交拍板）

| 方案 | 内容 | 评估 |
|---|---|---|
| A. 不动（推荐） | 维持现状：`logs/` 平铺、无轮转、靠 `.gitignore` 挡在版本库外 | **当前体量下最优**：9 文件 20 KiB，一年 <1 MB；`logs/` 和 `*.log` 已被 gitignore（`:28-29`，`git ls-files logs` 为空 ⇒ 零仓库污染）。为 20 KiB 建一套归档机制是负收益。 |
| B. 建 `logs/archive/{YYYYMM}/` 并纳入 `archive_old_data.py` | 把 N 天前的 `morning_*.log`/`weekly_health_*.log` 移入 | **可做，但必须白名单**：`pipeline_*.log` **永久排除**（三消费者要它），其余按 `logs_keep_days`（建议 ≥90）走。改动面 = `archive_old_data.py` 加一个 target ＋ 新配置键 ＋ 一条测试。 |
| C. 直接删除旧日志 | 删 N 天前的全部 `*.log` | **不可接受**（本轮红线：零删除；且会打瞎 `stall_watchdog`）。 |

**若要做，最小切片** = 方案 B，且顺序必须是：① 先给 `logs/pipeline_*.log` 加「永不动」白名单测试；
② 再给 `archive_old_data.py` 加 `logs` target；③ 跑一次 dry-run 核对只列举不移动。

## 五、零删除自证与复跑

- 本单**未创建、未移动、未删除任何文件**；普查脚本为一次性临时件，跑完即删（`tmp_logs_census_q920_12.py` 已不存在）。
- 复跑：第 0 节那条 `python -c` 一行命令，输出应与第一节表逐项一致。
