# TaskIntentDraft — Bark 推送成本/风控口径统一（Round 2 Slice）

- 日期：2026-08-24
- 父目标：GOAL.md（成本层真实口径 + 自动化推送稳定 + 体验层帮人守纪律）
- 难度评分：影响面 1（推送/展示，不改交易计算）+ 风险领域 1（成本与风控数字）+ 歧义度 0 + 新颖度 0 + 不可逆性 0 + 长程影响 1 = **3 → L2**
- 多模型路由：Flash 出方案（quick）+ 总指挥（DeepSeek V4 Pro 本会话）评审；按根配置 L2 不触发 GPT 双实现。

## Slice Card

- Goal：Bark 推送的摩擦成本按每笔订单分别套 5 元最低佣金且使用 cost_model 单一真相源；simple 模式与明日操作参考中的止损/止盈/持有天数/仓位文案与系统真实配置一致。
- Parent plan/spec：GOAL.md「成本层所有报告只用含5元最低佣金的真实口径」「体验层用复盘、行为与心理反馈帮人守纪律」。
- Files：`bark_sender/builders.py`、`bark_sender/formatters.py`、新增 `tests/test_bark_cost_guidance.py`。
- Boundary：不改 position_sizer/sim_trade/cost_model 的任何计算；不新增配置字段；不破坏 build_tomorrow_guide 签名；文件/配置缺失静默安全。
- Verification：`python -m pytest -q`、`python -m py_compile bark_sender/builders.py bark_sender/formatters.py`、直接调用两个函数打印输出检查。
- Stop：回归或评审 CRITICAL 未解决即停；API 预算超 20 元即停。

## BaselineReadSetHint

- `bark_sender/builders.py`（错误字段 `买入金额` + 硬编码 0.00025 + 止盈15%）
- `bark_sender/formatters.py`（8%-12%、牛市6-8成、止损-5%、止盈10/20% 旧文案）
- `cost_model.py`（COMMISSION_RATE=0.0003 / COMMISSION_MIN=5 / STAMP_TAX_RATE=0.0005）
- `core/config.py` + `data/system_config.json`（sim.stop=-0.08 / take=+0.20 / hold=10 / capital=2400）
- 基线：pytest 247 passed / 2 xfailed；API 已花 2.14 元。
