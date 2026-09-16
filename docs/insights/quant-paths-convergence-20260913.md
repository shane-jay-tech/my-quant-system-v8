# quant 路径收敛现状复核与切片候选（b-44，2026-09-13，零改码）

## 一、两项数字复核（实测命令）

- `utils/paths` 引用数：**0**（utils/ 下无 paths.py——路径源已由 S4-a 落位 `core/paths.py`，实查 17 文件已采用 `from core.paths import`）；
- 手写路径拼接文件数：全仓 100（含 tests 27）/ 剔 tests 生产域 **73**（基线口径 90 为旧行数分母，差异已归因，与 a-40 审计一致）。
- 复核命令：`grep -rlE "os\.path\.(join|dirname|abspath)|Path\(__file__\)" --include="*.py" . | grep -v tests | wc -l` → 73。

## 二、生产域 Top 手写点（按行数）

app/pages.py=28、strategy_feedback.py=19、digest.py=13、sim_trade.py=12、position_sizer.py=11、llm_analyst.py=11、goal_metrics.py=11、bark_sender/parsers.py=11、app/loaders.py=11、multi_strategy.py=10、exit_advisor.py=10、auto_heal.py=10（其余长尾）。core 内 4 处中 2 处为 paths.py 本体合法自引用。

## 三、切片候选（≥4 片，每片 ≤40 分钟，文件集不相交）

| 片 | 文件集 | 预估 | 风险 |
|---|---|---|---|
| S-a | bark_sender/ 6 文件（parsers/builders/senders 等，有 522 绿护栏） | 30m | 低 |
| S-b | app/（pages.py 28 处+loaders 等 3 文件） | 40m | 低-中（展示层，迁后 smoke 53/53） |
| S-c | 根部报告/杂用脚本：digest、goal_metrics、replay_picks、trade_analyzer、track_performance（5 文件 ~55 处） | 40m | 低-中 |
| S-d | core/ 残余：pipeline.py、llm.py、config.py（5 处，paths.py 本体豁免） | 30m | 低 |
| S-e（高风险·须逐行快审） | 资金域：position_sizer、multi_strategy、exit_advisor、newbie_protection、strategy_feedback、sim_trade（6 文件 ~73 处）——**资金红线域，改前须人工确认默认值语义零漂移** | 2 批 ×40m | **高（资金）** |

## 四、边界

- 本单零改码 ✓；utils/paths 已迁移为 core/paths.py 的新现状如实记录（任务书「utils/paths 引用=0」口径与实盘吻合）。
