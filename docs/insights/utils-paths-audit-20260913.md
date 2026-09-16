# utils/paths 与手写路径收敛审计（2026-09-13，只读零改码）

## 一、复算与基线对账

| 指标 | 基线（refactor-blueprint-20260907） | 本单实测（9/13） | 判定 |
|---|---|---|---|
| utils/paths 引用数 | 0（结论：模块不存在/未采用） | **0**（utils/ 下无 paths.py；路径源已落位 `core/paths.py`，S4-a 地基批 2026-09-10 建） | ✓ 吻合 |
| 手写路径文件数 | 90 | **100**（宽口径=os.path.join/dirname/abspath ∪ Path(__file__) ∪ Path.resolve()）；**窄口径（仅 os.path.*，剔 tests）=77** | 口径差异非漂移：宽口径多计 27 个 tests + Path(__file__) 自引用类 |
| 路径源采用数 | — | **17 个文件**已 `from core.paths import`（core/secrets、fetcher×4、domain 核心×7、ops/health、tests 验收等） | S4 进行中实证 |

## 二、收敛清单（100 文件按目录分布与难度分级）

| 目录 | 文件数 | 难度 | 说明 |
|---|---|---|---|
| 仓根遗留脚本 | 53 | 中 | 多为独立工具（track_performance、trade_analyzer、enhanced_backtest 等），机械替换+各自 smoke |
| tests/ | 27 | 低 | characterization 固定 tmp_path 者多数无需迁移（迁移会破坏隔离语义），只迁真读仓结构的 |
| bark_sender/ | 6 | 低 | parsers/builders 已有批次测试护栏（511 绿），机械替换 |
| core/ | 4 | 豁免 | core/paths.py 本体=路径源（Path(__file__) 为合法自引用）；余 3 个逐个审 |
| app/ | 3 | 中 | 展示层 cwd 敏感，迁后须 smoke 53/53 |
| utils/ | 3 | 低 | calendar/file_io/trading_calendar |
| scripts/ | 2 | 低 | 一次性工具，可豁免 |
| ops/ | 1 | 低 | health.py 已部分采用 core.paths |
| tmp/ | 1 | 豁免 | tmp/audit 样例非生产码 |

## 三、工作量估计

- 低难度（tests 部分豁免后 ~30 + bark 6 + utils 3 + ops 1 + scripts 2 ≈ 25 文件）：1 个夜批；
- 中难度（根 53 + app 3 ≈ 56 文件，须逐文件 diff 快审默认值语义=资金风险红线）：3–4 夜批 + 1 次白天快审（与 blueprint S4 原估一致）；
- 豁免：core/paths.py 本体 + tmp 1。

## 四、边界

- 只读：零改码、零 commit/push（生产码 diff=0）✓；计数命令与口径已写明，可复跑 ✓。
