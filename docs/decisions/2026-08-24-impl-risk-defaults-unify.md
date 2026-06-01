# 2026-08-24 — 风控默认值统一到 sim.* 单一真相源（Round 3）

## 元数据

- 任务类型：风控默认值/回退/文案口径统一
- 难度评分：影响面 2 + 风险领域 2 + 歧义度 0 + 新颖度 0 + 不可逆性 0 + 长程影响 2 = **6 → L3**
- 调用模型：Flash `deepseek-v4-flash` quick（A/B 方案）；GPT-5.6-terra 经 Codex CLI（read-only，effort=high）；DeepSeek V4 Pro 本会话仲裁。health_check 8 通道全 OK。
- override：0
- 测试：pytest **267 passed / 2 xfailed**（基线 258，净增 9）；smoke 48/48；py_compile 通过
- API 成本：本轮 Flash 0.2517 + smoke 外部探测 deepseek 1.6064；今日累计 5.96 元 < 20 元

## 原始需求

GOAL 要求「止损止盈与仓位跟随真实账户，模拟与实盘口径一致」。审计发现四处风控默认值互相打架：

1. `auto_heal.fix_missing_risk_config()` 重建 risk_config 时写 take=0.30 / hold=30，与系统真相源 take=0.20 / hold=10 冲突，且缺 alert_only=True。
2. `exit_advisor.py` 模块回退常量 MAX_HOLD_DAYS=30、TAKE_PROFIT_PCT=0.30；并且不识别 alert_only——sim_trade 在 alert_only=true 时忽略 risk_config 的 stop/take，而 exit_advisor 仍会用，两边口径可能分叉。
3. `position_sizer.calculate_stop_loss()` ATR 不足时回退固定 -5%，与系统 -8% 冲突；历史数据整体缺失时甚至不写止损字段。
4. `strategy.py` 选股结果止损回退 0.95（-5%），报告文案写死「止损参考：-5%」「止损设MA20或-5%」。

## Flash A/B（quick，verbatim）

先说明：下面两个方案都只改 `auto_heal.py`、`exit_advisor.py`、`position_sizer.py`、`strategy.py` + 新增测试；不动既有 `data/risk_config.json`，不改 `sim.*` 当前数值，不碰 `cost_model` 和正常 ATR/评分/买卖公式。

---

## 方案 A：四处就地直读 `core.config`（最小 diff）

### 关键改动

**auto_heal.py**  
`fix_missing_risk_config()` 重建默认值时，不再写死 `0.30 / 30`：

```diff
 defaults = {
     "stop_loss_pct": core.config.get("sim.stop_loss_pct", -0.08),
-    "take_profit_pct": 0.3,
-    "max_hold_days": 30,
+    "take_profit_pct": core.config.get("sim.take_profit_pct", 0.20),
+    "max_hold_days": core.config.get("sim.max_hold_days", 10),
     "position_size_mult": 1.0,
     # 其余字段保持原样
 }
 recreate_default_json(path, defaults)
```

**exit_advisor.py**  
删除/不再使用硬编码常量 `MAX_HOLD_DAYS = 30`、`TAKE_PROFIT_PCT = 0.30`，`analyze_position()` 的 fallback 改为：

```diff
 if not risk_config:
-    risk_config = {
-        "max_hold_days": MAX_HOLD_DAYS,
-        "take_profit_pct": TAKE_PROFIT_PCT,
-    }
+    risk_config = {
+        "stop_loss_pct": core.config.get("sim.stop_loss_pct", -0.08),
+        "take_profit_pct": core.config.get("sim.take_profit_pct", 0.20),
+        "max_hold_days": core.config.get("sim.max_hold_days", 10),
+    }
```

**position_sizer.py**  
`calculate_stop_loss()` 仅在 ATR 无效/不足时改用系统默认止损：

```diff
 if atr 无效或不足:
-    stop_loss = entry_price * 0.95
-    orders['止损方式'] = '固定-5%'
+    sl_pct = core.config.get("sim.stop_loss_pct", -0.08)
+    stop_loss = entry_price * (1 + sl_pct)
+    orders['止损方式'] = f"固定{sl_pct:.0%}"
```

**strategy.py**  
回退止损和报告文案都动态读取：

```diff
+sl_pct = core.config.get("sim.stop_loss_pct", -0.08)
 ...
-else: stop_loss = price * 0.95
+else: stop_loss = price * (1 + sl_pct)
 ...
-report.append("止损参考：-5% 或跌破 MA20")
-report.append("止损设MA20或-5%")
+report.append(f"止损参考：{sl_pct:.0%} 或跌破 MA20")
+report.append(f"止损设MA20或{sl_pct:.0%}")
```

### 新增测试

`tests/test_risk_default_alignment.py`，全部用 `tmp_path` / `monkeypatch`：

