# 2026-08-24 — Bark 推送成本/风控口径统一（Round 2）

## 元数据

- 任务类型：显示/推送口径修复（成本附录 + 风控文案 + 新手指令卡）
- 难度评分：影响面 1 + 风险领域 1 + 歧义度 0 + 新颖度 0 + 不可逆性 0 + 长程影响 1 = **3 → L2**
- 调用模型：Flash `deepseek-v4-flash` quick 出方案；DeepSeek V4 Pro 本会话仲裁评审；按根配置 L2 未触发 GPT 双实现
- override：0
- 测试：pytest **258 passed / 2 xfailed**（本轮前 247，净增 11）；smoke 48/48；py_compile 通过
- API 成本：本轮 Flash 0.4017 元 + smoke 外部探测 deepseek 1.5651 元；今日累计 4.11 元 < 20 元预算

## 原始需求

GOAL 的成本层要求「所有报告只用含 5 元最低佣金的真实口径」；体验层要求推送帮人守纪律，而不是给互相矛盾的旧参数。审计发现 Bark 推送层三处实际错误：

1. `bark_sender/builders.py::_build_friction_cost_addendum()` 读错订单字段（`实际投入/买入金额`，真实字段是 `金额`）→ 摩擦成本附录**从来没显示过**；且佣金硬编码 0.00025（cost_model 真相源是 0.0003），还把总买入额只套一次 5 元最低佣金，多笔订单时严重低估。
2. `build_bark_message_simple()` 写死「止损-8% | 止盈+15% | 持5-10天」；真实配置是 -8% / +20% / 10 天。
3. `formatters.build_tomorrow_guide()` 写死「每只 8%-12%、单票≤15%、总仓位牛市6-8成、止损-5%、止盈+10%/+20%」，与 2400 元小资金模式（除强熊外全仓、前 3 只、单票上限 1/3、止损-8%、止盈+20%、持有 10 天）直接冲突；另把候选池规模写死成 478 只。
4. `newbie_instruction_card.py` 写死「持有5-10天」「涨了15%以上卖一半」，同样与真实配置不符。

## Flash 方案（quick，verbatim）

## 方案概览

- 成本常量统一从 `cost_model` 导入；`sim.*` 统一从 `core.config.get` 读取。
- 不修改 `position_sizer/sim_trade` 的任何计算，不新增配置字段，不修改策略参数本身。
- 只改显示层：`bark_sender/builders.py`、`bark_sender/formatters.py`，并补测试。

---

## 1. `bark_sender/builders.py`

### 1.1 导入与模块级常量

```python
from pathlib import Path
from cost_model import COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE
from core.config import get as get_config

# 原代码如果还用 glob，可删除；订单目录用模块常量便于测试时 monkeypatch
_ORDERS_DIR = Path("orders")
```

### 1.2 重写 `_build_friction_cost_addendum()`

关键改动：

- 读取真实字段 `金额`；
- 改为逐笔计算佣金，每笔都套 `max(金额 × COMMISSION_RATE, COMMISSION_MIN)`；
- 买卖双边都收佣金，印花税只算卖出单边；
- 文件缺失/JSON 异常/无有效订单时静默返回空字符串。

```python
def _build_friction_cost_addendum():
    try:
        files = sorted(_ORDERS_DIR.glob("daily_orders_*.json"))
        if not files:
            return ""

        data = json.loads(files[-1].read_text(encoding="utf-8"))
        orders = data.get("订单") or []

        total_buy = 0.0
        round_trip_fee = 0.0

        for order in orders:
            amount = float(order.get("金额") or 0)
            if amount <= 0:
                continue

            total_buy += amount
            commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
            # 买入佣金 + 卖出佣金 + 卖出印花税
            round_trip_fee += commission * 2 + amount * STAMP_TAX_RATE

        if total_buy <= 0:
            return ""

        ratio = round_trip_fee / total_buy * 100

        return (
            f"\n📄 摩擦成本估算：买入总额 ¥{total_buy:.0f}，"
            f"往返费用约 ¥{round_trip_fee:.2f}"
            f"（按每笔买入/卖出最低佣金 ¥{COMMISSION_MIN:.0f}、"
            f"卖出印花税 {STAMP_TAX_RATE:.2%} 估算，"
            f"占买入额 {ratio:.2f}%）"
        )
    except Exception:
        return ""
```

### 1.3 修复 `build_bark_message_simple()` 尾部写死文案

新增一个读取 `sim.*` 的私有函数：

