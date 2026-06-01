# 2026-08-24 — 仓位计划预留佣金：现金可执行性收口（Round 10）

## 元数据

- 任务类型：仓位/执行口径一致性修复（硬触发：仓位计算 → L3）
- 难度评分：影响面 2 + 风险领域 2 + 歧义度 1 + 新颖度 0 + 不可逆性 0 + 长程影响 2 = **7 → L3**
- 模型：Flash A/B + GPT-5.6-terra（Codex CLI）独立方案 + Pro 本会话仲裁。health_check 全 OK。
- override：0
- 测试：pytest **307 passed / 2 xfailed**（基线 302，净增 5）；smoke 48/48；py_compile 通过
- API：本轮 Flash 0.3031 元；今日累计 7.26 元 < 20 元

## 症状与复现

- 本金 2400，3 只候选各 8 元：position_sizer 出 3 笔订单（每笔 800，合计 2400）。
- sim_trade 每笔要扣 800+5 佣金，3 笔需 2415；现金不足跳过第 3 笔 → 订单文件说买 3 只，实际只成交 2 只。
- 新端到端测试 `tests/test_risk_consistency_end_to_end.py` 复现（修复前 FAIL）。

## Flash A/B（quick，verbatim）

先说统一口径：  
- 只改 `position_sizer.py`，`sim_trade.py` 保持原样，保留“现金不足 skip”作为最后防线。  
- 不碰评分、买卖公式、止损止盈、成本门槛阈值。  
- 每笔买入费用统一从 `cost_model.order_cost_amount('buy', amount, mcap)` 取，不硬编码 `5`。  
- 现金池用现有 `investable`；小资金模式下 `investable = total_capital`，所以满足你的 `sum(amount + fee) <= total_capital` 目标。

---

## 方案 A：生成后做“现金可行性裁剪”

### 关键改动

1. 新增订单费用估算函数：

```python
def _estimated_buy_cost(order, cost_model):
    fee = cost_model.order_cost_amount(
        order['方向'], order['金额'], order['流通市值']
    )
    return fee, order['金额'] + fee
```

2. 新增 `_fit_orders_to_cash(orders, cash_budget, cost_model)`：  
   - 按原始订单顺序逐笔处理，不重新排序。  
   - 如果当前订单 `金额 + 费用 <= cash_left`，直接保留。  
   - 否则尝试把股数减少一档（`100` 股），重新计算 `金额/费用/总成本`。  
   - 如果减少到 `0` 还不能成交，就丢弃该订单，继续看下一只候选。  
   - 每次调整后继续用现有 `order_passes_cost_gate(amount, mcap, 0.025)` 校验；失败则放弃该订单。  
   - 保留原始“强者优先”顺序，所以只保留 1 只时会留下最强的那 1 只。

3. 在 `calculate_position_sizes` 的 return 前统一调用：

```python
orders = _fit_orders_to_cash(orders, investable, cost_model)
```

- top3 正常路径和 fallback“最强 1 只全押”路径都走同一个函数。  
- fallback 也会被费用约束修正，不会出现 `2400 全押` 后实际成交不了的情况。

4. 订单字段增加：

```python
order['预计佣金'] = fee
order['预计总成本'] = order['金额'] + fee
```

5. summary 增加：

```python
summary['预计佣金合计'] = sum(o['预计佣金'] for o in orders)
summary['预计占用现金'] = sum(o['预计总成本'] for o in orders)
```

### 优点

- 改动面小，主要在 `calculate_position_sizes` 尾部加一个后处理。  
- 不触碰原来的权重、股数、强制一手、成本门槛逻辑。  
- 和 `sim_trade.execute_buy_orders` 的逐笔扣款逻辑一致，容易验证。  
- top3 和 fallback 统一处理，行为一致。

### 缺点

- 会先构造出“不可执行”的临时订单，再裁剪或丢弃，中间过程不如直接生成时精确。  
- 需要循环重算费用，但候选数量很小，性能不是问题。  
- 不是全局最优分配，但符合“保留更强优先级”的诉求。

---

## 方案 B：生成订单时直接做“费用预算内定仓”

### 关键改动

1. 新增辅助函数：

```python
def _max_affordable_shares(price, budget, mcap, cost_model):
    """
    在 budget 内，找最大可买股数（100 股整数倍），
    且满足：
        amount + cost_model.order_cost_amount('buy', amount, mcap) <= budget
    """
```