- `fix_missing_risk_config()` 路径指向 `tmp_path`，断言重建文件内是 `-0.08 / +0.20 / 10`。
- `analyze_position()` 不传 `risk_config` 时，断言使用 `core.config.get` 的值，而不是 `30 / 0.30`。
- ATR 无效时调用 `calculate_stop_loss()`，断言止损为 `entry_price * (1 + sl_pct)`，且 `orders['止损方式'] == '固定-8%'`。
- 构造 strategy 报告，断言包含 `-8%`，不包含 `-5%`。

### 优点

- diff 最小，行为变化集中在“默认值、回退、文案”。
- 不引入新模块、新跨模块依赖。
- 保持原函数签名和 `fix_missing_risk_config()` 返回语义。

### 缺点

- 三四个文件里会重复写 `core.config.get("sim.stop_loss_pct", -0.08)` 这类调用。
- 若 `exit_advisor.MAX_HOLD_DAYS / TAKE_PROFIT_PCT` 被外部引用，删除常量可能需要额外兼容处理。

---

## 方案 B：统一 `get_risk_defaults()` 出口

### 关键改动

**exit_advisor.py** 新增统一读取函数，并让 `analyze_position()` 使用：

```python
def get_risk_defaults():
    return {
        "stop_loss_pct": core.config.get("sim.stop_loss_pct", -0.08),
        "take_profit_pct": core.config.get("sim.take_profit_pct", 0.20),
        "max_hold_days": core.config.get("sim.max_hold_days", 10),
    }

def analyze_position(position, risk_config=None):
    risk_config = risk_config or get_risk_defaults()
    ...
```

**auto_heal.py** 复用该函数生成重建默认值：

```python
from exit_advisor import get_risk_defaults

defaults = {
    **get_risk_defaults(),
    "position_size_mult": 1.0,
    # 其余字段保持原样
}
recreate_default_json(path, defaults)
```

**position_sizer.py / strategy.py** 也复用：

```python
sl_pct = get_risk_defaults()["stop_loss_pct"]
```

### 新增测试

同方案 A，另增加一个测试：  
- `get_risk_defaults()` 返回的值等于 `core.config.get(...)`，且没有旧字面量 `30 / 0.30`。

### 优点

- 默认值只有一个出口，后续新增/调整风控默认值不容易漏改。
- 比方案 A 更 DRY，代码重复更少。
- 可以顺手用 `module.__getattr__` 兼容旧的 `MAX_HOLD_DAYS / TAKE_PROFIT_PCT` 外部引用。

### 缺点

- 引入跨模块依赖：`auto_heal.py`、`position_sizer.py`、`strategy.py` 都要依赖 `exit_advisor.py`。
- 如果模块依赖方向没理清，可能引起循环 import；当前改动面会比方案 A 大一点。
- 对“快枪手”式小任务来说，可能略过度设计。

---

## 推荐

**推荐：A**  

理由：A 已经把所有默认值统一到 `core.config`，且改动最小、不碰签名和公式；B 的 helper 在当前四个文件规模下收益有限，反而增加跨模块依赖。


## GPT-5.6 独立方案（Codex CLI，verbatim）

方案 A：最小、直改式统一

- `auto_heal.py`：导入 `core.config.get`，重建时以 `sim.stop_loss_pct/-0.08`、`sim.take_profit_pct/0.20`、`sim.max_hold_days/10` 填默认值；同时保留/补上 `"alert_only": true`，避免重建后意外接管止损止盈。
- `exit_advisor.py`：删除 30 天、+30% 模块常量回退；`load_real_positions()`、`analyze_position()` 的止损止盈回退统一读 `sim.*`。`risk_config` 只允许覆盖 `max_hold_days`。报告中的 -8%/+20%/10 天也改动态，避免残留硬编码。
- `position_sizer.py`：两个固定 -5% 分支合并成一个小的本地赋值逻辑，价格为 `entry * (1 + cfg_get('sim.stop_loss_pct', -0.08))`，文案按真实百分比生成。空历史也应视为 ATR 不足并写入该回退。
- `strategy.py`：ATR 不可用时改用 `sim.stop_loss_pct`；Markdown 风险提示和 100 字摘要均由同一配置动态格式化。
- 测试：四个模块各用 `tmp_path + monkeypatch(cfg_get)` 验证配置值变动会同步影响价格、字段文案和报告；`exit_advisor` 额外验证 `alert_only=true` 时风险文件里的 stop/take 即使冲突也不会覆盖 `sim.*`，但 `max_hold_days` 会生效。

优点：改动小、容易审查、完全符合既有函数签名约束。  
缺点：百分比格式化及“有效规则”的小逻辑会在四个文件中有少量重复。

方案 B：各模块内建立很小的规则解析器

