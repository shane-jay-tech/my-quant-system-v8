# 2026-08-24 — 目标验收三指标（流水线成功率/数据完整率/自检通过率，Round 6）

## 元数据

- 任务类型：新增本地指标报告 + 流水线注册表步骤
- 难度评分：影响面 1 + 风险领域 0 + 歧义度 1 + 新颖度 1 + 不可逆性 0 + 长程影响 1 = **4 → L2**
- 调用模型：Flash `deepseek-v4-flash` quick 出方案；DeepSeek V4 Pro 本会话评审；health_check 8 通道全 OK。
- override：0
- 测试：pytest **294 passed / 2 xfailed**（基线 282，净增 12）；smoke 48/48；py_compile 通过
- API：本轮 Flash 0.3992 元；今日累计 6.89 元 < 20 元

## 原始需求

GOAL 验收要求「同时看净收益、胜率、最大回撤、超额、摩擦成本，以及数据完整率、流水线成功率与测试通过率」。前三项已有 benchmark/sim 报告，后三项此前没有每日快照。新增 `goal_metrics.py` 从本地日志/报告计算三项并落盘 `reports/goal_metrics_YYYYMMDD.md/json`，注册进 daily pipeline（beginner 档，self_check 之前）。

## Flash 方案（quick，verbatim）

## 实现方案

新增 `goal_metrics.py`，只做本地文件读取、指标计算、报告生成；不改任何交易/风控逻辑。  
`core/pipeline.py` 只增加一条 PIPELINE_STEPS 注册项。

---

## `goal_metrics.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目标验收三指标：
1. 流水线成功率
2. 数据完整率
3. 测试/自检通过率
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
LOGS_DIR = ROOT / "logs"
REPORTS_DIR = ROOT / "reports"
TODAY = datetime.now().strftime("%Y%m%d")

RECENT_LOG_LIMIT = 20
DEFAULT_MIN_STOCK_ROWS = 4000
MAX_HISTORY_LAG_DAYS = 5

# 数据完整率档位阈值（可配置）
COMPLETENESS_OK_THRESHOLD = 95.0
COMPLETENESS_DEGRADED_THRESHOLD = 80.0

DATE_RE = re.compile(r"(\d{8})")
KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*([^\s|]+)")


def _extract_date(name: str) -> Optional[str]:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        raw = str(value).strip().replace(",", "")
        if raw.lower() in {"", "none", "null", "n/a", "-"}:
            return None
        is_pct = raw.endswith("%")
        f = float(raw.rstrip("%")) if is_pct else float(raw)
        return f / 100.0 if is_pct else f
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    return int(round(f)) if f is not None else None


def _as_ratio(value: Any) -> Optional[float]:
    """兼容 0.95 / 95 / 95% 三种写法。"""
    f = _as_float(value)
    if f is None:
        return None
    return f / 100.0 if f > 1 else f


def _parse_kv_line(line: str) -> Dict[str, str]:
    return {k: v for k, v in KEY_VALUE_RE.findall(line)}


def _find_line(lines: List[str], keyword: str) -> Optional[str]:
    for line in lines:
        if keyword.lower() in line.lower():
            return line
    return None


def _fmt_rate(v: Optional[float]) -> str:
    return "N/A" if v is None else f"{v}%"


def _fmt_bool(v: Optional[bool]) -> str:
    return "N/A" if v is None else ("是" if v else "否")


def _fmt(v: Any) -> str:
    return "N/A" if v is None else str(v)


# ---------------------------------------------------------------- 指标 1
def _classify_log(text: str, date_str: str, today: str) -> str:
    if "[SKIP] 非交易日" in text:
        return "skipped"
    # 先看 FATAL，再看成功标记
    if "[FATAL]" in text:
        return "failed"
    if "[ALPHA-GATE] PAUSED" in text or "Pipeline complete" in text:
        return "success"
    # 有日期但今天仍无终态 = in_progress；更早无终态 = failed
    return "in_progress" if date_str == today else "failed"


