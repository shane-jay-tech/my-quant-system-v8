# 2026-08-24 — 自检 K 线新鲜度改交易日口径 + 弱信号证据审查（Round 5）

## 第一部分：自检修复（L1-L2）

- 难度评分：影响面 1 + 风险领域 0 + 歧义度 0 + 新颖度 0 + 不可逆性 0 + 长程影响 1 = **2 → L2 下沿（Flash 出方案 + Pro 评审）**
- 模型：Flash quick；Pro 本会话评审；health_check 8 通道全 OK。
- 原始问题：周一 2026-08-24 运行 `_self_check.py`，history 最新日期是上周五 2026-08-21，日历差 3 天 > 2 → 「Data: K-line freshness」误报 FAIL（修复前 141/142）。改成交易日落后数（优先 `utils.calendar.count_trading_days`，失败回退日历天数）。
- 改动：`_self_check.py` 新增 `_trading_days_behind(latest, today=None, data_dir=DATA_DIR)`；K-line freshness 详情改为 `X trading day(s) behind`。
- Flash 方案 verbatim：

## 修改 `_self_check.py`

```diff
--- a/_self_check.py
+++ b/_self_check.py
@@
+def _trading_days_behind(latest, today=None, data_dir=None):
+    """返回 latest 落后 today 的交易日数；latest 当天则为 0。"""
+    if today is None:
+        today = datetime.now()
+    try:
+        from utils.calendar import count_trading_days
+        # count_trading_days 包含 latest/today 两端，所以减 1
+        behind = count_trading_days(latest, today, data_dir=data_dir) - 1
+        return max(behind, 0)
+    except Exception:
+        # 回退到日历天数
+        return max((pd.Timestamp(today) - pd.Timestamp(latest)).days, 0)
+
+
 def _check_data_freshness(...):
     hist['日期'] = pd.to_datetime(hist['日期'])
-    days_behind = (datetime.now() - hist['日期'].max()).days
-    check('Data: K-line freshness', 'data', days_behind <= 2, f'{...}, {days_behind}d behind')
+    latest = hist['日期'].max()
+    days_behind = _trading_days_behind(latest, data_dir=data_dir)
+    check('Data: K-line freshness', 'data', days_behind <= 2,
+          f'{latest.date()}, {days_behind} trading days behind')
```

说明：`data_dir=data_dir` 按原函数中已有变量名使用；如果原代码是 `self.data_dir` 或 `DATA_DIR`，替换成对应变量名即可。

## 测试要点

测试直接覆盖私有 helper，使用 `monkeypatch` 和 `tmp_path`，不碰生产数据目录。

```python
from datetime import date, datetime
import utils.calendar as calendar
import _self_check


def test_friday_to_monday_is_one_trading_day_behind(monkeypatch):
    monkeypatch.setattr(
        calendar,
        "count_trading_days",
        lambda latest, today, data_dir=None: 2,
    )

    assert _self_check._trading_days_behind(
        date(2026, 8, 21), today=date(2026, 8, 24)
    ) == 1


def test_same_day_is_zero_behind(monkeypatch):
    monkeypatch.setattr(
        calendar,
        "count_trading_days",
        lambda latest, today, data_dir=None: 1,
    )

    assert _self_check._trading_days_behind(
        date(2026, 8, 24), today=date(2026, 8, 24)
    ) == 0


def test_fallback_to_calendar_days_on_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(calendar, "count_trading_days", boom)

    assert _self_check._trading_days_behind(
        date(2026, 8, 21), today=datetime(2026, 8, 24, 15, 0)
    ) == 3


def test_data_dir_is_forwarded(tmp_path, monkeypatch):
    captured = {}

    def fake_count(latest, today, data_dir=None):
        captured["data_dir"] = data_dir
        return 2

    monkeypatch.setattr(calendar, "count_trading_days", fake_count)

    assert _self_check._trading_days_behind(
        date(2026, 8, 21), today=date(2026, 8, 24), data_dir=str(tmp_path)
    ) == 1
    assert captured["data_dir"] == str(tmp_path)
```

现有 smoke 目标 `_self_check` 仍应全 PASS；不修改 `data_validator.py`，不新增依赖。


- 总指挥修正：Flash 的 fallback 用 `pd.Timestamp`，但模块顶层没有 pandas；改为纯 datetime/date 解析，并修复 `datetime` 是 `date` 子类导致的减法 TypeError。
- 测试：新增 `tests/test_selfcheck_trading_day.py` 5 项。
- 证据：`python _self_check.py` → **142/142 PASS**，K-line freshness 详情 `2026-08-21, 0 trading day(s) behind`（修复前 FAIL）。

## 第二部分：弱信号不买 — 证据审查（暂不落地）

目标要求「弱信号不买」。本轮用已有数据检验“评分/共识门槛”是否可落地：

- 数据 1：`results/pick_*.md` 解析 340 个个股评分，join `data/history.csv` 得到 320 个 1/3/5 日前向收益。按评分分桶：80-90 分 n=9 ret1 +0.31%；90-93 n=80 +1.13%；93-96 n=113 -0.22%；96+ n=118 +0.24% —— **非单调，无可用门槛**。
- 数据 2：`orders/multi_vote_*.json` 解析 320 条最终得分与前向收益。最终得分最低五分位（<64.3）n=80 ret1 -0.40%、胜率 36%；最高五分位（>92.9）n=48 ret1 +0.51%、胜率 58%；中间三档来回跳动。而且 320 条里 319 条共识度是 1/3，**共识门槛会直接清空 99.7% 的订单**。
- 结论：现有证据不足以给「弱信号」定一个有信心的阈值；按「无证据不落地」原则，**本轮不新增 min_score/min_consensus 门槛代码**。继续靠已落地的 Alpha Gate（连续跑输改 ETF）、强熊空仓、每笔成本门槛保护。
- 什么证据能改变结论：把每个选股日的 `综合评分/final_score/共识度/入选理由` 与 1/3/5 日前向收益结构化落表，积累 ≥60 个交易日（≥1800 个样本）后重新做分桶与置信区间；若某阈值下低分组净收益（扣 5 元最低佣金后的真实成本）显著为负且高分组显著更优，再实现 gate。
- 本轮数据快照：分数分桶与 quintile 表见 memory 尾部与 `docs/decisions/2026-08-24-review-weak-signal-evidence.md`。

## 验证汇总

- `python -m pytest -q` → **282 passed, 2 xfailed**（基线 277，净增 5）
- `python smoke_tests.py` → **48 OK / 0 FAIL**
- `python -m py_compile _self_check.py` → OK
- API：本轮 Flash 0.3129 元；今日累计 6.49 元 < 20 元。

## 风险

1. 交易日落后数依赖本地 `stock_*.csv` 文件名；归档清掉旧文件时仍按 utils.calendar 的 weekday fallback 兜底，但长假尾段可能轻微偏差。
2. 弱信号不买暂未落地，是目标中的已知未完成项；不能靠本轮证据硬上阈值。
