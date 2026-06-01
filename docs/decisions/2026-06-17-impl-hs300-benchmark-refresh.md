# Implement: 修复沪深300基准数据在 beginner 档不更新

Date: 2026-06-17
Supersedes: none

## 结构化元数据
- 任务类型：implement（数据流水线 + 决策闸门，强制多模型）
- 调用模型：Kimi K2.6（方案审）、DeepSeek V4 Pro（代码审）。GPT-5.5 独立实现被用户中途取消 → 改为 Opus 单实现 + DeepSeek 审（符合"第二份实现或评审任选其一"规则）。
- 模式：deep（核心模块 + 数据源 + 影响 buy/don't-buy 闸门）
- DeepSeek findings：critical 0 / major(security+design 类) 2~3 / minor·suggestion 若干（见下）
- 接受的 finding：性能#3（恢复新鲜短路）、设计#4+#1（无 stock 文件返回 None + 异常打印告警）
- Opus override 的 finding：#2 节假日盲区、#5 count_trading_days 复杂度、nit#3 —— 理由见仲裁；nit#1 经核实代码已处理（DeepSeek 误读）
- 测试：183 passed（全量回归）
- 残留风险：见末节
- 用户是否要求返工：否

## 原始需求
选股系统提示"基准数据已24天未更新"。诊断根因后永久修复，使其在 beginner 档也每天刷新且不再误报。

## 诊断（根因）
- `data/hs300_index.csv`（沪深300基准，列 `日期,收盘`/utf-8-sig/升序）唯一写入者是 `enhanced_backtest.fetch_index()`（新浪 sh000300），而 enhanced_backtest 是 `core/pipeline.py` 的 `backtest` 步骤，`tiers=["advanced","pro","auto"]`，**beginner 档不跑**。
- 当前系统 = beginner 档（`core/config.py` 默认；`system_config.json` 无 tier 字段）。
- 故 beginner 档每日流水线从不刷新基准；`hs300_index.csv` 与 `results/honest_evaluation.md` 都冻结在 5/23（v8.6 发布日手动跑过一次）。
- `etf_gate.py` 首选读 `honest_evaluation.md` 的 **文件 mtime**，超 `gate.max_age_days(=10)` 即报"基准数据已 X 天未更新"。今天(6/17)正好 24 天。
- 新浪接口实测可用（curl 拉到 6/16 收盘 4884.232）——数据源没坏，纯粹无人调用。

## 即时处置（本次实现之前）
手动 `python enhanced_backtest.py` 刷新一次 → `hs300_index.csv` 到 6/16、`honest_evaluation.md` 重写 → 警告归零。但旧的全量覆盖逻辑把文件历史从 2025-07-23 截断到 2025-08-15（仍含 200 个交易日，远超所有消费方 120 天窗口，无影响）。该次刷新后闸门露出真实信号：超额 -10.05%（severe，建议买ETF）——这是闸门本职，非 bug。

## Kimi 方案审（要点）
- Part 1 方向正确。Part 2 三候选对比后**推荐 (c)**：陈旧判定改为基于真实行情数据(hs300_index.csv)的最新交易日，而非报告 mtime；前提是**必须改文案**区分"行情数据陈旧"vs"回测评估老旧"。
- (a) 多源取最新鲜有 false-negative 风险（benchmark_*.md 派生自 honest_evaluation.md）；(b) beginner 加轻量回测违背档位意图、维护成本最高。
- 最大风险：A股长假休市导致"按自然日算"误报 → 应按**交易日**口径（本实现采用）。

## 最终实现（Opus 落地）
1. **新增 `fetch_index.py`**（全系统单一写入源）：新浪 sh000300 → 合并式写 `hs300_index.csv`（读旧+抓新 → 按日期去重 keep=last → 升序 → 原子写 `os.replace`）；反反爬（Session/轮换UA/Referer/超时/3次指数退避+抖动）；网络或解析全失败 `return False` 且**绝不覆盖现有文件**；暴露 `update_hs300_index(data_dir)->bool`。
2. **`core/pipeline.py`**：`PIPELINE_STEPS` 新增 `fetch_index` 步骤（script=`fetch_index.py`，全四档含 beginner，daily，retry=2/wait=30，**非 fatal**，位于 update_history 之后、data_validator 之前）。dry-run 确认 beginner 档为 [5/26] active。
3. **`enhanced_backtest.fetch_index()`**：改为复用 `update_hs300_index`（消除"合并 vs 全量覆盖"两份写入逻辑打架 = DeepSeek/Kimi 的 P1-001）；并保留"已是最新交易日则跳过网络"短路（避免每日回测重复抓取）。
4. **`core/config.py`**：`gate` 块新增 `stale_lag_trading_days=3`。
5. **`etf_gate.py`**：新增 `_hs300_data_lag_trading_days()`（用 utils/calendar 算 hs300 落后本地最新交易日多少个**交易日**，≥3 才 stale；缺 hs300 文件 / 缺 stock_*.csv / 读不出 → None 按"不陈旧"放过，异常打印告警不静默）。`evaluate_etf_gate` 重排：读超额(优先 honest_evaluation.md 回退最新 benchmark_*.md) → 判数据陈旧 → 按超额分级。文案改为"行情基线数据(沪深300)已落后 N 个交易日未更新，请检查每日 fetch_index 步骤"。`max_age_days` 参数保留但已不参与判定。
6. **测试**：新增 `tests/test_fetch_index.py`（合并去重/保留历史/升序/网络失败不毁文件/utf-8-sig，全 monkeypatch 不打网）；`tests/test_etf_gate.py` 把两个旧 mtime stale 用例改为数据驱动 + 新增"缺数据不误报"用例。