def compute_pipeline_metrics(
    logs_dir: Optional[Path] = None,
    today: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    logs_dir = Path(logs_dir) if logs_dir is not None else LOGS_DIR
    today = today or TODAY
    limit = limit if limit is not None else RECENT_LOG_LIMIT

    result: Dict[str, Any] = {
        "name": "流水线成功率",
        "status": "UNKNOWN",
        "attempts": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "in_progress": 0,
        "success_rate": None,
        "raw_evidence": [],
        "error": None,
    }

    if not logs_dir.is_dir():
        result["error"] = "logs 目录不存在"
        return result

    logs = [
        p for p in logs_dir.glob("pipeline_*.log")
        if _extract_date(p.name)
    ]
    if not logs:
        result["error"] = "未找到带日期的 pipeline_*.log"
        return result

    logs = sorted(logs, key=lambda p: _extract_date(p.name) or "", reverse=True)[:limit]

    unreadable = 0
    for path in logs:
        date_str = _extract_date(path.name) or ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            unreadable += 1
            result["raw_evidence"].append(f"{path.name}: UNKNOWN (读取失败)")
            continue

        state = _classify_log(text, date_str, today)
        if state == "success":
            result["success"] += 1
        elif state == "failed":
            result["failed"] += 1
        elif state == "skipped":
            result["skipped"] += 1
        elif state == "in_progress":
            result["in_progress"] += 1
        result["raw_evidence"].append(f"{path.name}: {state} ({date_str})")

    attempts = result["success"] + result["failed"]
    result["attempts"] = attempts

    if attempts > 0 and unreadable == 0:
        result["success_rate"] = round(100.0 * result["success"] / attempts, 2)
        result["status"] = "OK"
    else:
        result["success_rate"] = None
        result["status"] = "UNKNOWN"

    if unreadable:
        result["error"] = (result["error"] + "; " if result["error"] else "") + f"{unreadable} 个日志读取失败"

    return result


# ---------------------------------------------------------------- 指标 2
def _get_min_stock_rows() -> int:
    for module_name in ("core.data_validator", "core.data_validation"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for attr in ("min_stock_rows", "MIN_STOCK_ROWS"):
            value = getattr(module, attr, None)
            if value is None:
                continue
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
    return DEFAULT_MIN_STOCK_ROWS


def _latest_data_health_file(reports_dir: Path) -> Optional[Path]:
    if not reports_dir.is_dir():
        return None
    files = [
        p for p in reports_dir.glob("data_health_*.md")
        if _extract_date(p.name)
    ]
    return max(files, key=lambda p: _extract_date(p.name) or "") if files else None


def compute_data_completeness(reports_dir: Optional[Path] = None) -> Dict[str, Any]:
    reports_dir = Path(reports_dir) if reports_dir is not None else REPORTS_DIR

    result: Dict[str, Any] = {
        "name": "数据完整率",
        "status": "UNKNOWN",
        "source": None,
        "rows": None,
        "nonzero_price_ratio": None,
        "nonempty_volume_ratio": None,
        "latest_date": None,
        "lag_days": None,
        "multi_vote_count": None,
        "completeness_pct": None,
        "rows_ok": None,
        "lag_days_ok": None,
        "raw_evidence": [],
        "error": None,
    }

    path = _latest_data_health_file(reports_dir)
    if path is None:
        result["error"] = "未找到 data_health_*.md"
        return result

    result["source"] = path.name
    result["raw_evidence"].append(f"数据源: {path.name}")

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        result["error"] = f"读取失败: {exc}"
        return result

    stock_line = _find_line(lines, "stock_csv")
    history_line = _find_line(lines, "history")
    vote_line = _find_line(lines, "multi_vote")

    if stock_line:
        result["raw_evidence"].append(stock_line.strip())
    if history_line:
        result["raw_evidence"].append(history_line.strip())
    if vote_line:
        result["raw_evidence"].append(vote_line.strip())

    stock_kv = _parse_kv_line(stock_line) if stock_line else {}
    history_kv = _parse_kv_line(history_line) if history_line else {}
    vote_kv = _parse_kv_line(vote_line) if vote_line else {}

    rows = _as_int(stock_kv.get("rows"))
    nonzero_price_ratio = _as_ratio(stock_kv.get("nonzero_price_ratio"))
    nonempty_volume_ratio = _as_ratio(stock_kv.get("nonempty_volume_ratio"))
    latest_date = history_kv.get("latest_date")
    lag_days = _as_int(history_kv.get("lag_days"))
    multi_vote_count = _as_int(vote_kv.get("count"))

    result.update(
        rows=rows,
        nonzero_price_ratio=nonzero_price_ratio,
        nonempty_volume_ratio=nonempty_volume_ratio,
        latest_date=latest_date,
        lag_days=lag_days,
        multi_vote_count=multi_vote_count,
    )

    if nonzero_price_ratio is not None and nonempty_volume_ratio is not None:
        result["completeness_pct"] = round(
            100.0 * (nonzero_price_ratio * 0.6 + nonempty_volume_ratio * 0.4),
            2,
        )

    min_rows = _get_min_stock_rows()
    if rows is not None:
        result["rows_ok"] = rows >= min_rows
    if lag_days is not None:
        result["lag_days_ok"] = lag_days <= MAX_HISTORY_LAG_DAYS

    completeness_pct = result["completeness_pct"]
    if completeness_pct is None or rows is None or lag_days is None:
        result["status"] = "UNKNOWN"
    elif (
        rows < min_rows
        or lag_days > MAX_HISTORY_LAG_DAYS
        or completeness_pct < COMPLETENESS_DEGRADED_THRESHOLD
    ):
        result["status"] = "FAIL"
    elif completeness_pct < COMPLETENESS_OK_THRESHOLD:
        result["status"] = "DEGRADED"
    else:
        result["status"] = "OK"

    return result


# ---------------------------------------------------------------- 指标 3
def compute_self_check(reports_dir: Optional[Path] = None) -> Dict[str, Any]:
    reports_dir = Path(reports_dir) if reports_dir is not None else REPORTS_DIR
    path = reports_dir / "system_self_check_v86.json"

    result: Dict[str, Any] = {
        "name": "测试/自检通过率",
        "status": "UNKNOWN",
        "source": path.name,
        "passed": None,
        "total": None,
        "self_check_pass_rate": None,
        "raw_evidence": [],
        "error": None,
    }

    if not path.exists():
        result["error"] = "system_self_check_v86.json 不存在"
        return result

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["error"] = f"JSON 解析失败: {exc}"
        return result

    if not isinstance(data, dict):
        result["error"] = "JSON 顶层不是对象"
        return result

    score = data.get("score", {})
    if not isinstance(score, dict):
        score = {}

    passed = score.get("passed")
    total = score.get("total")
    if passed is None:
        passed = data.get("passed")
    if total is None:
        total = data.get("total")

    try:
        passed_f = float(passed)
        total_f = float(total)
    except (TypeError, ValueError):
        result["error"] = "score.passed / score.total 无法解析"
        return result

    if total_f <= 0:
        result["error"] = "score.total <= 0"
        return result

    result.update(
        passed=passed_f,
        total=total_f,
        self_check_pass_rate=round(100.0 * passed_f / total_f, 2),
        status="OK",
    )
    result["raw_evidence"].append(f"score.passed={passed_f}, score.total={total_f}")
    return result


# ---------------------------------------------------------------- 报告
def _build_conclusion(metrics: Dict[str, Any]) -> str:
    p = metrics["pipeline_success_rate"]
    d = metrics["data_completeness"]
    s = metrics["self_check_pass_rate"]
    return (
        "当日快照："
        f"流水线成功率 {_fmt_rate(p.get('success_rate'))}；"
        f"数据完整率 {_fmt_rate(d.get('completeness_pct'))}（{d.get('status', 'UNKNOWN')}）；"
        f"自检通过率 {_fmt_rate(s.get('self_check_pass_rate'))}。"
    )


def build_report(
    date_str: Optional[str] = None,
    logs_dir: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    date_str = date_str or TODAY
    logs_dir = Path(logs_dir) if logs_dir is not None else LOGS_DIR
    reports_dir = Path(reports_dir) if reports_dir is not None else REPORTS_DIR

    pipeline = compute_pipeline_metrics(logs_dir, date_str)
    data = compute_data_completeness(reports_dir)
    self_check = compute_self_check(reports_dir)

    metrics = {
        "pipeline_success_rate": pipeline,
        "data_completeness": data,
        "self_check_pass_rate": self_check,
    }

    return {
        "date": date_str,
        "metrics": metrics,
        "conclusion": _build_conclusion(metrics),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    date_str = report.get("date", TODAY)
    m = report["metrics"]
    p = m["pipeline_success_rate"]
    d = m["data_completeness"]
    s = m["self_check_pass_rate"]

    lines: List[str] = []
    lines.append(f"# 目标验收指标 {date_str}")
    lines.append("")

    # 1. 流水线成功率
    lines.append("## 1. 流水线成功率")
    lines.append("")
    lines.append(f"- 状态：{p.get('status', 'UNKNOWN')}")
    lines.append(f"- attempts：{p.get('attempts', 0)}")
    lines.append(f"- success：{p.get('success', 0)}")
    lines.append(f"- failed：{p.get('failed', 0)}")
    lines.append(f"- skipped：{p.get('skipped', 0)}")
    lines.append(f"- in_progress：{p.get('in_progress', 0)}")
    lines.append(f"- success_rate：{_fmt_rate(p.get('success_rate'))}")
    if p.get("error"):
        lines.append(f"- 错误：{p['error']}")
    lines.append("- 原始证据：")
    if p.get("raw_evidence"):
        for ev in p["raw_evidence"]:
            lines.append(f"  - {ev}")
    else:
        lines.append("  - 无")
    lines.append("")

    # 2. 数据完整率
    lines.append("## 2. 数据完整率")
    lines.append("")
    lines.append(f"- 状态：{d.get('status', 'UNKNOWN')}")
    lines.append(f"- 数据源：{_fmt(d.get('source'))}")
    lines.append(f"- stock_csv rows：{_fmt(d.get('rows'))}")
    lines.append(f"- nonzero_price_ratio：{_fmt(d.get('nonzero_price_ratio'))}")
    lines.append(f"- nonempty_volume_ratio：{_fmt(d.get('nonempty_volume_ratio'))}")
    lines.append(f"- history latest_date：{_fmt(d.get('latest_date'))}")
    lines.append(f"- history lag_days：{_fmt(d.get('lag_days'))}")
    lines.append(f"- multi_vote count：{_fmt(d.get('multi_vote_count'))}")
    lines.append(f"- completeness_pct：{_fmt_rate(d.get('completeness_pct'))}")
    lines.append(f"- rows_ok：{_fmt_bool(d.get('rows_ok'))}")
    lines.append(f"- lag_days_ok：{_fmt_bool(d.get('lag_days_ok'))}")
    lines.append(f"- overall：{d.get('status', 'UNKNOWN')}")
    if d.get("error"):
        lines.append(f"- 错误：{d['error']}")
    lines.append("- 原始证据：")
    if d.get("raw_evidence"):
        for ev in d["raw_evidence"]:
            lines.append(f"  - {ev}")
    else:
        lines.append("  - 无")
    lines.append("")

    # 3. 测试/自检通过率
    lines.append("## 3. 测试/自检通过率")
    lines.append("")
    lines.append("- 说明：自检通过率（测试通过率的每日代理指标）")
    lines.append(f"- 状态：{s.get('status', 'UNKNOWN')}")
    lines.append(f"- score.passed：{_fmt(s.get('passed'))}")
    lines.append(f"- score.total：{_fmt(s.get('total'))}")
    lines.append(f"- self_check_pass_rate：{_fmt_rate(s.get('self_check_pass_rate'))}")
    if s.get("error"):
        lines.append(f"- 错误：{s['error']}")
    lines.append("- 原始证据：")
    if s.get("raw_evidence"):
        for ev in s["raw_evidence"]:
            lines.append(f"  - {ev}")
    else:
        lines.append("  - 无")
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    lines.append(report.get("conclusion", "N/A"))
    lines.append("")

    return "\n".join(lines)


def write_report(
    report: Dict[str, Any],
    reports_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    reports_dir = Path(reports_dir) if reports_dir is not None else REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    date_str = report["date"]
    md_path = reports_dir / f"goal_metrics_{date_str}.md"
    json_path = reports_dir / f"goal_metrics_{date_str}.json"

    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return md_path, json_path


def main() -> int:
    try:
        report = build_report()
        md_path, json_path = write_report(report)
        print(md_path)
        print(json_path)
    except Exception as exc:  # 保证 rc=0，缺失/坏文件不会抛异常
        print(f"goal_metrics: 已降级完成（{exc}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## `core/pipeline.py` 注册片段

只加注册表条目，不动执行逻辑：

```python
# core/pipeline.py

_GOAL_METRICS_STEP = {
    "name": "goal_metrics",
    "label": "目标指标",
    "tier": "beginner",
    "schedule": "daily",
    "command": ["python", "goal_metrics.py"],
    "description": "计算目标验收三指标：流水线成功率、数据完整率、测试/自检通过率",
}

try:
    _idx = next(
        i for i, _s in enumerate(PIPELINE_STEPS)
        if "自检" in str(_s.get("label", ""))
    )
    PIPELINE_STEPS.insert(_idx, _GOAL_METRICS_STEP)
except StopIteration:
    PIPELINE_STEPS.append(_GOAL_METRICS_STEP)
```

---

## 测试要点

用 `tmp_path` 构造本地文件场景，并 `monkeypatch` 模块常量：

1. **流水线成功率**
   - 构造 4 个 `pipeline_YYYYMMDD.log`：
     - 今天无终态 → `in_progress`
     - 旧无终态 → `failed`
     - 含 `Pipeline complete` → `success`
     - 含 `[SKIP] 非交易日` → `skipped`
   - 断言 `attempts/success/failed/skipped/success_rate`。

2. **数据完整率**
   - 构造 `data_health_YYYYMMDD.md`：
     - `stock_csv` 行包含 `rows / nonzero_price_ratio / nonempty_volume_ratio`
     - `history` 行包含 `latest_date / lag_days`
     - `multi_vote` 行包含 `count`
   - 断言 `completeness_pct = round(100*(ratio*0.6 + volume*0.4), 2)`
   - 覆盖 `OK / DEGRADED / FAIL` 分支。
   - monkeypatch `_get_min_stock_rows` 和 `MAX_HISTORY_LAG_DAYS`。

3. **测试/自检通过率**
   - 构造 `system_self_check_v86.json`：
     - `{"score": {"passed": 9, "total": 10}}`
     - 断言 `self_check_pass_rate == 90.0`。
   - 坏 JSON / 缺字段 → `status == "UNKNOWN"`，不抛异常。

4. **缺失文件 / 坏文件**
   - 删掉 `logs/`、`reports/`、`data_health_*.md`、`system_self_check_v86.json`
   - 断言对应指标为 `UNKNOWN`，缺失字段为 `N/A`，`main()` 返回 `0`。

5. **报告生成**
   - 调用 `build_report(...)` + `write_report(...)`
   - 断言生成 `reports/goal_metrics_YYYYMMDD.md` 和 `.json`，JSON 可反序列化。

6. **注册表**
   - 断言 `PIPELINE_STEPS` 中新增步骤的 `label == "目标指标"`，且位于「自检」之前。


## 总指挥仲裁与修正

- 采纳 Flash 的三段式计算与 UNKNOWN 降级策略；拒绝其「用 list.insert 操作 PIPELINE_STEPS」的片段——本项目 PIPELINE_STEPS 是**字典注册表**，直接在 `self_check` 前插入条目。
- 修正 Flash 的 `_as_float` 对 `95%`/`0.95` 歧义问题：data_health 报告里的 ratio 恒为 0~1 小数，直接用 float 解析，不猜测百分比。
- 关键补丁：旧日志在「非交易日干净跳过」修复前，周六/周日会以 `check_trading_day FATAL` 结束；若把周末 FATAL 计入失败，流水线成功率被系统性低估。分类器把「周末 + FATAL + 无 Pipeline complete」归为 skipped_non_trading，不计分母。
- `main()` 永不非零退出：指标本身可 UNKNOWN，但指标脚本失败不能阻断流水线（fail-open）。

## 落地改动

- 新增 `goal_metrics.py`：`compute_pipeline_metrics / compute_data_completeness / compute_self_check_pass_rate / build_report / render_markdown / write_report`。
- `core/pipeline.py`：PIPELINE_STEPS 新增 `goal_metrics`（always_on，daily，label「目标指标」），位置在 self_check 前。
- `tests/test_goal_metrics.py`：12 项回归。

## 实跑证据（2026-08-24）

- `python goal_metrics.py` → rc=0，生成 `reports/goal_metrics_20260824.md/json`
- 流水线成功率：**62.5%**（DEGRADED；attempts=16，success=10，failed=6，周末 skip=4）
- 数据完整率：**99.95%**（OK；stock rows=5554，nonzero=0.9991，volume=1.0，history lag=0）
- 自检通过率：**100.0%**（142/142）

## 风险

1. 流水线成功率基于日志文本分类：旧日志里非周末 FATAL 仍计入失败，这是保守口径；如果某日因 Alpha Gate 暂停（现在归 success）未来想单独统计，需要拆分状态。
2. 数据完整率只是 data_health 快照的加权合成（nonzero 60% + volume 40%），不等于「缺了几只股票」；更细的 completeness 需要 stock csv 与交易日历逐日比对。
3. 测试通过率用每日自检代理，不是每次 pytest 全量；要拿真实 pytest 数字需要每日落 test_run json（后续可做，但会拉长流水线）。

## 下一轮候选

- 数据完整率升级为逐交易日 stock_*.csv 覆盖比对。
- pytest 每日测试结果落盘并接入指标。
- 流水线成功率的月度趋势与失败原因 top 分类。
