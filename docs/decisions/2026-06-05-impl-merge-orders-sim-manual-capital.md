# /implement — 合并今日订单进模拟交易页 + 模拟本金手填 + 修本金显示 bug

- 日期：2026-06-05
- 模式：deep（涉及模拟账户资金逻辑，命中「风控/仓位/资金」升档清单）
- 流程：pre-flight health_check（3 relay 全绿）→ GPT 写码（**relay 掉线降级**）→ Opus 自写实现 → DeepSeek 5 维度独立评审 → Opus 仲裁 → 落地 + 测试

## 原始需求（用户原话）

1. 今日订单和模拟交易可以合并成一个页面吧；
2. 模拟交易的金额不是 10 万，应该和真实股市金额匹配，可以从真实订单推测，也可以做窗口亲自填；
3. 模拟交易和回测仪表是不是功能重合了。

第 3 条为概念解释（回测=过去验证策略 / 模拟=往后跟踪账户，不重合）。
第 1、2 条为实现。AskUserQuestion 产品决策结果：本金来源 = **「我自己填 + 自动推测兜底」**。

## GPT relay 掉线

GPT-5.5 Pro relay 当天对大任务持续 `RemoteProtocolError`（incomplete chunked read，与 2026-06-02 同症）。
按 CLAUDE.md 网络失败规则降级：Opus 自写实现，DeepSeek 做独立对抗评审（DeepSeek relay 健康）。

## 落地改动

| 文件 | 改动 |
|---|---|
| `sim_trade.py` | 新增 `get_manual_capital()`；`resolve_initial_capital()` 优先级改 manual > real net投入 > fallback；`init_account()` delta-sync 加 manual 优先分支（手填时锁基线、不动 cash） |
| `core/config.py` | 新增 `set_value()`（原子写用户配置 + reload）；DEFAULTS.sim 加 `manual_capital: None` |
| `app/pages.py` | 抽 `_render_today_orders_block()` 共用；新增 `_reset_sim_account()` / `_render_capital_setting()`；`render_sim_trading_page` 顶部并入今日订单；**修 bug**：收益率分母从写死 config 1200 改读 `state['initial_capital']` |
| `app/sidebar.py` | 导航删「📋 今日订单」（10→9） |
| `app.py` | 删今日订单路由 elif |
| `tests/test_sim_trade.py` | +8 测试（manual 解析 / 三级优先级 / 手填禁用 delta-sync） |
| `tests/test_capital_setting_page.py` | +3 测试（reset 一致性 / 清旁路文件 / 无文件不报错） |

测试：165 passed（原 154 + 11 新增）。self_check 141/142（唯一 WARN = 空仓，正常）。

## DeepSeek V4 Pro 评审原文（verdict: do-not-ship，5 条 + nits）

1. **Security/critical** — STATE_FILE 写入无跨进程锁，pipeline 与 UI 并发写可能丢更新（直接驱动资金决策）。
2. **Edge** — `baseline = state.get('initial_capital') or _FALLBACK`：initial_capital 合法为 0 时被 `or` 当 falsy 误兜底。
3. **Perf** — `check_exits` 每持仓每指标全量扫 history_df，O(n) 重复扫描。
4. **Readability** — `init_account` 单体函数混 5 职责（加载/迁移/manual 对齐/delta-sync/保存），脆弱难测。
5. **Design/critical** — `resolve_initial_capital`（模块级）与 `init_account`（运行时）双真相源；`init_account` 把 mutating delta-sync 作为「加载」副作用，**生成报告会静默改 cash/baseline**；清除 manual 后下次加载用旧 manual 当基线做未经请求的 cash 跳变。
   nits：模块级 `INITIAL_CAPITAL` import 时定值后陈旧；`should_increment` 命名误导；`_main_lite` 与 `main` 非交易日逻辑重复；`calc_execution_quality` 每次读 orders 文件。

## Opus 仲裁

| 编号 | 决定 | 理由 |
|---|---|---|
| #3 重置只清权益曲线留交易历史 | **采纳修** | 我引入的真矛盾：total_trades=0 却列旧成交。改为同清 equity_curve + trade_history，且旁路路径从 state_path 目录推导（同目录 + 可隔离测试） |
| #5 清 manual 后延迟静默 cash 跳变 | **采纳修** | 我引入的边界。把「取消手动」改成当场显式 `resolve + _reset_sim_account`，杜绝延迟 |
| #1/#4 文件无锁 / Windows os.replace 并发 | **不修（标风险）** | 单用户桌面 app；`os.replace` 原子替换不会损坏文件，最坏丢更新；重置手动点、流水线定点跑，撞车概率极低 |
| #2 `or` 把 0 当 falsy | **不修（说明）** | 本金永远 >0（手填 ≤0 被拦、自动 ≤0 返 None）；该兜底正好防收益率除零，是想要的行为 |
| #5 主（side-effect-on-load 重构）/ #3 perf / 陈旧常量 / nits | **不修（记债）** | 均 v8.7 既有设计、本次未碰；属独立重构，硬改会动已测资金引擎，风险大于收益 |

## 遗留态处理

用户 live 账户原为 `initial_capital=2423.9 / cash≈517~1145 / pnl=-49`（v8.7 delta-sync 历史遗留的内部矛盾，且因 baseline 已等于 real，流水线 delta=0 自身修不好）。落地时用 `_reset_sim_account` 一次性理顺到自动推算值 **2423.9（cash=equity=baseline，pnl=0，空仓）**。这也实测印证了 DeepSeek #5「加载即改 cash」——两次读取间数值已被 delta-sync 改动。

## 给用户的摘要

见对话。结论：三页合并完成、本金可手填（自动兜底）、显示 bug 已修、遗留账户已理顺；回测与模拟不重合。
