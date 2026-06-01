# 2026-08-24 — 每笔订单成本门槛（Round 4）

## 元数据

- 任务类型：新增风控 gate（订单成本门槛）+ 执行防线二
- 难度评分：影响面 2 + 风险领域 2 + 歧义度 1 + 新颖度 1 + 不可逆性 0 + 长程影响 2 = **8 → L3**
- 调用模型：Flash `deepseek-v4-flash` quick（A/B）；GPT-5.6-terra 经 Codex CLI（read-only，effort=high）；DeepSeek V4 Pro 本会话仲裁。health_check 8 通道全 OK。
- override：0
- 测试：pytest **277 passed / 2 xfailed**（基线 267，净增 10）；smoke 48/48；py_compile 通过
- API 成本：本轮 Flash 0.2177 元；今日累计 6.18 元 < 20 元

## 原始需求

GOAL 策略层要求「每笔订单过成本门槛」。此前系统只有间接约束（小资金前 3 只 + 5 元佣金 floor），没有显式 gate，也没有执行层防线。历史 15 笔订单的往返成本分布（含 5 元最低佣金与分档滑点）：min 0.97% / p25 1.14% / 中位 1.82% / p75 2.21% / p90 2.61% / max 2.84%。默认门槛 2.5% 只截掉最贵的约 13%（418 元 2.84%、435 元 2.75%），不会剧变现有行为，同时把「门槛」从口头变成可测试的硬规则。

## Flash A/B（quick，verbatim）

## 公共前置改动（A/B 共用）

**core/config.py / DEFAULTS**

```python
DEFAULTS.setdefault("cost", {})["order_gate_max_pct"] = 0.025
```

**data/system_config.json**

```json
"cost": {
  "...": "...",
  "order_gate_max_pct": 0.025
}
```

**cost_model.py：增加原子门槛判断纯函数**

```python
def order_passes_cost_gate(amount, mcap=0, max_pct=None):
    cost = round_trip_cost(mcap, amount, with_slippage=True)
    if max_pct is None:
        max_pct = DEFAULTS["cost"]["order_gate_max_pct"]
    return cost.rate <= max_pct, cost
```

> 只新增判断，不落盘、不修改成本公式。

---

## 方案 A：就地双保险

### 关键 diff

**position_sizer.py**

```python
def _try_add_order(orders, order, max_pct, stats):
    ok, cost = order_passes_cost_gate(
        order["amount"], order.get("mcap", 0), max_pct
    )
    if not ok:
        stats["cost_gate_skipped"] += 1
        print(f"[cost_gate] 跳过 {order.get('symbol')}: "
              f"往返成本率 {cost.rate:.2%} > {max_pct:.2%}")
        return False

    order["往返成本率"] = cost.rate
    order["往返成本"] = cost.total
    orders.append(order)
    return True
```

在 `calculate_position_sizes` 中：

- top3 每个订单生成后立刻调 `_try_add_order`
- `orders` 为空时走“最强 1 只”fallback
- fallback 也必须过同一门槛
- 全部不过则返回空 `orders`
- `summary["cost_gate_skipped"]` 统计被门槛跳过的数量

**sim_trade.py**

```python
for order in orders:
    ok, cost = order_passes_cost_gate(
        order["amount"], order.get("mcap", 0), max_pct
    )
    if not ok:
        print(f"[cost_gate] 防御二跳过 {order.get('symbol')}: "
              f"{cost.rate:.2%}")
        continue

    # 原有执行逻辑不变
    ...
```

### 优点

- 逻辑直白，diff 小，容易 review
- 生成端和执行端各自实时调用 `order_passes_cost_gate`，防御最直接
- 保留原有 fallback 结构，改动风险小

### 缺点

- `position_sizer` 和 `sim_trade` 有相似的判断/打印/统计代码
- 以后如果新增其他生成订单入口，容易忘记加同一道门槛

---

## 方案 B：共享过滤器

### 关键 diff

**cost_model.py 追加一个共享过滤函数**

```python
def filter_orders_by_cost_gate(orders, max_pct=None,
                               amount_key="amount", mcap_key="mcap"):
    passed, rejected = [], []

    for order in orders:
        amount = order.get(amount_key)
        if amount is None:
            amount = order["shares"] * order["price"]

        ok, cost = order_passes_cost_gate(
            amount, order.get(mcap_key, 0), max_pct
        )

        if ok:
            order["往返成本率"] = cost.rate
            order["往返成本"] = cost.total
            passed.append(order)
        else:
            rejected.append((order, cost))

    return passed, rejected
```

**position_sizer.py**

