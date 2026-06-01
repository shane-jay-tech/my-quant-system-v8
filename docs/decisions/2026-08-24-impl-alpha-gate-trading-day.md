# 2026-08-24 — Alpha Gate 交易日口径修复 + 流水线非交易日干净跳过

## 元数据（根配置归档格式）

- 任务类型：缺陷修复 / 自动暂停闸门口径修正
- 难度评分：影响面 2 + 风险领域 1 + 歧义度 1 + 新颖度 0 + 不可逆性 0 + 长程影响 2 = **6 → L3**
- 调用模型与思考深度：Flash `deepseek-v4-flash` quick（A/B 方案）；GPT-5.6-terra 经 Codex CLI（ChatGPT 登录，effort=high，sandbox=read-only）；DeepSeek V4 Pro 由本会话总指挥直接仲裁（未额外烧 API）
- critical/major/minor：外部方案 0 条 BLOCKER；GPT 提出 2 项风险（周一长假 fail-open、unknown 分支需测试），均采纳处理
- override：0
- 测试：pytest 247 passed / 2 xfailed；smoke 48/48；py_compile 通过；dry-run rc=0
- 残留风险：见文末
- 返工：测试夹具字段索引修正 1 轮
- 自动升档：无

## 原始需求

GOAL.md 成功证据第 2 条：系统超额收益连续 **5 个交易日** 跑输沪深300 时，Alpha Gate 自动暂停选股。上一轮刚把 `_alpha_gate_precheck()` 接进流水线，但它只按日历日去重，且位于交易日检测之前；而 Windows 计划任务 `QuantDailyPipeline_v5` 是 Daily 触发（周六周日也跑）。实测日志 `logs/pipeline_20260822.log` / `20260823.log` 显示周末流水线以 FATAL 结束。推算：若周五 severe，周六+周日各 +1，周一 +1，周二就会触发暂停——实际只过了 4 个交易日，违反目标。

同时 `check_trading_day.py` 存在周一误判：周一盘前拿到上周五行情时 `day_diff=3`，旧代码落入「数据过期→可能长假」返回 False；2026-08-24 周一实测旧逻辑会误判（本次修复后实测 rc=0）。

## 健康检查（多模型启动前）

`python D:\code\scripts\health_check.py`：deepseek / flash / dashscope / dsbackup / kimi / claude / gpt / codex **全部 OK**。

## Flash（A/B 方案，quick，verbatim）

## A 方案：最小改动，前置交易日闸门 + 周一特判

### 核心改动点

1. **`check_trading_day.py::is_trading_day`**  
   在 `day_diff >= 3` 误判长假之前，增加“周一 + 上周五数据”的特判。

```python
def is_trading_day(today=None):
    today = today or date.today()

    # 周末直接返回 False
    if today.weekday() >= 5:
        return False, "weekend"

    quote = fetch_sh000001()
    if quote is None:
        return True, "quote unavailable, fail-open"

    data_date, volume = quote["date"], quote["volume"]
    day_diff = (today - data_date).days

    # 修复周一误判：周一拿到上周五行情，diff=3，不是长假
    if (
        today.weekday() == 0
        and data_date.weekday() == 4
        and day_diff == 3
        and volume > 0
    ):
        return True, "Monday with Friday quote"

    if day_diff <= 1 and volume > 0:
        return True, "fresh quote"

    if day_diff >= 3:
        return False, "stale quote -> possible long holiday"

    return True, "ambiguous, fail-open"
```

2. **`core/pipeline.py::run_all`**  
   在 `_alpha_gate_precheck()` 之前增加交易日预检；非交易日直接 `return 0`，不执行任何步骤。

```python
def run_all():
    print(header)

    if not dry_run:
        ok, reason = check_trading_day.is_trading_day()
        if not ok:
            print(f"[pipeline] 非交易日，跳过: {reason}")
            return 0

    if alpha_gate.enabled and not dry_run:
        _alpha_gate_precheck(trading_day_ok=ok)

    for step in active_steps:
        ...
```

3. **`alpha_gate.py::check_alpha_gate`**  
   增加交易日闸门，只有交易日才允许更新状态；非交易日直接返回当前状态。