- 在四个文件内部各自定义私有函数，例如 `_sim_risk_rules()`，每次调用都从 `core.config.get` 返回已转换类型的 stop/take/hold；不新增共享模块或配置键。
- `exit_advisor.py` 再定义 `_effective_exit_rules(risk_config)`：stop/take 始终来自 `_sim_risk_rules()`，max-hold 才取 `risk_config.get(..., sim 默认值)`。所有持仓生成、分析和报告都只消费此解析结果。
- `position_sizer.py` 定义 `_apply_fixed_stop(order, entry_price)`，用于历史缺失、长度不足、ATR 无效三条路径，彻底消除 -5% 分支漂移。
- `strategy.py` 定义 `_format_pct()`，选股回退、Markdown 和摘要统一使用，保证 -8%、-7.5% 等都真实展示。
- `auto_heal.py` 的重建默认值由解析器构造，并明确包含 `alert_only: true`。

优点：策略口径集中，后续再调整显示或回退规则时不易重新分叉；测试可直接覆盖解析器与调用点。  
缺点：相比 A 多了若干私有辅助函数，属于略高一点的结构性改动。

推荐：融合。以 B 的 `exit_advisor` 规则解析和 `position_sizer` 固定止损助手消除语义分叉，其余采用 A 的最小改动；这样既不扩范围，也能堵住我核对时发现的两个残留点：`load_real_positions()` 和 `generate_report()` 仍分别写死了止损止盈规则。


## 总指挥仲裁

- 采纳 GPT 融合思路 + Flash 的最小改动主路线，并补上 GPT/Flash 都没覆盖的关键语义：**exit_advisor 必须与 sim_trade.load_risk_config 的 alert_only 语义完全一致**。
- 拒绝「exit_advisor 一律只读 sim.*、risk_config 只允许接管 hold」的简化——那会破坏 strategy_feedback 在 alert_only=false 时调整 stop/take 的既有能力；正确做法是新建 `effective_risk_config()`：alert_only=true → stop/take 强制 sim.*，hold 可由 risk_config 接管；alert_only=false → risk_config 覆盖 stop/take/hold，缺失项回退 sim.*。
- 保留 `exit_advisor.STOP_LOSS_PCT/TAKE_PROFIT_PCT/MAX_HOLD_DAYS` 模块常量（旧测试 monkeypatch 与外部 import 兼容），但默认值改为从 core.config 读取。
- `position_sizer` 采纳「空历史也逐单回退」修正，订单文件始终带止损字段。

## 落地改动

- `auto_heal.py`：导入 cfg_get；重建 risk_config 的 stop/take/hold 读 sim.*，新增 alert_only=True。
- `exit_advisor.py`：常量默认读 sim.*；新增 `_risk_defaults()` / `effective_risk_config()`；analyze_position 与报告、CLI 打印全部走有效规则并动态格式化。
- `position_sizer.py`：新增 `_fixed_stop_pct()/_apply_fixed_stop()`；ATR 缺失/不足/无效与整体无历史四种路径都回退 sim.stop_loss_pct。
- `strategy.py`：新增 `_fallback_stop_loss()`；ATR 缺失回退 -8%；报告风险提示按本金动态显示小资金模式/大资金规则，止损与摘要动态百分比。
- `tests/test_risk_defaults_unify.py`：9 项回归。

## 验证证据

- `python -m pytest -q` → **267 passed, 2 xfailed**
- `python smoke_tests.py` → **48 OK / 0 FAIL**
- `python -m py_compile auto_heal.py exit_advisor.py position_sizer.py strategy.py` → OK
- 生产配置直跑：`effective_risk_config(load_risk_config())` → stop=-0.08 / take=0.20 / hold=10 / alert_only=True；`_fallback_stop_loss(10)` → 9.20

## 风险

1. 本轮只统一 fallback/重建默认值，没有改当前生效的 `data/risk_config.json`；若文件缺失后 auto_heal 重建，stop/take 会因 alert_only=true 固定走 sim.*，反馈循环将不再自动调止损止盈——这是当前用户配置的既有语义，不是新引入。
2. `strategy.py` 的止损参考只是报告提示，真正模拟成交止损来自 position_sizer 订单 → sim_trade；两个链路现已同源，但仍建议下一轮做端到端测试逐字段核对。
3. exit_advisor 保留了模块级常量，外部旧代码若在导入后再 monkeypatch 常量，analyze_position 走 effective_risk_config 时会忽略 monkeypatch（旧测试只断言 hold_days，未受影响；若未来外部依赖常量动态性需再评估）。

## 下一轮候选

- 端到端「订单→sim→exit_advisor」止损/仓位逐字段一致性测试。
- 每笔订单显式成本门槛 gate。
- 数据完整率 / 流水线成功率统计。