```python
passed, rejected = filter_orders_by_cost_gate([order], max_pct)
if passed:
    orders.append(passed[0])
else:
    stats["cost_gate_skipped"] += 1
    print(...)
```

fallback 同样用 `filter_orders_by_cost_gate([fallback_order], max_pct)` 过滤。

**sim_trade.py**

```python
passed, rejected = filter_orders_by_cost_gate(orders, max_pct)

for order, cost in rejected:
    print(f"[cost_gate] 防御二跳过 {order.get('symbol')}: {cost.rate:.2%}")

for order in passed:
    # 原有执行逻辑不变
    ...
```

### 优点

- 过滤、打印、成本字段填充逻辑收敛到一处
- 生成端和执行端使用同一套规则，不会出现两套逻辑漂移
- 以后新入口直接调 `filter_orders_by_cost_gate` 即可

### 缺点

- 多一层抽象，批量过滤后执行顺序和对象引用需要更小心
- `sim_trade` 不再是一眼可见的“逐单 if”，略绕
- 需要额外处理旧订单缺少 `amount` / `mcap` 的情况

---

## 推荐：融合

以 **方案 A 的逐单实时判断为骨架**，把 **方案 B 的 `filter_orders_by_cost_gate` 作为共享 helper** 吸收进来：

- `position_sizer` 和 `sim_trade` 都用 `filter_orders_by_cost_gate`
- 但每次调用必须内部走 `order_passes_cost_gate` 实时计算成本
- 不在生成端提前打“已通过”标记后让执行端直接信任

一句话理由：  
**成本门槛必须同时覆盖生成端和执行端，共享 helper 能避免两套逻辑漂移，但最终判定仍要逐单实时计算。**

---

## 测试注意

- 新增测试不要写生产文件，用 `tmp_path` / `monkeypatch`
- 测试 `sim_trade` 时，`order_passes_cost_gate` 可用 monkeypatch 伪造 `(True, fake_cost)`，或把 `order_gate_max_pct` 临时调高，避免现有小额测试订单因 5 元佣金 floor 成本率高而误伤
- 重点覆盖：
  - top3 全部过门槛
  - top3 部分被门槛跳过
  - top3 全部不过 → fallback 过
  - top3 全部不过 → fallback 也不过 → 返回空 orders
  - sim_trade 收到手工/旧订单文件时，防御二能跳过超高成本订单


## GPT-5.6 独立方案（Codex CLI，verbatim）

只读核对完成，未改文件、未联网。

## 方案 A：调用边界读取配置（推荐）

关键改动：

- `core.config.DEFAULTS["cost"]` 与 `data/system_config.json["cost"]` 增加：
  ```json
  "order_gate_max_pct": 0.025
  ```

- `cost_model.py` 增加纯函数；只计算，不读写配置或文件：
  ```python
  def order_passes_cost_gate(amount, mcap=0, max_pct=None):
      limit = 0.025 if max_pct is None else float(max_pct)
      breakdown = round_trip_cost(mcap, amount, with_slippage=True)
      return amount > 0 and breakdown.rate <= limit, breakdown
  ```

- `position_sizer.py` 在“股数取整、单票上限处理后”的 `actual_amount` 上过门槛；市值取候选行的 `流通市值`，缺失则传 `0`，按小盘滑点保守处理。
  - 不通过：不入 `orders`，打印代码、金额、往返成本率、阈值。
  - 订单补充 `流通市值`、`往返成本`、`往返成本率`。
  - 小资金主候选全被成本门槛拒绝时，保留现有“最强一只”回退；回退候选逐只也必须重新过门槛。
  - 汇总增加 `cost_gate_max_pct`、`cost_gate_skipped`、`cost_gate_fallback_used`，最好再拆分主候选与回退候选的拒绝数。
  - 为保持原有行为，“一手太贵”导致主候选全空的旧回退逻辑不应被删掉。

- `sim_trade.py` 在滑点后的实际成交额上再次检查，使用订单携带的 `流通市值`；旧手工订单缺市值时按 `0` 保守处理。
  - 新开仓：按完整成交额检查。
  - 已有持仓的调仓订单：仅对“增加股数”对应的增量金额检查；减仓或不变不应被成本门槛拦截。
  - 阈值由 `cfg_get("cost.order_gate_max_pct", 0.025)` 在两个调用边界读取后显式传给纯函数，因此修改配置无需重启进程。

测试建议：

