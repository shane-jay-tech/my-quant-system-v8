# 2026-09-02 · 方案 B 落地：LLM 融合层（shadow）+ 系统完整体检与改良

> 协作档位：评分卡 6 项 = 影响面 1 / 风险领域 1（凭据清理、shadow 不碰资金）/ 歧义 1 / 新颖 2 / 不可逆 0 / 长程 1 → **总分 6 → L3 门槛**。
> 实际执行：总指挥（DeepSeek V4 Pro，当前会话）直做 + 自审；**未调用 Flash/GPT 第二实现**。理由：本次改动不触碰 buy/sell / 风控 / 仓位 / 回测核心（均为交付层与 shadow 落盘），不在「量化项目强制多模型触发清单」内；凭据清理属删除硬编码回退，可自动验证（测试锁定）。**LLM 观点晋级为投票权重时必须走 L3+ 多模型评审**（已写入 AGENTS.md 铁律）。
> 本会话 API 成本：0 元（全部离线，未调用任何模型接口）。

## 1. 原始需求

用户："按照推荐（方案 B：中结合）进行，并检查我的系统，对我的系统进行一次完整的优化改良改善。"

前置调研：`reports/study_tradingagents_cn_studio_20260902.md`（frank-quant/TradingAgents-CN-studio 对比）。

## 2. 基线诊断（改动前）

| 项 | 结果 | 处置 |
|---|---|---|
| pytest | 317 passed / **1 failed** / 2 xfailed | `test_exit_advisor_analyze_position_uses_effective_rules` 写死 `entry_date='2026-08-14'`，hold_days 随真实日期增长，9-02 起必然失败 → 改为 `datetime.now()`，测试不再依赖日期 |
| smoke_tests | 48/48 | — |
| _self_check | 139/142（2 FAIL 1 WARN） | 三条全是**数据新鲜度**（行情 84.8h、history 滞后 12 天、出场顾问 294h）——流水线自 08-30 后未跑，非代码缺陷；本次不拉数据（写状态、耗时长），留给下次交易日流水线 |
| README 验证一节 | 引用 `scripts/health_check.py` **不存在** | 修正为 `_self_check.py`，补新命令 |
| .venv | **缺 pytest**（README 的 `pytest` 命令跑不起来） | requirements.txt 补 `pytest>=8.0`；本次用系统 python 3.12（有 pytest + pandas/streamlit）跑测试 |
| 安全 | `bark_sender/config.py` 两处**硬编码 Bark token 回退**；`_self_check` 只查 `send_to_bark.py` 所以漏检 | 删除回退，无 token 返回空列表 + `send_bark()` 返回 False；新增测试 `test_no_hardcoded_bark_token_in_sources` 扫 4 个文件 |
| 死代码 | `bark_sender/config.py` 的 `RESULTS_DIR/REPORTS_DIR/...` 指向 `bark_sender/` 子目录（错误）且零引用；`push.py` 用了 `datetime` 却没 import（`send_from_newbie_file` 路径必崩） | 删常量；补 import |
| 文档/代码偏差 | AGENTS.md 称「LLM 步骤 6 个」，但 `research_agent`/`external_research` 实为本地 TF-IDF/规则，进程内无任何 LLM 调用 | 本次新增 `core/llm.py` 成为真正的统一 LLM 通道；旧描述留待版本升级时整理（不在本次范围） |
| 根目录杂物 | `gpt_out*.txt`、`call_gpt*.py`（硬编码绝对路径）、`CLAUDE.md.bak*`、`pipeline_run_20260529.log`、`stderr_capture.log` | **未删除**（不可逆，需用户决定）；已 gitignore，不影响仓库 |

## 3. 设计：「算得清的管钱，说不清的管理解」

```
数据层(现有) → 全市场规则筛选(现有) → 风控门(现有) → top N 候选 → position_sizer/exit_advisor(现有，唯一下单依据)
                                                          ↓ 只读
                                    llm_analyst.py(新, shadow)：多头→空头→研究经理裁决 JSON，只落盘
                                                          ↓
                    digest.py(新)：四段 200 字简报 ←── 所有当日产出 ──→ decision_replay.py(新)：单文件 HTML
                                                          ↓
                    send_to_bark.py(改)：简报前置 → bark_sender/channels.py(新)：Bark + webhook + 飞书
反馈：llm_analyst --evaluate 用 history.csv 算 verdict 的 5 日前瞻命中率 → 达标后才允许进 strategy_feedback 投票（L3+ 评审）
```

