"""ETF Gate v1 — when picks underperform HS300, force a top banner saying
"don't bother stock-picking, just buy ETF".

Why this exists:
    The user has 1200 RMB capital. Real backtest shows 10-day net +1.41% but
    excess vs HS300 is -0.71% — i.e. you'd be better off buying the index ETF
    and not running this system at all. Every daily Bark push must surface
    that fact prominently or the user loses money "thinking" the system works.

Design:
    1. Read the latest excess-return number from results/honest_evaluation.md
       (or fall back to reports/benchmark_*.md if the first source is missing).
    2. Classify into severe / warning / normal / stale / unknown.
    3. Format a short top-of-message banner (no emoji, ASCII separator only).
    4. Bark builder calls evaluate_etf_gate() and prepends the banner.

Thresholds (calibrated to 1200 RMB capital + 5 RMB commission floor):
    excess <= 0.0%  -> severe   (red banner: "buy ETF instead")
    excess <= 1.0%  -> warning  (yellow: "barely beats benchmark, fees eat it")
    excess >  1.0%  -> normal   (small green note: "system is alpha-positive")

Data freshness:
    honest_evaluation.md is regenerated weekly. If the file is older than
    max_age_days, the gate downgrades to "stale" — message tells the user to
    re-run the backtest rather than acting on stale data.
"""
from __future__ import annotations

import glob
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

# v8.6: 阈值统一从 core/config.py 读取（alpha_gate 也用同一组），避免两处漂移
sys.path.insert(0, BASE_DIR)
from core.config import get as _cfg_get
SEVERE_THRESHOLD_PCT = float(_cfg_get('gate.severe_excess_pct', 0.0))
WARNING_THRESHOLD_PCT = float(_cfg_get('gate.warning_excess_pct', 1.0))
DEFAULT_MAX_AGE_DAYS = int(_cfg_get('gate.max_age_days', 10))  # 已废弃：v8.7 起不再用报告 mtime 判陈旧
# v8.7: 陈旧判定改为"行情基线数据(hs300_index.csv)落后本地最新交易日多少个交易日"
STALE_LAG_TRADING_DAYS = int(_cfg_get('gate.stale_lag_trading_days', 3))
# 文案里的本金口径跟配置走（2026-08-24 起为 2400），避免闸门提示还用旧的 1200
GATE_CAPITAL = float(_cfg_get('sim.initial_capital', 2400))

RECOMMENDED_ETFS = "510300 / 510310 (沪深300ETF)"


@dataclass
class EtfGateResult:
    severity: str  # "severe" | "warning" | "normal" | "stale" | "unknown"
    message: str
    excess_pct: Optional[float]
    source: str
    data_age_days: Optional[float] = None
    recommended_etf: str = RECOMMENDED_ETFS
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def should_show_banner(self) -> bool:
        """Only severe / warning / stale produce a visible top banner.
        normal => optional small footnote; unknown => silent."""
        return self.severity in ("severe", "warning", "stale")


# ---- parsing ----

# Match these forms anywhere in a markdown document:
#   **超额收益**: -0.71%
#   超额收益: -0.71%
#   超额收益：+1.23%
#   | 超额（vs HS300）| -0.71% |
_EXCESS_PATTERNS = [
    re.compile(r"\*?\*?超额收益\*?\*?\s*[:：]\s*([+\-]?\d+(?:\.\d+)?)\s*%"),
    re.compile(r"超额\s*[（(]\s*vs\s*HS300\s*[)）]\s*[\|\:：]\s*([+\-]?\d+(?:\.\d+)?)\s*%"),
]


def _parse_excess_from_text(text: str) -> Optional[float]:
    for pat in _EXCESS_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _file_age_days(path: Path) -> Optional[float]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return (datetime.now().timestamp() - mtime) / 86400.0


def _read_excess_from_file(path: Path) -> Optional[float]:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_excess_from_text(text)


