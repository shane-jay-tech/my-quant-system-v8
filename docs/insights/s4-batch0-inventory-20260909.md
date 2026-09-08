# S4 批 0：paths/config/secrets 收敛——只读盘点与分批方案（2026-09-09）

> 执行：GLM-5.3-Flash 夜间执行班（任务 20260909-034003-qs40，**零改码**）。观察时点 2026-09-09 04:2x，HEAD=3725c7b（S2/S3 已在本夜落地）。
> 方法：全仓 .py 静态扫描（排除 .venv/.git/archive/data/logs/docs 等非代码目录），五类模式：BASE 拼接 / 相对路径字面量 / 盘符绝对路径 / core.config 导入 / 其他 config 读取 / secrets 相关。

## 一、现状盘点（实测，非蓝图估算）

| 类别 | 文件数 | 说明 |
|---|---|---|
| **有任一收敛标的的文件** | **79** | 与蓝图「约 90 文件」同量级（蓝图估算含 docs/tests，本扫描排除后为 79） |
| BASE 拼接路径（os.path.join(BASE…)） | 60 | core/paths.py 收敛主战场 |
| 相对路径字面量（'data/' 等） | 4 | 少量直写 |
| 盘符绝对路径 | 1（tests/test_v87_review_refactors.py） | 仅测试，低优先 |
| core.config 导入 | 46 | config 单例读的改造面 |
| 其他 config 读取（configparser/config.json/load_config） | 18 | 多副本候选 |
| secrets/API_KEY/BARK/.env 相关 | **11**（+1 扫描脚本自匹配） | **R2 快审必列** |

**secrets 相关 11 文件（R2 清单核心）**：app/loaders.py、archive_old_data.py、bark_sender/channels.py、bark_sender/config.py、bark_sender/push.py、core/llm.py、core/pipeline.py、fetch_history.py、llm_analyst.py、ops/health.py、（tests/test_v87_hybrid_layer.py 为断言引用非消费）。
另有 root 级 `.env.local`（llm_call._load_env_local 上溯读取）与 core/secrets 的目标语义重合，收敛时须一并设计。

## 二、分批方案（5 批，每批独立可 revert，批内一次 commit）

| 批 | 范围 | 内容 | 批间依赖 | R2 快审需求 |
|---|---|---|---|---|
| **S4-a** | ops/ + tests + scripts 工具层 | 新建 core/paths.py + core/secrets.py（单例读 API）；迁 ops/health.py、scripts 层引用 | 无（打地基） | 低 |
| **S4-b** | fetch_* + 数据入口层（fetch_history/fetch_stock_data/fetch_etf_data/fetch_index/data_loader/data_validator） | BASE 拼接迁 paths；数据文件默认路径迁移 | 依赖 S4-a 的 API | 中（数据落点变化=资金数据风险，默认路径语义需逐文件快审） |
| **S4-c** | 策略/回测核心层（strategy/sim_trade/enhanced_backtest/walk_forward/monte_carlo/position_sizer/portfolio_risk） | 同上迁移 | 依赖 S4-a | **高（R2 核心：默认值漂移=资金风险，逐文件 diff 快审）** |
| **S4-d** | app/ 前端层 + bark_sender + llm 链 | BASE 拼接迁移 + **secrets 收敛进 core/secrets.py**（本批含全部 11 个 secrets 文件中的 9 个） | 依赖 S4-a；bark 批次放后（推送凭据，错配=外部副作用） | **高（凭据读取路径变化，白天快审+实推验证）** |
| **S4-e** | 收尾：config 单例读改造 + 存量 config_other 18 文件清理 + tests | 18 个其他 config 读取统一走 core/config 单例；补回归断言 | 依赖 a–d 全部 | 中 |

## 三、R2 白天快审清单（逐文件 diff 不可省）

1. **全部 11 个 secrets 相关文件**（上表）——凭据默认值/回退值语义；
2. **S4-c 全部核心层文件**——数据文件默认路径与默认参数值；
3. **S4-b 的 fetch_history/fetch_stock_data**——历史数据落点默认值（迁移后数据断档=回测失真）；
4. config 18 文件中的 `load_config` 多副本——默认值合并时以「现网实际生效值」为准，不以代码字面为准（建议迁移前先跑一次现状值采样脚本留档）。

## 四、验收与回滚
- 每批验收：pytest 全量（基线 410）+ smoke 53/53 + 该批涉及脚本的 pipeline 实跑干跑；
- 回滚：单批单 commit，`git revert <hash>` 即回；
- 本批 0 承诺：未改任何生产文件（本报告为唯一新增文件，零扫描临时件残留）。

## 五、遗留问题
- 扫描为模式匹配，语义级路径拼接（如 f-string 拼路径）可能漏计——S4-a 实施时以 `grep -rn "os.path.join"` 人工复核一遍为妥；
- 79 文件的逐文件清单已在扫描中生成，入报告时按批归组展示（全文列表过长，如需可追加附录文件）；
- `.env.local` 读取逻辑（llm_call._load_env_local）与 ops/health 的 secrets 检查（_self_check 遗产）语义是否并入 core/secrets.py，属 S4-a 设计决策，留实施单。