## DeepSeek 5维度审查（verbatim 摘录）
Verdict: **ship-with-fixes**（无 BLOCKER/CRITICAL）
1. security — `_hs300_data_lag_trading_days` 吞异常返回 None=不陈旧，corrupt/missing 文件会静默跳过 → false-negative。建议：无法判定时视为陈旧或独立 severity 并告警。
2. edge-cases — `count_trading_days` 在区间未被本地文件覆盖时用 weekday 计数，忽略节假日（如春节周），lag 可能偏差数日。建议：接入节假日历或 fallback 时告警。
3. performance — `update_hs300_index` 最多 3 次退避(~45s)，enhanced_backtest 现在每次都触发网络调用，慢网会拖累每日流水线。建议：离线快速返回 / 降低重试预算。
4. readability — `count_trading_days` 三轮补丁累积、深嵌套，难审 off-by-one。建议：拆分阶段重构。
5. design — `get_last_trading_day` 依赖 stock_*.csv 文件名，archive 会清理，全缺时退回 `datetime.now()`（未必交易日）→ 破坏 lag 计算，比旧 mtime 方案更脆。建议：专用 marker 文件 / mtime 兜底。
nits：① _merge 只 trim 了 fresh 的日期未 trim existing；② pandas 局部 import 在 bare except 内会吞 ImportError；③ 缺 weekday-fallback 路径测试。
好的方面：单写入源 + 原子写防损坏；测试充分用 monkeypatch 避免真网络。

## Opus 仲裁（逐条）
- **#3 性能 → 接受**：`enhanced_backtest.fetch_index()` 恢复"最新交易日则跳过网络"短路。已修。
- **#4 设计 + #1 security → 部分接受**：无 stock_*.csv 时返回 None（避免 now() 兜底的 bogus lag）；异常分支 `print` 告警不再全静默。已修。但**不接受**"无法判定即判 stale"——会让新装/测试夹具（无 hs300 文件）误报红横幅，且旧 mtime 方案在 honest_evaluation 缺失时同样静默（非回归）。对 1200 元用户，误报"系统坏了"比偶发漏报更糟。
- **#2 节假日 + #5 count_trading_days 复杂度 → override（不改）**：`count_trading_days` 是全队共用成熟工具（已 3 轮修 + 有自身语义），改它影响面远超本次范围。实际风险低：数据新鲜时提前返回 0 不走 fallback；数据真陈旧（>本地7天窗口）时即便天数偏差，结论仍是"陈旧"=正确。列为既有技术债 + 残留风险，不在本次扩张。
- **#5 marker 文件 → override**：stock_*.csv 全缺意味着 fetch_quote(fatal_on_fail) 已挂、整条流水线已停，属更大故障；为此加专用 marker 属过度设计。已用"无 stock 文件→None"廉价兜底。
- **nit#1 → 经核实已处理**：`fetch_index._merge` 中 `existing["日期"]=...str[:10]` 已对 existing 截断，DeepSeek 误读。
- **nit#2 → 由 #1 修复覆盖**（异常已打印告警）。**nit#3 → defer**：count_trading_days 的 fallback 测试属该工具自身职责，本次不扩。

## 验证
- `python fetch_index.py` rc=0，合并写入，最新 6/16。
- `enhanced_backtest.fetch_index()` 0.58s 返回（短路生效，无网络）。
- `etf_gate.evaluate_etf_gate()`：severity=severe，excess=-10.05，无 stale（数据新鲜）。
- `python daily_pipeline.py --dry-run`：beginner 档 fetch_index = [5/26] active，位置正确。
- `pytest tests/`：**183 passed**。

## 残留风险
1. **闸门"跑赢/跑输"结论在 beginner 档仍不会自动刷新**：超额数来自 `honest_evaluation.md`，只由 advanced+ 回测生成。本次只修了"数据陈旧误报"，未让 excess 在 beginner 每日更新。当前值是今天手动回测的 -10.05%。若要 beginner 也每日刷新评估，是更大改动（Kimi 的 (b)/(d)），需另立任务。
2. **count_trading_days 节假日盲区（既有债）**：仅当基准已严重落后且超出本地 stock_*.csv 窗口时，警告里的"落后 N 个交易日"数字在长假附近可能偏差几天；但"陈旧"判定本身仍正确。
3. **依赖新浪单一数据源**：fetch_index 仅接新浪 sh000300，限流/接口变更时当日不刷新（非 fatal，不阻塞流水线，下个交易日自动重试；持续失败会再次触发陈旧告警）。