def _hs300_data_lag_trading_days(base_dir: str) -> Optional[int]:
    """行情基线数据落后多少个交易日。

    口径：本地最新交易日（data/stock_*.csv 文件名）与 data/hs300_index.csv 最新
    日期之间的交易日差（用 utils.calendar，按交易日计，自动避开周末/长假误报）。

    返回 None 表示无法判定（缺 hs300 文件 / 读不出日期 / 无交易日历），
    此时按"不陈旧"处理 —— 宁可不报，也不误报。
    """
    data_dir = os.path.join(base_dir, "data")
    f = os.path.join(data_dir, "hs300_index.csv")
    if not os.path.exists(f):
        return None  # 还没有基准文件：交给 benchmark_comparison 的"数据不可用"提示，此处不误报
    # 没有任何 stock_*.csv 时 get_last_trading_day 会退回 now()（未必交易日），
    # 据此算 lag 不可靠 → 直接按"无法确定"放过，避免 bogus lag 误报。
    if not glob.glob(os.path.join(data_dir, "stock_*.csv")):
        return None
    try:
        import pandas as pd  # 局部导入：只解析超额收益的调用方无需 pandas
        df = pd.read_csv(f)
        if df.empty or "日期" not in df.columns:
            return None
        hs_last_ts = pd.to_datetime(df["日期"], errors="coerce").max()
        if pd.isna(hs_last_ts):
            return None
        hs_last = hs_last_ts.strftime("%Y-%m-%d")
        from utils.calendar import get_last_trading_day, count_trading_days
        last_td = get_last_trading_day(data_dir=data_dir)
    except Exception as exc:
        # 不静默：读不出/算不了时打印告警（仍按"无法确定"放过，避免误报红横幅）
        print(f"[ETF闸门] 行情数据新鲜度无法判定（按不陈旧处理）：{exc}")
        return None
    if hs_last >= last_td:  # ISO 日期字典序 == 时间序；基线不落后
        return 0
    # count_trading_days 为闭区间含两端，减 1 得"落后的交易日数"
    lag = count_trading_days(hs_last, last_td, data_dir=data_dir) - 1
    return max(0, lag)


# ---- main evaluator ----

def evaluate_etf_gate(
    base_dir: str = BASE_DIR,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
) -> EtfGateResult:
    """Read latest excess-vs-HS300 figure and classify into a gate severity.

    Order of preference:
        1. results/honest_evaluation.md (regenerated weekly by enhanced_backtest)
        2. newest reports/benchmark_*.md
    Returns a result with severity == "unknown" when neither source yields a
    parseable number (silent: better than a false alarm)."""
    base = Path(base_dir)

    # ---- 1) 取最新可解析的超额收益（优先 honest_evaluation.md，回退最新 benchmark_*.md）----
    primary = base / "results" / "honest_evaluation.md"
    excess = _read_excess_from_file(primary)
    source = str(primary) if excess is not None else ""

    if excess is None:
        files = sorted(glob.glob(str(base / "reports" / "benchmark_*.md")), reverse=True)
        for f in files:
            v = _read_excess_from_file(Path(f))
            if v is not None:
                excess = v
                source = f
                break

    # ---- 2) 行情基线数据新鲜度：基于 hs300_index.csv 的最新交易日（节假日安全），
    #         而非报告文件 mtime。区分"行情数据陈旧"与"回测评估老旧"，避免误导。----
    data_lag = _hs300_data_lag_trading_days(str(base))
    if data_lag is not None and data_lag >= STALE_LAG_TRADING_DAYS:
        return EtfGateResult(
            severity="stale",
            message=(
                f"[ETF闸门] 行情基线数据(沪深300)已落后 {data_lag} 个交易日未更新，"
                f"请检查每日 fetch_index 步骤是否正常运行；数据刷新后此提示自动消失。"
            ),
            excess_pct=excess,
            source="data/hs300_index.csv",
            data_age_days=float(data_lag),
        )

    if excess is None:
        return EtfGateResult(
            severity="unknown",
            message="",
            excess_pct=None,
            source="none",
            data_age_days=None,
        )

    if excess <= SEVERE_THRESHOLD_PCT:
        msg = (
            f"[ETF闸门] 系统跑输沪深300 ({excess:+.2f}%)，"
            f"对 {GATE_CAPITAL:,.0f} 元资金，建议直接买 ETF 长持（{RECOMMENDED_ETFS}），别折腾选股。"
        )
        sev = "severe"
    elif excess <= WARNING_THRESHOLD_PCT:
        msg = (
            f"[ETF闸门] 超额仅 {excess:+.2f}%，扣完佣金/印花税基本持平。"
            f"考虑改买 ETF（{RECOMMENDED_ETFS}）省心。"
        )
        sev = "warning"
    else:
        msg = f"[ETF闸门] 超额 {excess:+.2f}%，系统暂时跑赢基准，可继续运行。"
        sev = "normal"

    return EtfGateResult(
        severity=sev,
        message=msg,
        excess_pct=excess,
        source=source,
        data_age_days=None,
    )


def format_gate_banner(result: EtfGateResult) -> str:
    """Produce a top-of-Bark banner. Empty string when banner shouldn't show."""
    if result.severity == "unknown":
        return ""
    if result.severity == "normal":
        # small footnote, not a banner
        return result.message
    # severe / warning / stale: enclosed by separator lines
    sep = "=" * 32
    return f"{sep}\n{result.message}\n{sep}"


def main() -> int:
    # Windows cmd defaults to GBK; force UTF-8 so the banner doesn't garble.
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    r = evaluate_etf_gate()
    print(f"severity   : {r.severity}")
    print(f"excess_pct : {r.excess_pct}")
    print(f"source     : {r.source}")
    print(f"data_age_d : {r.data_age_days}")
    print("-" * 40)
    banner = format_gate_banner(r)
    if banner:
        print(banner)
    else:
        print("(no banner for this severity)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
