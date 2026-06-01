# 2026-08-24 — 赚钱目标固化 + 本金 2400 同步 + Alpha Gate 计数接线

## 难度评分（根配置评分卡）

- 影响面 1（配置与既有停损接线，非交易信号公式）+ 风险领域 1（涉及资金口径）+ 歧义度 0 + 新颖度 0 + 可逆性 0 + 长程影响 2（配置为全链路口径）→ **L2 档**。
- 未改 buy/sell 决策公式、止损止盈参数、数据源、回测引擎核心，故按根配置不触发双实现；资金相关结论由总指挥直接复核。

## 决策

1. **固化目标**：新建 `GOAL.md`，把「在 2400 元小资金下更可能赚钱」写成 310 字目标（应用户要求多轮重写，最终版为数据/策略/风控/成本/自动化/体验六层面全系统优化口径，明确不只改交易策略）+ 成功证据 + 停止条件；预算 20 元人民币（API 花费）。
2. **本金全链路 1200 → 2400**：
   - `core/config.py` DEFAULTS：`position.default_capital` / `sim.initial_capital` / `broker.max_single_amount` = 2400。
   - `data/system_config.json`：同上，并新增 `sim.manual_capital=2400`（用户口述真实投资额）。
   - `sim_trade._FALLBACK_CAPITAL`、`position_sizer._CONFIG_CAPITAL`、`cost_model.DEFAULT_CAPITAL` 兜底统一 2400。
   - `app/pages.py` 回放/本金设置/健康页兜底与 Beginner 标签改为读配置。
   - `benchmark_comparison.py`、`replay_picks.py`、`etf_gate.py` 报告/文案本金口径读配置，不再写死 1200。
   - 已执行 `sim_trade.init_account()`：账户基线 2423.90 → 2400.00，**现金、持仓、历史盈亏原样保留**。
3. **Alpha Gate 补线**：`core/pipeline.py` 新增 `_alpha_gate_precheck()`。旧实现只读 `is_paused()`、从不更新状态，连续 severe 计数永远停在历史值，门形同虚设；现在每次非 dry-run 流水线先执行 `check_alpha_gate()` 计数，再决定是否早退。异常 fail-open（打印告警不阻断）。
4. **测试隔离修正**：`tests/test_sim_trade.py` fixture 默认 monkeypatch `get_manual_capital→None`，避免生产手填本金泄漏进 real-trades 联动测试；`tests/test_cost_model.py` 动态金额期望更新为 2400 口径，并保留 1200 历史回归用例。

## 验证

- `python -m pytest -q`：**239 passed, 2 xfailed**（改动前基线 235 passed / 2 xfailed，净增 4 个通过用例：Alpha Gate 接线 3 个 + 1200 历史成本回归 1 个）。
- `python smoke_tests.py`：**48 OK / 0 FAIL**。
- `python -m py_compile`：全部改动文件通过。
- `python -m core.pipeline --dry-run`：正常列出 26 个 beginner 步骤，rc=0。
- 配置读取确认：position/sim/broker 全部为 2400，`sim.manual_capital=2400`。

## 预算

- 本轮未调用任何外部 LLM API / 多模型通道，API 花费 **0 元**，远低于 20 元上限；全部为本地计算与文件操作。

## 风险与边界

- 本金改为 2400 后仍 ≤3000，小资金模式（全仓、板块集中度豁免）不变；摩擦成本单笔 800 元约 1.7%、单笔 2400 元约 0.87%，仍显著，继续遵守「少交易」原则。
- Alpha Gate 现在会按真实日历计数：当前 excess=-0.09%（severe），若连续 5 个交易日未改善，流水线将自动暂停选股并推送 Bark。这是设计意图；想恢复运行 `python alpha_gate.py --reset`，想关闭在 `system_config.json` 设 `alpha_gate.enabled=false`。
- 未动：buy/sell 因子、止损止盈、回测核心、数据源；这些仍需按根配置走多模型评审后再改。