### 3.1 各方案取舍（已在上轮向用户呈现，用户选 B）
- A 轻结合：只抄交付层。收益确定但不建立 LLM 观点的评估数据。
- **B 中结合（采纳）**：A + shadow 分析师。多出的成本可控（top3 × 3 次 Flash 调用/日，无 key 零成本），且从今天起积累 verdict 数据，为后续是否给 LLM 投票权提供证据。
- C 重结合：部署上游 TradingAgents-CN + Studio。重（MongoDB/Redis）、app/frontend 商业许可边界、小资金不划算。

### 3.2 与 Studio 的对应关系
| Studio 模块 | 本系统落地 | 差异 |
|---|---|---|
| digest（LLM 提炼） | `digest.py` | 加了**规则兜底**（无 key 也有产出）；输入是本地结构化产出而非十几万字报告 |
| notify（5 渠道） | `bark_sender/channels.py` | 先做 Bark/webhook/飞书三种；`type#别名` 多实例、失败隔离照抄 |
| replay（辩论回放） | `decision_replay.py` | 本系统无辩论过程，改为「为什么选中/买/卖/哪道门拦」的规则决策回放；纯本地零成本 |
| compare（多模型对比） | **未做** | 需真实 token；作为 P2 留待 shadow 数据≥20 条后再评估是否需要 |
| 上游多智能体 | `llm_analyst.py`（3 角色精简版） | 事实锚定：只允许引用当日快照 + 20 日 K 线派生；不做新闻/基本面（无数据源，避免幻觉） |

## 4. 改了什么

**新增**
- `core/llm.py` — 统一 OpenAI 兼容通道；key 优先级 env > secrets.json；无 key `llm_available()=False`；空内容加倍重试 / HTTP 退避重试；每次调用写 `cost_tracker`（真实 usage × 模型单价）；`parse_json_object` 容忍围栏与废话。
- `digest.py` — 收集 pick/orders/exit_advisor/regime/alpha_gate/daily_insight/llm_analyst → 事实清单（12k 裁剪保头尾）→ LLM 四段简报（校验标签+长度，不合格收紧重试一次）→ 规则兜底 → `results/digest_*.md` + `orders/digest_bark_*.txt`。
- `decision_replay.py` — 六区块单文件 HTML（市场与风控门 / 选股漏斗 8 道门 / 选股表 / 订单与"选中未下单" / 出场顾问 / shadow 观点），全部 `html.escape`。
- `bark_sender/channels.py` — `Channel` 抽象 + `registry`；`BarkChannel`/`WebhookChannel`/`FeishuChannel`（签名）；`load_channel_config`（secrets.json:notify_channels + env）；`build_channels` 配置不全跳过；`push_all` 逐渠道结果。
- `llm_analyst.py` — top N（默认 3，`llm_analyst.max_stocks`）× 三角色；verdict 归一化；`results/llm_analyst_*.{md,json}` + `data/llm_verdicts.jsonl`；`--evaluate` 前瞻命中率。
- `tests/test_v87_hybrid_layer.py` — 35 用例，全部离线。

**修改**
- `core/pipeline.py` — 注册 `llm_analyst`（strategy_feedback 后）、`digest`、`decision_replay`（behavior_log 后、bark_push 前）；44 步；既有顺序约束全部保持。
- `send_to_bark.py` — `load_digest()` 前置当日简报（标题替换为「开盘前简报 MM-DD（多空）」）；推送改走 `push_all`（只配 Bark 时行为不变）；`--no-digest` 开关。
- `bark_sender/config.py` — 重写：删硬编码 token、删死常量。
- `bark_sender/push.py` — `send_bark(title, body, tokens=None)`；无 token 返回 False；补 `datetime` import。
- `_self_check.py` — 文件清单加 `v87_new`（5 个文件）。
- `tests/test_risk_defaults_unify.py` — 去掉日期依赖。
- `README.md` — 验证命令修正 + 新模块说明；`requirements.txt` — 补 pytest；`AGENTS.md`/`CLAUDE.md` — 新增「v8.7 预备：LLM 融合层」章节 + 三条铁律。