可以用二分或步进实现，默认按 100 股一档。

2. 在生成每笔订单时，先算原始目标股数 `target_shares`，再收紧：

```python
shares = min(target_shares, _max_affordable_shares(price, cash_left, mcap, cost_model))
```

- 如果 `shares == 0`，跳过该订单。  
- 生成订单同时记录 `预计佣金`、`预计总成本`。  
- 每保留一笔订单，就从 `cash_left` 中扣除 `金额 + 佣金`。

3. 重新计算金额和仓位占比：

```python
order['金额'] = shares * price
order['仓位占比'] = order['金额'] / total_capital
```

4. 对最终金额继续使用现有 `order_passes_cost_gate` 校验；成本门槛阈值不变。

5. fallback 的“最强 1 只全押”也改成：

```python
shares = _max_affordable_shares(price, investable, mcap, cost_model)
```

### 优点

- 订单从出生开始就在现金预算内，不会产生不可执行的中间订单。  
- 更适合以后扩展“总费用预算”“单笔费用上限”等约束。  
- fallback 全押时能自然算出费用约束下的最大可买股数。

### 缺点

- 需要把费用预算逻辑插入订单生成主流程，改动更大。  
- 更容易影响原有“强制一手”“单票上限”等逻辑，回归风险比 A 高。  
- 需要保证 `_max_affordable_shares` 和 `sim_trade` 的扣款口径完全一致。

---

## 推荐

推荐：**方案 A**，可融合 B 的二分加速作为优化。

理由：A 在原有 `calculate_position_sizes` 结果上做后置现金可行性裁剪，改动最局部、最贴近 `sim_trade` 逐笔执行逻辑，也最不容易碰坏评分、成本门槛等既有规则。

---

## 测试建议

构造本地测试，不用网络：

```python
def test_2400_3x8_only_two_executable(tmp_path, monkeypatch):
    # monkeypatch cost_model.order_cost_amount 为：
    # buy 时返回 max(amount * 0.0003, 5)，模拟最低佣金 5 元
    # 本地构造 picks_df：3 只候选，价格都是 8 元
    # 调用 calculate_position_sizes(picks_df, regime, 2400)

    orders, summary = calculate_position_sizes(...)

    # 期望：只输出 2 笔订单，按原排序保留前两只
    assert len(orders) == 2

    # 模拟 sim_trade 逐笔执行
    cash = 2400
    executed = []
    for o in orders:
        total = o['金额'] + cost_model.order_cost_amount('buy', o['金额'], o['流通市值'])
        if total <= cash:
            cash -= total
            executed.append(o['代码'])

    # 订单计划必须能被完整执行
    assert [o['代码'] for o in orders] == executed

    assert summary['预计佣金合计'] == 10
    assert summary['预计占用现金'] == 1610

    # 写入 tmp_path 检查订单文件里也只剩 2 笔
    order_file = tmp_path / "orders.json"
    order_file.write_text(json.dumps(orders, ensure_ascii=False), encoding="utf-8")
    assert len(json.loads(order_file.read_text(encoding="utf-8"))) == 2
```

这样修复后，订单文件和模拟成交结果一致，`sim_trade` 的 skip 分支不会再被正常计划触发。


## GPT-5.6 独立方案（Codex CLI，verbatim）

已只读核对：`sim_trade` 实际只扣“成交额 + 佣金”，而 `cost_model.order_cost_amount('buy', ...)`还包含滑点，不能直接拿来做现金可执行性判断。

## 方案 A：生成后做“现金可执行性收口”（推荐）

保留现有选股、等权/动量、成本门槛和 fallback 流程；在 `apply_sector_cap` 后新增最终收口：

- 逐单用 `cost_model.COMMISSION_RATE`、`COMMISSION_MIN` 算预计佣金，与 `sim_trade` 当前同源同公式。
- 写入：
  - `预计佣金 = max(金额 × rate, min)`
  - `预计总成本 = 金额 + 预计佣金`（即模拟账户实际扣现金额）
- 按当前候选优先级依次保留订单；若剩余现金不足，则以 100 股为步长缩减该单，缩至不能买一手则跳过。
- 每次缩股后重新跑成本门槛，避免缩小后因最低佣金导致成本率超标。
- 汇总新增 `预计佣金合计`、`预计占用现金`，并将 `cash_remaining` 改为 `总资金 - 预计占用现金`；`used_amount`仍保持成交额合计，兼容旧消费者。
- 强熊原有空仓路径不变，并补齐新增汇总字段。