```python
def _get_config_float(key: str, default: float) -> float:
    try:
        value = get_config(key)
        return float(value) if value is not None else default
    except Exception:
        return default


def _sim_rule_tail() -> str:
    stop_loss_pct = _get_config_float("sim.stop_loss_pct", -0.08)
    take_profit_pct = _get_config_float("sim.take_profit_pct", 0.20)
    max_hold_days = int(_get_config_float("sim.max_hold_days", 10))

    return (
        f"止损{stop_loss_pct:.0%} | "
        f"止盈{take_profit_pct:+.0%} | "
        f"持{max_hold_days}天"
    )
```

在 `build_bark_message_simple()` 中替换：

```python
# 原：tail = "止损-8% | 止盈+15% | 持5-10天"
tail = _sim_rule_tail()
```

---

## 2. `bark_sender/formatters.py`

### 2.1 新增读取配置与判断强熊的私有方法

```python
from core.config import get as get_config


def _get_config_float(key: str, default: float) -> float:
    try:
        value = get_config(key)
        return float(value) if value is not None else default
    except Exception:
        return default


def _is_strong_bear(bt_data) -> bool:
    if not bt_data:
        return False

    if isinstance(bt_data, dict):
        for key in ("market_regime", "regime", "trend", "market_state"):
            if "强熊" in str(bt_data.get(key, "")):
                return True
        return "强熊" in str(bt_data)

    return "强熊" in str(bt_data)
```

### 2.2 重写【仓位与风控】文案生成

```python
def _build_risk_section(bt_data) -> str:
    initial_capital = _get_config_float("sim.initial_capital", 2400)
    stop_loss_pct = _get_config_float("sim.stop_loss_pct", -0.08)
    take_profit_pct = _get_config_float("sim.take_profit_pct", 0.20)
    max_hold_days = int(_get_config_float("sim.max_hold_days", 10))

    if initial_capital <= 3000:
        if _is_strong_bear(bt_data):
            position_line = "总仓位：空仓等待（强熊信号）"
        else:
            position_line = "总仓位：小资金模式可全仓；最多同时持有3只，单票上限1/3"
    else:
        position_line = (
            "每只股票仓位：总资金8%-12%（单票不超过15%）；"
            "总仓位：牛市6-8成，震荡/熊市3-5成"
        )

    return (
        "【仓位与风控】\n"
        f"{position_line}\n"
        f"止损线：{stop_loss_pct:.0%}（收盘有效跌破止损价/MA20 次日离场）\n"
        f"止盈参考：{take_profit_pct:+.0%}\n"
        f"持有周期：最长 {max_hold_days} 天"
    )
```

在 `build_tomorrow_guide(stocks, bt_data)` 中，把原来的 4 行写死风控文案替换为：

```python
risk_section = _build_risk_section(bt_data)
```

并放到原【仓位与风控】所在位置。

---

## 3. 需要新增的测试用例清单

| 测试名称 | 关键断言 |
|---|---|
| `test_friction_addendum_uses_amount_field_and_per_order_min_commission` | 在 `tmp_path` 写 3 笔各 800 元的订单，monkeypatch `builders._ORDERS_DIR`；断言输出含 `"2400"`，且费用按 `cost_model` 常量计算为 `31.20` 左右 |
| `test_friction_addendum_empty_when_no_files` | 空 `tmp_path` 下调用返回 `""` |
| `test_friction_addendum_silent_on_bad_json` | 写非法 JSON 文件，调用返回 `""`，不抛异常 |
| `test_friction_addendum_handles_empty_orders` | 写 `{"订单": []}`，调用返回 `""` |
| `test_simple_message_tail_reads_config` | monkeypatch `builders.get_config` 返回 `sim.take_profit_pct=0.20`、`sim.max_hold_days=10`；断言消息含 `"止盈+20%"`、`"持10天"`，且不含 `"止盈+15%"`、`"持5-10天"` |
| `test_simple_message_tail_safe_fallback` | config 返回 `None`；断言仍输出安全文本 `"止盈+20%"`、`"持10天"`，不抛异常 |
| `test_tomorrow_guide_small_capital_risk_section` | monkeypatch `formatters.get_config` 返回 2400/-0.08/0.20/10；断言风控含 `"小资金"`、`"1/3"`、`"-8%"`、`"+20%"`、`"10天"`，且不含 `"8%-12%"`、`"牛市6-8成"`、`"-5%"`、`"+10%卖1/3"` |
| `test_tomorrow_guide_strong_bear_empty_position` | `bt_data={"market_regime": "强熊"}`；断言风控含 `"空仓"`，且不含 `"可全仓"` |
| `test_tomorrow_guide_large_capital_keeps_legacy_text` | `sim.initial_capital=100000`；断言仍显示 `"8%-12%"`、`"牛市6-8成"` |
| `test_tomorrow_guide_bt_data_empty_dict` | 调用 `build_tomorrow_guide([], {})`，断言不抛异常且包含 `【仓位与风控】` |

