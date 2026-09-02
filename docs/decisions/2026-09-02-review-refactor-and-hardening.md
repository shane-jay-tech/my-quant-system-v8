# 2026-09-02 · 系统完整审查 + 前后端重构优化 + 提交

> 前置：用户要求"先完整了解与审查架构/功能 → 重构优化前后端需要的部分 → 提交改动"。
> 审查方式：两个只读子代理（前端 Streamlit / 后端 30+ 模块）并行产出证据报告；本文件保留结论与决策。
> 决策核心（strategy/position/sim/backtest/风控/出场/进化器）本轮**零改动**——按项目铁律，动它们需多模型评审。

## 1. 审查结论（证据来自子代理报告）

**前端**：薄入口 + 1443 行 pages.py + 独立 loaders/sidebar/styles；主要问题 = 坏文件无保护整页崩、三处选股解析重复、CSV 读取缺容错、requirements 的 streamlit>=1.30 与代码实际 API（width="stretch"/st.toggle）不匹配、缓存不完整、iterrows 慢。
**后端**：无 BLOCKER；主要问题 = auto_heal 把 `'python "..."'` 当脚本名导致修复后自检从未真正执行、goal_metrics 硬编码 v86 文件名（升版必坏）、7 处状态 JSON 非原子写、_self_check 状态读取无容错、cost_tracker 把本地审计记成 LLM 调用、parsers 与 rebalancer 持仓函数重复、core.config 静默吞配置错误、newbie 指令卡写死 10 万本金、smoke 未覆盖 v8.7 新模块。

## 2. 本轮重构（全部行为保持 + 只修故障/健壮性）

**后端**
- `auto_heal.py`：两处自检调用改 `run_script('_self_check.py')`（真 bug 修复）。
- `goal_metrics.py`：自检文件名跟随 `SYSTEM_VERSION`（新增 `self_check_report_name()`）；报告 JSON 原子写。
- 原子写迁移 `utils.file_io.atomic_write_json`：`portfolio_manager`、`newbie_protection`（2 处）、`track_performance`、`auto_heal.recreate_default_json`、`broker_adapter`、`goal_metrics`。
- `_self_check.py`：sim account / real_trades / newbie_status 三处读取 try/except 降级 WARN，不再中断整份自检；文件清单纳入 `v87_new`（上轮已做，本轮复核）。
- `core/config.py`：system_config.json 解析失败不再静默，打印 `[CONFIG] WARNING` 后仍用 DEFAULTS 兜底。
- `cost_tracker.py`：删除把本地成本审计记为 LLM 调用的 `log_llm_call('cost_tracker')`。
- `bark_sender/parsers.py`：删除无人引用的重复 `_lookup_position_shares`（唯一实现留在 `rebalancer.py`）。
- `smoke_tests.py`：CORE_MODULES 加入 v8.7 五个新模块（53 项导入检查）。
- `newbie_instruction_card.py`：本金回退不再写死 10 万，改读 `sim.initial_capital`。
- `data_loader.py`：缓存 CSV `.tmp+os.replace` 原子写；读缓存校验非空。

**前端**
- `app/loaders.py`：新增统一 `parse_pick_line()`（收敛 3 处重复的新旧表头解析）；`load_index_data/load_latest_picks/load_evaluation/load_daily_insight/load_current_prices` 全部加读取容错；补 `st.cache_data`；`load_current_prices` 去 iterrows 改向量化。
- `app/pages.py`：模拟账户 JSON 损坏降级为未初始化概览；持仓智能分析异常不阻断录入；健康页 JSON 损坏提示并继续；权益曲线/交易历史 CSV 读取容错；第三处选股解析改用 `parse_pick_line`。
- `app/sidebar.py`：版本回退值 8.5 → 8.6。
- `requirements.txt`：streamlit 下限 1.30 → 1.44（匹配 width="stretch"/st.toggle）。

## 3. 事故与修复（诚实记录）

全量 pytest 期间（2026-09-02 23:27:58），一次测试/AppTest 会话触发了仪表盘「取消手动，改回自动推算」回调，以生产路径执行：
- `data/system_config.json` 的 `sim.manual_capital` 从 **2400 被改成 None**（memory.md 20260824 条目可证原值）；
- `sim_results/account_state.json` 被重置为空仓（reason=manual_capital_set）；
- `sim_results/equity_curve.csv` 与 `trade_history.csv` 被删除。

**修复**
- `sim.manual_capital` 恢复为 2400；`account_state.json` 按 08-21 `sim_report.md` + `exit_advisor_20260821.json` + memory 重建（3 持仓、equity 2031.54、12 笔/胜率 33.3% 等聚合字段）；
- `equity_curve.csv` / `trade_history.csv` 无任何备份，无法忠实重建——**已如实告知用户**；下一次 `sim_trade.py` 运行会重建权益曲线，12 笔成交明细不可恢复（聚合统计仍在 sim_report.md）；
- 新增 `tests/conftest.py` 全局护栏：任何测试对生产 `sim_results` 调 `_reset_sim_account` 直接 AssertionError，只允许 tmp_path；并加回归测试锁定。
- 复验：全量 pytest 后生产 account_state mtime 不变。

## 4. 回归（最终执行）

| 检查 | 结果 |
|---|---|
| pytest | **366 passed / 2 xfailed / 0 failed**（本轮新增 tests/test_v87_review_refactors.py 14 用例 + conftest 护栏） |
| smoke_tests | **53/53 OK**（新增 5 个 v8.7 模块 import 检查） |
| _self_check | **147 项：144 PASS / 1 WARN / 2 FAIL**；3 条告警全部为改动前数据新鲜度（stock 85.8h、history 滞后 12 天、exit advisor 295h），下一交易日流水线消除；sim 持仓已恢复 3 只、metric 7/8 |
| py_compile | 全部改动文件编译通过 |
| 生产数据护栏 | 全量 pytest 后 account_state.json mtime 未变 |
| API 成本 | 0 元（全程离线） |

## 5. 未做（明确列入后续）

- 决策核心任何重构（需多模型评审 + 回测验证）。
- `_self_check.py` import 即执行全量自检 → 函数化重构（影响 smoke/测试面，单独做）。
- `app/pages.py` 拆包（1443 行 → pages/ 包）、`utils/paths.py` 全量替换 50+ 处 BASE_DIR/sys.path。
- `_reset_sim_account` 加二次确认/备份（涉及账户数据语义，需用户决策）。
- trade_analyzer / psychology_assistant 硬编码风控文案改读配置。
- `data_validator` fail-open 策略与 pipeline fatal 语义（涉及交易链路，多模型评审）。
- 根目录杂物清理（gpt_out*.txt、call_gpt*.py、*.bak*）：等待用户确认后删除。
