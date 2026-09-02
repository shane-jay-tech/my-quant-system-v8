# 2026-09-03 · 深挖审查第二轮（静态扫描 + 决策核心 bug 修复 + 独立复核）

> 用户："还不够细致……再好好审查优化。"
> 方法：ruff E9/F63/F7/F82/F821/F841/F401/E7/B 全库静态扫描 → 逐条验证上一轮 11 项遗留 →
> 修复决策核心 bug → **放独立评审员审 git diff**（抓到 3 个 MAJOR，已全部回修）→ 全量回归 → 提交。
> 生产数据防护：审计前后 12 个状态文件 SHA-256 逐字节一致。

## 1. 静态扫描发现并修复

- **`_self_check.py` 未定义 `re`**（secrets.json 缺失分支会崩）→ 补 `import re`；扫描规则本身也清掉了历史真实 token 残留。
- 清理未使用导入/变量（loader/position_sizer/exit_advisor/goal_metrics 等），`zip(strict=True)`，`strategy_feedback` 可变默认参数。

## 2. 决策核心本轮已修（每个都有测试）

| 文件 | 修复 | 依据 |
|---|---|---|
| strategy_feedback.py | ①短窗口（未来数据< N 交易日）返回 None，不许把 1 日收益当 3/5/10 日；②汇总胜率 dropna，NaN 组整行不入策略权重；③无平仓真实交易 apply=False；④无任何数据 apply=False——任何情况下不再把默认风控写回 risk_config.json | 独立复核 MAJOR-1/3 |
| walk_forward.py | 测试集指标用「截至测试期末的全量历史」预热，MA/RSI 在测试首日已就绪（无未来泄漏） | 上轮 M4 |
| portfolio_manager.py | sim 账户持仓并入 get_held_codes（两套真相源合并防重复推荐）；持有日数幂等用独立 `last_hold_increment_date`（同日重跑不 +1，且不被 add/remove 干扰） | 上轮 B2/M4 + 复核 MINOR |
| position_sizer.py | 选股回退从 pick_*.md + parse_report_full 解析（旧 strategy_* 文件名 + 13 列正则永远 0 命中，会落入全市场前 N 的危险兜底） | 上轮 M7 |
| etf_gate.py | 评估源按文件 mtime 取最新可解析（不再无条件优先陈旧的 honest_evaluation）；stat 异常防护 | 上轮 M2 |
| strategy_arena.py | 优先 `arena_<id>_equity.csv`；共用曲线标记 proxy；**全部 proxy 时跳过淘汰/变异**（防随机淘汰）；报告标「代理」 | 上轮 M8 + 复核 MAJOR-4 |
| check_trading_day.py + utils/trading_calendar.py（新增） | 周一「上一工作日行情」歧义分支先问本地缓存+akshare 兜底的交易日历；日历不可用退回 fail-open | 上轮 B1 |
| evolve_daily_light.py | IMPROVEMENT_THRESHOLD 0.20 直接比较（旧 /100 成 0.003，门槛形同虚设） | 上轮 m5 |
| data_validator.py | history lag 改交易日口径（与 _self_check 一致） | 上轮 m4 |
| psychology_assistant.py | 移除重复 check_readiness 调用（tip.body 已含准备度；重复调用会翻倍 upgrade_suggestions 计数，提前触发被动升级） | 独立复核 MAJOR-2 |
| app/pages.py | 录入真实成交后立即重算 behavior_log（收盘补录不再停留在"未操作"）；成本看板去掉「本地节省=月成本×3」误导指标 | 上轮 M3/m5 |

## 3. 独立复核结论（原文要点）

- 无 BLOCKER、无需整体回退；上一轮方向正确。
- 抓到并已回修：strategy_feedback NaN 污染胜率、无数据重置风控、psychology 重复状态变更、arena proxy 无消费方。
- 提交注意：`utils/trading_calendar.py` 与新增测试必须一起入库（已确认包含）。

## 4. 验证

| 检查 | 结果 |
|---|---|
| pytest | **383 passed / 2 xfailed / 0 failed**（新增 tests/test_v87_deep_audit_fixes.py 12 用例） |
| ruff E9/F821 | 全部通过（未定义变量清零） |
| smoke_tests | **53/53 OK** |
| _self_check | **163 项：160 PASS / 1 WARN / 2 FAIL**；剩余 3 条仍为改动前数据新鲜度（stock 85.8h / history 12 天 / exit advisor 295h） |
| 生产数据 | 12 个状态文件 SHA-256 与审计前一致 |
| API 成本 | 0 元（全程离线） |

## 5. 仍未动（真正需要外部多模型/外部数据源评审的）

1. sim_trade 当日收盘成交 vs 回测次日开盘的口径统一（资金口径变更）。
2. position.max_single_position=1.0 与文档 15% 的冲突（风控参数变更）。
3. monte_carlo 历史偏移窗口仍用最新行情快照（前视信息）。
4. `_self_check` import 即执行整份自检的函数化重构；pages.py 拆包；utils/paths 全量收敛。
5. Windows 计划任务 LastResult=9009 的人工核查（任务计划器「起始于」）。
6. Bark token 轮换（旧 token 已进 Git 历史）。