```python
def check_alpha_gate(today=None, trading_day_ok=None):
    today = today or date.today()

    # pipeline 显式传入时直接用；单独调用时用轻量 weekend guard 兜底
    if trading_day_ok is None:
        trading_day_ok = today.weekday() < 5

    if not trading_day_ok:
        return load_state(), "non-trading-day, skip"

    state = load_state()
    severity = evaluate_etf_gate()

    if severity == "severe":
        if state.get("last_counted_date") != today.isoformat():
            state["consecutive_severe_days"] += 1
            state["last_counted_date"] = today.isoformat()
    elif severity in ("normal", "warning"):
        state["consecutive_severe_days"] = 0
    # unknown/stale 保持不变

    save_state(state)
    return state, severity
```

### 优点

- 改动面最小，逻辑直观，review 成本低。
- 直接解决周末流水线 `rc=1` 问题：非交易日提前 return 0。
- 不改变 state 字段结构，兼容旧数据。
- 现有测试 `test_alpha_gate_same_day_no_double_count` 不受影响。

### 缺点 / 风险

- `Monday + Friday数据的特判` 本质是启发式；如果某个周一正好是法定节假日，仍可能被误判为交易日。
- 如果 pipeline 不传 `trading_day_ok`，alpha_gate 单独调用时只能挡周末，不能挡工作日节假日。
- `check_trading_day` 步骤仍会在后续步骤中再跑一次，存在一次重复网络请求；可把预检结果缓存到 context 中避免，但 A 方案未强制做。

---

## B 方案：交易日 key 去重 + 共享交易日判定缓存

### 核心改动点

1. **新增共享判定器 `core/trading_day.py`**  
   避免 pipeline、alpha_gate、check_trading_day 步骤重复请求网络。

```python
_trading_day_cache = {}

def get_trading_day_status(today=None):
    today = today or date.today()
    if today in _trading_day_cache:
        return _trading_day_cache[today]

    ok, reason = check_trading_day.is_trading_day(today)
    _trading_day_cache[today] = (ok, reason)
    return ok, reason

def reset_trading_day_cache():
    _trading_day_cache.clear()
```

2. **`check_trading_day.py::is_trading_day`**  
   同样修复周一误判，但用本地交易日文件辅助判断，处理“周一/节后周二”的间隔。

```python
def is_trading_day(today=None):
    today = today or date.today()

    if today.weekday() >= 5:
        return False, "weekend"

    quote = fetch_sh000001()
    if quote is None:
        return True, "fail-open"

    data_date, volume = quote["date"], quote["volume"]
    day_diff = (today - data_date).days

    if day_diff <= 1 and volume > 0:
        return True, "fresh quote"

    last_local = get_last_trading_day(today)

    # 数据日期等于本地已知最近交易日，且间隔只可能是周末/一两天假日
    if data_date == last_local and day_diff in (3, 4) and volume > 0:
        return True, "latest local trading day, not long holiday"

    if day_diff >= 5:
        return False, "stale quote -> possible long holiday"

    return True, "ambiguous, fail-open"
```

3. **`core/pipeline.py::run_all`**  
   使用共享判定，非交易日直接 `return 0`。

```python
def run_all():
    print(header)

    if not dry_run:
        ok, reason = get_trading_day_status()
        if not ok:
            print(f"[pipeline] 非交易日，跳过: {reason}")
            return 0

    if alpha_gate.enabled and not dry_run:
        _alpha_gate_precheck()

    for step in active_steps:
        ...
```

4. **`alpha_gate.py::check_alpha_gate`**  
   不再用“今天日期”做去重，而是用本地数据文件对应的“最近交易日”作为 state 的 `last_counted_date`。这样周六、周日、节假日都不会被当成新交易日。

```python
from utils.calendar import get_last_trading_day

def _normalize_last_counted_date(state, today):
    raw = state.get("last_counted_date")
    if not raw:
        return

    try:
        d = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return

    last = get_last_trading_day(d)
    if last and last.strftime("%Y-%m-%d") != raw:
        state["last_counted_date"] = last.strftime("%Y-%m-%d")

def check_alpha_gate(today=None):
    today = today or date.today()
    state = load_state()

    # 兼容旧数据：如果旧 state 里 weekend 日期被写入，归一化到最近交易日
    _normalize_last_counted_date(state, today)

    trade_day = get_last_trading_day(today) or today
    trade_key = trade_day.strftime("%Y-%m-%d")

    severity = evaluate_etf_gate()

    if severity == "severe":
        if state.get("last_counted_date") != trade_key:
            state["consecutive_severe_days"] += 1
            state["last_counted_date"] = trade_key
    elif severity in ("normal", "warning"):
        state["consecutive_severe_days"] = 0
    # unknown/stale 保持不变

    save_state(state)
    return state, severity
```