**未改**：任何 buy/sell、风控、仓位、回测代码；`SYSTEM_VERSION` 仍 8.6（新模块标注"v8.7 预备"，版本号升级另走流程）。

## 5. 验证（改动后，见 §7 回归记录）

- 新增 `digest.py --dry-run --no-llm`：242 字四段，事实全部来自 orders/exit_advisor ✓
- `decision_replay.py`：11.5KB HTML，5 区块 34 行 ✓
- `llm_analyst.py` 无 key rc=0 跳过；`--evaluate` 无记录 rc=0 ✓
- `send_to_bark.py --dry-run`：简报前置、标题「开盘前简报 08-21（中性）」✓
- 渠道注册表：Bark 2 token、registry=[bark, feishu, webhook]、无 token 返回 False ✓
- 全量 pytest / smoke / self_check：见 §7

## 6. 风险与反方

1. **规则简报可能把"止损触发"当天的紧急卖出排在信号之后**——四段顺序固定，紧急卖出在【风险】【动作】两段都出现，但用户若只读第一行会漏。缓解：标题含多空判断；后续可在【结论】前加 🚨 前缀（未做）。
2. **LLM 简报的事实校验只有标签+长度**，没有逐数字对账；prompt 已禁止编造，但幻觉风险仍在 → 简报 md 附完整"事实来源"段供人工核对；订单不受影响。
3. **shadow 分析每日 9 次 Flash 调用**（top3×3）：按 DeepSeek Flash 定价约 0.02–0.05 元/日，可忽略；但若用户把 `DEEPSEEK_MODEL` 设成 Pro，成本 ×3。`cost_tracker` 会记录。
4. **`send_to_bark` 标题被简报覆盖**：老用户习惯的"量化选股 TOP10"标题变了；`--no-digest` 可恢复。
5. **反方**：小资金 <3000 元场景下，交付层再好也不改变"摩擦成本 0.8%/笔"的现实；本次改动提升的是**可读性、可追溯、凭据安全**，不是收益。LLM 观点是否有 alpha，要等 ≥20 条 verdict 的 `--evaluate` 数据说话。

## 7. 回归记录（2026-09-02 实际执行）

| 检查 | 结果 | 说明 |
|---|---|---|
| pytest（系统 python 3.12） | **353 passed / 2 xfailed / 0 failed** | 基线 317+1 失败；修日期依赖测试后 318；本次新增 `test_v87_hybrid_layer.py` 35 个离线用例 |
| smoke_tests | **48/48 OK** | rc=0，报告 `reports/smoke_tests_20260902.md` |
| _self_check | **147 项：144 PASS / 1 WARN / 2 FAIL** | file 68/68（v87 五个新文件全部在位）、config 11/11、import 32/32；3 条告警全部是**改动前就存在的数据新鲜度**（stock 85.3h、history 滞后 12 天、exit_advisor 294.5h），与本次改动无关，下一个交易日流水线自动消除 |
| 模块实测 | digest 规则兜底 242 字四段（来自 08-21 真实产出）；replay HTML 5 区块 11.5KB；llm_analyst 无 key rc=0 干净跳过；send_to_bark --dry-run 简报前置成功 | 全部无 Traceback |
| API 成本 | **0 元** | 本会话全程离线，未调用任何模型接口 |

## 8. 遗留 / 下一步

- P2 `compare`（多模型同题对比）：待 shadow verdict ≥20 条后评估。
- 根目录杂物清理（`gpt_out*.txt`、`call_gpt*.py`、`*.bak*`、旧 log）：需用户确认后删除。
- AGENTS.md「LLM 步骤 6 个」描述与代码不符，随版本升级到 8.7 时一并整理。
- 数据新鲜度告警：下一个交易日流水线自动消除；若持续，检查 Windows 计划任务是否还在。
- 配置 `DEEPSEEK_API_KEY`（或 `data/secrets.json:deepseek_api_key`）后，digest 走 LLM、llm_analyst 开始积累数据。