- `test_cost_model.py`：400 元小盘拒绝、600 元小盘通过、显式 `max_pct` 覆盖默认值、返回 `CostBreakdown`。
- `test_position_sizer.py`：Top3 都因成本拒绝后，1200 元单票回退通过；回退候选也全拒绝时返回空单；断言 summary 计数。
- 新增 `test_order_cost_gate.py`：模拟执行层拒绝低金额旧/手工订单；用 `monkeypatch` 将阈值设为 `1.0`，锁定旧的小额订单执行行为。测试目录全部使用 `tmp_path`，不触碰生产文件。

优点：纯函数边界清晰、配置可即时生效、执行层按真实滑点后金额复核，避免旧订单绕过。  
缺点：两个调用点各有一行读取配置。

## 方案 B：成本模块在导入时缓存门槛

关键改动与 A 基本相同，但 `cost_model.py` 在模块加载时定义：

```python
ORDER_GATE_MAX_PCT = cfg_get("cost.order_gate_max_pct", 0.025)
```

而 `order_passes_cost_gate(..., max_pct=None)` 的 `None` 使用该常量；`position_sizer` 和 `sim_trade` 不再显式读取配置。

优点：调用点更简洁，所有成本参数都集中在 `cost_model.py` 的模块级常量风格中。  
缺点：配置修改后要重启或重载模块才会生效；与“纯函数”要求相比，函数的默认行为更依赖模块初始化状态；测试配置覆盖也更容易受导入顺序影响。

## 推荐：方案 A

理由：成本门槛是可调风控参数，A 在不牺牲 `cost_model` 纯计算属性的前提下，让生成订单和实际成交两道防线都使用当前配置，并且按真实成交金额复核。


## 总指挥仲裁

- 采纳 Flash 的「公共纯函数 + 两道防线」与 GPT 的方案 A 细化。
- 关键补充/否决：
  1. 否决 GPT 的「sim_trade 按订单整体金额检查已有持仓调仓」——已有持仓减仓/不动是回收资金，不应被买入门槛拦截；只对**新增投入金额**过 gate。
  2. 采纳 GPT 的「订单携带流通市值，缺省按 0（小盘滑点最保守）」。
  3. 采纳 Flash 的 `order_passes_cost_gate(amount, mcap, max_pct)` 纯函数，max_pct 由两个调用边界从 core.config 显式传入，函数不读配置，保持 cost_model 纯计算属性。
  4. fallback（top3 全被拦 → 最强 1 只）也过同一门槛；全部不过则空仓，不允许「硬买高成本订单」。

## 落地改动

- `core/config.py` / `data/system_config.json`：新增 `cost.order_gate_max_pct=0.025`。
- `cost_model.py`：新增 `order_passes_cost_gate(amount, mcap=0, max_pct=None) -> (bool, CostBreakdown)`；amount<=0 恒不过。
- `position_sizer.py`：新增 `_order_cost_gate_max_pct()` / `_append_order_if_cost_ok()`；每个候选订单生成后立即过门槛，订单写入 `流通市值/往返成本/往返成本率`；summary 增加 `cost_gate_max_pct / cost_gate_skipped / cost_gate_fallback_used`；fallback 候选逐只过门槛，全部不过返回空单。
- `sim_trade.py`：防线二 `_order_cost_gate_check()`；新买入按实际滑点后成交额过门槛；已有持仓只对加仓增量过门槛；减仓/不变不拦截。
- `tests/test_cost_gate.py`：10 项回归（纯函数、三道 sizer 场景、强熊空仓、sim 拒绝/接受/减仓不拦）。

## 验证证据

- `python -m pytest -q` → **277 passed, 2 xfailed**
- `python smoke_tests.py` → **48 OK / 0 FAIL**
- `python -m py_compile cost_model.py core/config.py position_sizer.py sim_trade.py` → OK
- 历史 15 笔订单回放：默认 2.5% 门槛下 2 笔会 SKIP（000088@435 2.75%、600266@418 2.84%），其余 13 笔 PASS；与设计目标一致。

## 风险

1. 默认 2.5% 是基于现有 15 笔历史订单分布选择的保守上界，不是回测优化结果；门槛过低会强制空仓/集中，过高则形同虚设。阈值已配置化，后续可用 walk-forward/回测证据再校准。
2. 成本门槛包含滑点估算（按流通市值分档），但真实成交滑点可能更高；订单文件里的 `往返成本率` 是估算口径而非成交口径。
3. 加仓增量的 gate 只检查新增投入金额，未检查合并后整仓成本；若同一只票反复小额加仓，单次增量可能都过门槛，但总摩擦仍偏高——现有单票上限 1/3 与持有排除机制部分对冲。

## 下一轮候选

- 阈值校准：用回测/前向收益对 2.0% / 2.5% / 3.0% 做证据比较。
- 「弱信号不买」评分门槛研究。
- 数据完整率 / 流水线成功率统计。