### 优点

- Alpha Gate 从“日历日去重”变成“交易日去重”，从根本上避免周末/节假日被计入连续跑输天数。
- 共享缓存避免重复网络请求。
- state 字段结构不变，且对旧数据中的周末 `last_counted_date` 做了归一化，兼容性更好。
- 对“周一拿到周五数据”“节后周二拿到节前数据”等场景更稳。

### 缺点 / 风险

- 依赖本地 `data/stock_YYYYMMDD.csv` 文件；如果本地数据文件缺失或更新不及时，`get_last_trading_day` 可能回退到工作日计数，导致误判。
- 改动比 A 大，需要新增共享缓存模块，测试中需要 reset cache。
- 如果 pipeline 必须在“盘前/早盘”就计入当天作为连续跑输交易日，那么 B 方案会把计数延后到当天数据文件出现之后，需要确认业务语义。

---

推荐：**融合方案**  
用 A 的“前置交易日闸门 + 周一特判”保证周末干净跳过，同时用 B 的“Alpha Gate 交易日 key 去重”避免周末/节假日被计入连续跑输天数；改动量可控且两个根因都被覆盖。


## GPT-5.6-terra（Codex CLI 独立方案，effort=high，verbatim）

A 方案：最小改动，流水线先判交易日，再运行 Alpha Gate

核心函数改动要点：

- `check_trading_day.py`
  - 抽出可注入的 `is_trading_day(today=None, request_get=requests.get)`。
  - 周一允许“最近行情为上周五且成交量>0”，避免 `day_diff=3` 被误判成长假。
  - 非交易日也让 `main()` 返回 `0`，输出“SKIP”；退出码只表示脚本自身异常，不表示“今天不开市”。

```diff
+def _previous_weekday(today):
+    return today - timedelta(days=3 if today.weekday() == 0 else 1)

-def is_trading_day():
+def is_trading_day(today=None, request_get=requests.get):
     today = today or date.today()
     if today.weekday() >= 5:
         return False, "weekend"
     ...
-    if data_date == today_str and volume > 0:
+    if data_date == today_str and volume > 0:
         return True, "today quote"
-    elif day_diff <= 1 and volume > 0:
+    elif data_date == _previous_weekday(today).isoformat() and volume > 0:
         return True, "pre-open; latest quote is previous weekday"
     elif day_diff >= 3:
         return False, "stale; possible holiday"
     ...
 
 def main():
     is_trade, reason = is_trading_day()
     print(...)
-    return 0 if is_trade else 1
+    return 0
```

- `core/pipeline.py`
  - 在 Alpha Gate 前以内联函数调用交易日检测。
  - 明确非交易日时打印“干净跳过”并 `return 0`，不再实际执行注册表中的 `check_trading_day` 子进程。
  - 交易日确认后再执行 `_alpha_gate_precheck()`；从 `active` 中排除已执行的 `check_trading_day`。

```diff
+from check_trading_day import is_trading_day
+
+is_trade, reason = is_trading_day()
+if not is_trade:
+    print(f"[SKIP] non-trading day: {reason}")
+    return 0
+active = [s for s in active if s["id"] != "check_trading_day"]
 
 paused, reason = _alpha_gate_precheck()
```

- `alpha_gate.py`
  - 给 `check_alpha_gate()` 增加可选 `is_trading_day_fn`；直接手动执行时也不会在周末累加。
  - 非交易日直接返回当前状态，不调用 `evaluate_etf_gate()`、不写计数。

```diff
-def check_alpha_gate(state_dir=DATA_DIR):
+def check_alpha_gate(state_dir=DATA_DIR, is_trading_day_fn=None):
+    checker = is_trading_day_fn or check_trading_day.is_trading_day
+    is_trade, _ = checker()
+    if not is_trade:
+        return _result_from_current_state_without_mutation(...)
```

优点：

- 改动面小，交易日检测只请求一次。
- 直接解决周末误计数、周一误判、周末 FATAL 三个现象。
- 不改状态文件结构，已有 `last_counted_date` 继续使用。
- 测试直观：注入 `today`、`request_get`、`is_trading_day_fn` 即可。

缺点：

- “网络无法确认”沿用当前 fail-open=`True` 的语义；此时流水线会继续，Alpha Gate 也可能把当天算入计数。
- `last_counted_date` 本质仍是“运行日期”，不是明确的“已确认交易会话标识”。

