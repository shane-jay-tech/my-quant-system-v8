# TodoCheckpointDraft — Bark 推送成本/风控口径统一（Round 2 Slice）

- 状态：slice 完成；GOAL 仍未完成（active，下一轮继续）。
- 完成 todo：Flash 方案与 Pro 评审；builders 逐笔成本 + 动态风控尾部；formatters 动态风控/仓位文案 + 强熊空仓 + 空候选池修复；newbie 指令卡动态参数；11 项新测试；全量验证；归档与 memory。
- 证据：`90-evidence.md`；`docs/decisions/2026-08-24-impl-bark-cost-guidance.md`。
- 阻塞项：无。
- Next：成本门槛显式 gate / 真实-模拟口径一致性审计 / 数据完整率与流水线成功率统计。

## ResumeStateHint

- 从这里继续：读本文件 + GOAL.md + memory.md 末尾。
- 已锁契约：`build_tomorrow_guide(stocks, bt_data)` 签名不变；`_build_friction_cost_addendum()` 使用 `ORDERS_DIR`（str + glob）；测试通过 monkeypatch `builders.ORDERS_DIR` / `formatters.ORDERS_DIR` / `cfg_get` 注入。
- 不要退回：不得在推送层恢复硬编码佣金率/止损止盈文案。

## DriftCheckDraft

- 服务原目标：是（成本真实口径 + 推送守纪律）。
- 兼容边界：仅显示/推送层，未动引擎计算、阈值、数据源。
- 新 fallback：`_latest_order_regime()` 文件缺失返回空串并回退安全文案；无新 owner 冲突。
- 证据：11 项新测试 + 生产订单真实输出。
- 决策：continue。