测试要点：所有订单文件都写在 `tmp_path` 下并通过 `monkeypatch.setattr(builders, "_ORDERS_DIR", tmp_path)` 注入，不读写生产 `orders/` 目录。

---

## 4. 风险点

- `bt_data` 的“强熊”字段名目前按 `market_regime / regime / trend / market_state` 兼容；如果实际数据结构使用其他字段，需要按真实结构补充 key，否则强熊空仓文案不会触发，但不会抛异常。
- 成本估算假设每日订单均为买单，且卖出金额按买入金额估算；如果未来 `daily_orders_*.json` 包含卖出单，需要按方向过滤，否则费用会重复计算。
- `_ORDERS_DIR = Path("orders")` 与原相对路径行为一致；测试中通过 monkeypatch 指向 `tmp_path`，不影响生产。
- 测试中 patch `builders.get_config` / `formatters.get_config` 时，要以代码实际导入方式为准；如果项目是 `from core.config import get`，则对应 patch 名称为 `get`。


## 总指挥评审与修改

- 采纳 Flash 主方案：逐笔套 5 元最低佣金、常量读 cost_model、simple 尾部读 sim.*、formatters 读真实配置。
- 修正两点：`ORDERS_DIR` 保持字符串形式与现有 glob 调用兼容；风险文案不保留旧「8%-12%」大资金文案，统一改为真实五档仓位表（强牛80/弱牛60/震荡40/弱熊20/强熊0）。
- 新增：`_latest_order_regime()` 从最新 daily_orders 读市场档位，强熊时明示「空仓观望」；顺手修复 `build_tomorrow_guide` 空候选池会除以 10 崩溃的旧缺陷（min(10, max(1, n))）。
- 扩展同一 slice 到 `newbie_instruction_card.py`：持有天数/止盈文案读配置。

## 落地改动

- `bark_sender/builders.py`：导入 cost_model/core.config；`_build_friction_cost_addendum()` 逐笔计算 `max(金额×0.0003, 5)`，卖印花 0.0005，输出每笔笔数与真实费率；`_sim_rule_tail()` 动态生成止损/止盈/持有天数。
- `bark_sender/formatters.py`：`_risk_control_lines()` 动态生成仓位/止损/止盈/持有周期；`_latest_order_regime()` 读当日市场档位；候选池规模动态；兜底风险提示改为「Alpha Gate 提示连续跑输 → 空仓或改持 510300/510310 ETF」。
- `newbie_instruction_card.py`：持有天数/止盈阈值读 `sim.*` 配置。
- `tests/test_bark_cost_guidance.py`：11 项回归（逐笔佣金 3×800=31.20、空文件/坏 JSON 静默、simple 尾部、小资金文案、强熊空仓、大资金分档、新手指令卡、空候选池不崩）。

## 验证证据

- `python -m pytest -q` → **258 passed, 2 xfailed**
- `python smoke_tests.py` → **48 OK / 0 FAIL**
- `python -m py_compile bark_sender/builders.py bark_sender/formatters.py newbie_instruction_card.py` → OK
- 真实文件直跑：最新 `daily_orders_20260821.json`（1 笔 ¥467）→ 附录显示「往返费用 ¥10.23 / 成本占比 2.19%」；simple 尾部显示「止损-8% | 止盈+20% | 持10天」；guide 显示小资金模式文案。

## 风险

1. 摩擦成本附录只按买入单估算卖出金额（每日订单 JSON 里卖出建议没有统一金额字段），印花税按买入额估；真实卖出金额可能不同，但方向保守、不会低估佣金 floor。
2. `_latest_order_regime()` 依赖本地订单文件；文件缺失时风控文案回退到「除强熊外全仓」表述，不显示空仓提示——最坏情况是文案少一句，不会改系统实际仓位计算。
3. 本次只改显示/推送，没有动 position_sizer/sim_trade 的仓位与成本计算；若推送数字与实际引擎仍有偏差，下一轮需要做「推送 vs 引擎」全链路一致性测试。

## 下一轮候选

- 每笔订单的显式成本门槛 gate（目前靠小资金模式间接控制）。
- 真实账户与模拟账户止损/仓位口径一致性审计。
- 数据完整率、流水线成功率的自动统计口径。