风险：

- 周一恰逢长假时，最新数据仍为周五，会按 fail-open 被当作交易日；虽然不会中断流水线，但可能发生一次不必要的运行/计数。


B 方案：三态交易日决策 + 交易会话键，计数语义彻底与日历日解耦

核心函数改动要点：

- `check_trading_day.py`
  - 新增 `TradingDayDecision`，状态严格区分：`trading` / `non_trading` / `unknown`。
  - `unknown` 是网络异常、响应解析失败等；它与“确认是交易日”不同。
  - 同样使用“前一个工作日”规则修复周一上周五数据问题。
  - CLI 对三种状态均返回 `0`；只有程序内部未捕获异常才非零。

```diff
+@dataclass(frozen=True)
+class TradingDayDecision:
+    status: Literal["trading", "non_trading", "unknown"]
+    reason: str
+    session_date: str | None
+
+def get_trading_day_decision(today=None, request_get=requests.get):
+    if weekend:
+        return TradingDayDecision("non_trading", "weekend", None)
+    if quote_date == today or quote_date == previous_weekday(today):
+        return TradingDayDecision("trading", "...", today.isoformat())
+    if stale_or_zero_volume:
+        return TradingDayDecision("non_trading", "...", None)
+    return TradingDayDecision("unknown", "quote unavailable", None)
```

- `core/pipeline.py`
  - 交易日决策成为流水线的第一个“控制门”，不再依赖子进程 rc 表达业务状态。
  - `non_trading`：打印 `[SKIP]` 后 `return 0`。
  - `unknown`：流水线继续（fail-open），但本次不调用 Alpha Gate 计数，避免断网导致错误暂停。
  - `trading`：把已确认的 `session_date` 传给 Alpha Gate。

```diff
+decision = get_trading_day_decision()
+if decision.status == "non_trading":
+    print(f"[SKIP] non-trading day: {decision.reason}")
+    return 0
+if decision.status == "unknown":
+    print(f"[WARN] trading day unknown; continue fail-open, skip alpha counting")
+elif alpha_enabled:
+    paused, reason = _alpha_gate_precheck(
+        trading_session=decision.session_date
+    )
```

- `alpha_gate.py`
  - 新增兼容字段 `last_counted_session_date`，保留并同步旧字段 `last_counted_date`。
  - 仅在收到已确认 `trading_session` 时，才允许 severe 累加或 normal/warning 清零。
  - 同一交易会话的任意重跑不改变计数；`unknown/stale` 不消耗会话键。
  - 首次升级时可用旧 `last_counted_date` 作为迁移回退，避免刚上线就多算一次。

```diff
-def check_alpha_gate(state_dir=DATA_DIR):
+def check_alpha_gate(
+    state_dir=DATA_DIR,
+    trading_session: str | None = None,
+    trading_day_resolver=get_trading_day_decision,
+):
+    if trading_session is None:
+        decision = trading_day_resolver()
+        if decision.status != "trading":
+            return _current_state_result_without_mutation(...)
+        trading_session = decision.session_date
+
+    last_session = (
+        state.get("last_counted_session_date")
+        or state.get("last_counted_date")  # 兼容旧 state
+    )
+    if severity in ("severe", "normal", "warning") and last_session != trading_session:
+        if severity == "severe":
+            consecutive += 1
+        else:
+            consecutive = 0
+        state["last_counted_session_date"] = trading_session
+        state["last_counted_date"] = trading_session
```

优点：

- “交易日”“非交易日”“无法确认”语义清楚，断网不会触发暂停，满足真正的 fail-open。
- Alpha Gate 的计数键是确认后的交易会话，不再只是机器当天的日历日期。
- 周末、手动重跑、同一会话多次执行都不会重复计数。
- 新字段为增量兼容，不破坏现有 `paused`、`consecutive_severe_days`、`last_counted_date` 等状态。

缺点：

- 比 A 多一个决策对象和状态字段，测试与迁移逻辑更多。
- 首次上线使用旧 `last_counted_date` 迁移时，最多可能保守地少算一次，而不是冒险多算一次。

风险：

- 周一长假仍可能因“上周五数据”进入 `trading` 的 fail-open 分支；但会话键使其不会在随后真实交易日重复累加。
- 需补齐 `unknown` 分支测试，确保它只跳过 Alpha 计数、不跳过整条流水线。