2400 / 3×8 元场景会得到前两只各 100 股：

- 成交额：1600
- 预计佣金：10
- 预计占用现金：1610
- 剩余现金：790

优点：改动小、保留现有策略排序、保证计划在同一价格快照下可被 `sim_trade` 全部执行。  
缺点：属于贪心收口；在复杂的不同价格组合下，不保证找到全局最优的组合。

## 方案 B：在生成订单阶段做离散组合优化

把每只候选的可选股数建成 `0、100、200 … 原计划股数`，以“预计总成本不超过本金”为硬约束，枚举小资金 top-3 的可行组合。

目标可设为：

1. 最大化可成交标的数；
2. 再最大化候选优先级/动量；
3. 再最大化实际投入金额；
4. 同分时选价格更低或原排序更靠前的组合。

同样写入预计佣金、预计总成本及汇总字段。

优点：全局最优，能严格落实“能留两只就留两只；只能留一只就留最强一只”。  
缺点：逻辑和测试明显更复杂；需明确“动量、原排序、便宜”的精确优先级，避免后续争议。

## 推荐：方案 A

这是一次执行资金口径修复，方案 A 以最小改动建立“计划一定可执行”的硬不变量；top-3 小资金场景下效果与组合优化一致。

测试应使用 `tmp_path` 隔离目录、`monkeypatch` 固定成本门槛与配置，并同时断言：

- 2400、三只 8 元候选最终为两笔、保留前两只；
- `sum(订单['预计总成本']) <= 2400`，且为 1610；
- 汇总佣金为 10、预计占用现金为 1610；
- 将同一订单和同一价格快照喂给 `sim_trade.execute_buy_orders` 后，2 笔都成交、现金为 790。

注意：该保证以订单生成时的价格快照为准；若模拟执行取到更高的新价格，`sim_trade` 的现金不足防线仍应继续保留。


## 总指挥仲裁

- 采纳 A（后置现金收口），并采用 GPT 的关键修正：**现金判定只算佣金**，不能用 `cost_model.order_cost_amount('buy')`——那里面含滑点，而 sim_trade 的滑点已经体现在成交价里，再扣一次会高估现金需求。
- 优先级保持原订单顺序（=策略优先级），现金不够先减该单 100 股，缩到不可买或不过成本门槛再放弃；因此「只能留 1 只时会留下最强 1 只」成立。
- fallback 路径同样过收口：原先「最强 1 只全押 investable」可能 2400+5 佣金超现金，收口自动缩股。
- 不改 sim_trade 现金不足 skip（防线二保留），因为执行价快照可能高于订单价（滑点/次日跳空）。

## 修复

- `position_sizer.py`：新增 `_buy_commission/_attach_cost_fields/_fit_orders_to_cash`；在 sector cap 与 0 股过滤后调用；订单新增 `预计佣金/预计总成本`；summary 新增 `预计佣金合计/预计占用现金`，`cash_remaining` 改为「本金-预计占用现金」；`_empty_summary` 契约同步补字段。
- 测试：更新 3 个受影响的既有断言；新增端到端 5 项（alert_only 一致、非 alert_only 一致、强熊空仓、sizer 预算跟随 sim 基线、real_trades 净投入驱动 sim 基线）。

## 关键场景修复后

- 2400 / 3×8：输出 **2 笔**（1600 成交额 + 10 佣金 = 1610 占用，剩余 790），sim_trade 可完整执行。
- 成本门槛 fallback（阈值 1.5%）：单票从 2400 自动缩到 1600（含佣金 1605），仍过门槛。

## 风险

1. 收口是贪心按优先级，不保证全局最优组合；top-3 小资金场景与枚举最优一致，但复杂价格组合可能不同。
2. 保证只对订单生成时的价格快照成立；次日开盘跳空/滑点后仍可能不足，sim_trade 防线二保留。
3. `cash_remaining` 语义从「本金-成交额」变为「本金-预计占用现金」，下游旧展示若自行重算可能产生小差异（当前消费者均读 summary）。

## Retirement

- 旧「出满额订单 → sim_trade 静默跳单」路径已由收口替代；sim_trade skip 保留为异常兜底。