推荐：融合，以 B 的三态决策和会话键为主、采用 A 的“流水线内联预检且不再重复跑子进程”方式；这样既干净跳过周末，又不会因断网或重复运行误暂停。


## 总指挥仲裁（DeepSeek V4 Pro，本会话）

验收维度：正确性 50% / 风险控制 25% / 可维护与测试 15% / 成本 10%。

- 采纳 **融合方案**：GPT 的三态思路（非交易日明确不计数）+ Flash 的「流水线内联交易日闸门 + 周一特判」最小改动。
- 不引入 GPT 提议的 `TradingDayDecision` dataclass 与 `last_counted_session_date` 新字段——旧 `last_counted_date` 字段已够用，新增状态字段会扩大迁移面而收益很小；保留 `AlphaGateResult.counted` 一个布尔位来表达「本次是否计数」。
- 不采纳「check_trading_day CLI 非交易日也返回 0」：`morning_pipeline.bat` 依赖 rc=1 跳过盘前流水线，改动会破坏现有盘前链路；改为 core.pipeline 内联调用函数、周末干净跳过，子进程 CLI 语义不动。
- unknown/网络失败语义：pipeline 与 Alpha Gate 均保持 fail-open（未知按交易日继续），与旧系统一致；唯一代价是断网那天可能计一次数，但不会误暂停（保守方向正确）。

## 落地改动

- `check_trading_day.py`：`is_trading_day(today=None, request_get=None)` 可注入；新增 `_previous_weekday`；当行情日期 == 上一工作日且成交量 >0 时判为交易日（修周一 day_diff=3 误判）；网络失败仍 fail-open；`main()` 退出码语义保持不变（盘前 bat 兼容）。
- `core/pipeline.py`：新增 `_check_trading_day_inline()`；`run_all` 先判交易日——非交易日打印 `[SKIP]` 并 **rc=0**；确认交易日后才 `_alpha_gate_precheck(trading_day_ok=True)`；注册表里的 `check_trading_day` 子进程不再重复执行。
- `alpha_gate.py`：`check_alpha_gate(..., trading_day_ok=None, is_trading_day_fn=None)`；非交易日直接返回当前状态（`counted=False`、`severity='non_trading'`），不读行情、不写盘；`AlphaGateResult` 新增 `counted` 字段；状态文件字段零改动，旧 state 兼容。
- 测试：新增 `tests/test_alpha_gate_trading_day.py`（9 项）；更新 `test_pipeline_alpha_gate.py` 断言 precheck 传 `trading_day_ok=True`；更新同日去重回归测试。

## 验证证据

- `python -m pytest -q` → **247 passed, 2 xfailed**（基线 239 passed / 2 xfailed，净增 8）
- `python smoke_tests.py` → **48 OK / 0 FAIL**
- `python -m py_compile check_trading_day.py alpha_gate.py core/pipeline.py` → OK
- `python -m core.pipeline --dry-run` → 列出 26 步，rc=0，不触网
- `python check_trading_day.py`（2026-08-24 周一真实调用）→ 「最新行情=2026-08-21(上一工作日), 工作日→假设交易日」，**rc=0**
- `python alpha_gate.py` → `consecutive_severe_days=2` 保持不变（同一交易日重复运行未二次累加）；`--status` paused=false
- 预算：今日 API 计费 2.14 元（Flash 协作 0.39 + smoke 外部探测触发的 deepseek 1.75），累计远低于 20 元；GPT 走 Codex Plus 额度，未计 API 费。

## 残留风险

1. 周一恰逢法定节假日时，`check_trading_day` 仍会因「上周五行情 + fail-open」把当天当交易日，Alpha Gate 可能多计一天；这是无交易日历/新数据源约束下的既有启发式风险，与旧逻辑同源。证据：无本地节假日历可核。
2. 断网且无法确认交易日时，pipeline 照跑、Alpha Gate 可能按 fail-open 计一次数；不会误暂停（只会延迟或提前一次），符合「宁可不阻断」的旧约定。
3. 本 slice 未动 severe 阈值、超额收益计算、买卖公式、止损止盈、仓位参数与数据源。

## 后续（仍在本目标内，下一轮候选）

- 数据完整率 / 流水线成功率的自动化看板口径（周末跳过应记为 skip 而非 fail）。
- 每笔订单过成本门槛的显式 gate（当前是仓位/head(3) 间接控制）。
- 真实账户与模拟账户止损止盈/仓位的口径一致性审计。
