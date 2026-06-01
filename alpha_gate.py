"""Alpha Gate v1 — auto-pause the daily pipeline when system underperforms HS300
   for N consecutive trading days.

Why this exists:
    etf_gate.py is passive — it only adds a banner. With 1200 RMB capital and
    real backtest showing -0.71% excess vs HS300, the user can keep ignoring
    the banner and burn money. Alpha Gate is the active fail-safe: 5 consecutive
    severe days (excess <= 0% vs HS300) flips paused=True, blocking selection
    runs until the user explicitly resets.

State file: data/alpha_gate_state.json
{
  "paused": false,
  "consecutive_severe_days": 0,
  "last_check": "2026-05-23T16:30:00",
  "last_severity": "severe",
  "last_excess_pct": -0.71,
  "pause_reason": "...",
  "pause_started": null,
  "history": [...]   // last 30 entries
}

Usage:
    python alpha_gate.py            # run check, update state, print status
    python alpha_gate.py --status   # read-only status query
    python alpha_gate.py --reset    # clear paused + counter (resume pipeline)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATE_FILE_NAME = 'alpha_gate_state.json'

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get
from etf_gate import EtfGateResult, evaluate_etf_gate


@dataclass(frozen=True)
class AlphaGateResult:
    paused: bool
    consecutive_severe_days: int
    severity: str
    excess_pct: Optional[float]
    pause_triggered_now: bool   # True iff this check flipped paused False -> True
    pause_reason: str
    state_file: str
    counted: bool = True        # False = 非交易日跳过，未读取行情也未写盘


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _default_is_trading_day() -> tuple[bool, str]:
    """默认交易日判定：check_trading_day（网络，fail-open）。测试可注入替换。"""
    try:
        from check_trading_day import is_trading_day
        ok, reason = is_trading_day()
        return bool(ok), str(reason)
    except Exception as exc:
        # 判定器不可用时 fail-open：宁可当交易日继续流水线，也不要静默漏跑。
        return True, f'trading-day check unavailable (fail-open): {exc}'


def _state_file_path(state_dir: str) -> str:
    return os.path.join(state_dir, STATE_FILE_NAME)


def _blank_state() -> dict[str, Any]:
    return {
        'paused': False,
        'consecutive_severe_days': 0,
        'last_check': None,
        'last_severity': 'unknown',
        'last_excess_pct': None,
        'pause_reason': '',
        'pause_started': None,
        'history': [],
    }


def _load_state(state_dir: str) -> dict[str, Any]:
    path = _state_file_path(state_dir)
    state = _blank_state()
    if not os.path.exists(path):
        return state
    try:
        with open(path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
    except (OSError, json.JSONDecodeError):
        return state
    if not isinstance(loaded, dict):
        return state
    state.update(loaded)
    if not isinstance(state.get('history'), list):
        state['history'] = []
    state['paused'] = bool(state.get('paused', False))
    try:
        state['consecutive_severe_days'] = int(state.get('consecutive_severe_days', 0))
    except (TypeError, ValueError):
        state['consecutive_severe_days'] = 0
    if state['consecutive_severe_days'] < 0:
        state['consecutive_severe_days'] = 0
    return state


# v8.7: 抽到 utils/file_io.py（保留 sort_keys=True 的 alpha_gate 流派语义）
from utils.file_io import atomic_write_json as _atomic_write_json_base  # noqa: E402

def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    """alpha_gate 历史流派：sort_keys=True + 自动建父目录（与 sim_trade 不同）。"""
    _atomic_write_json_base(path, data, sort_keys=True, ensure_dir=True)


def _cfg_int(key: str, default: int) -> int:
    try:
        value = cfg_get(key, default)
    except Exception:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _send_bark_notification(title: str, body: str) -> None:
    """v8.6: 触发暂停时发独立 Bark 通知。失败静默 — 暂停状态已写盘。"""
    try:
        from bark_sender.push import send_bark
        send_bark(title, body)
    except Exception as exc:
        print(f'[ALPHA-GATE] Bark notification failed: {exc}')


def _build_pause_reason(consecutive_severe_days: int,
                       lookback_days: int,
                       excess_pct: Optional[float]) -> str:
    pct_str = f'{excess_pct:.2f}%' if excess_pct is not None else 'unknown'
    return (f'Underperformed HS300 for {consecutive_severe_days} consecutive trading days '
            f'(threshold={lookback_days}, latest excess={pct_str})')


def check_alpha_gate(
    state_dir: str = DATA_DIR,
    trading_day_ok: Optional[bool] = None,
    is_trading_day_fn=None,
) -> AlphaGateResult:
    """Run the gate check once. Updates state file. Returns result.

    Logic:
    - 交易日判定：非交易日直接返回当前状态、不读行情也不写盘（counted=False）。
      pipeline 已确认过交易日时可传 trading_day_ok=True 省一次网络请求。
    - severity == 'severe' -> increment counter（同一交易日只 +1）
    - severity in ('normal', 'warning') -> reset counter to 0
    - severity in ('unknown', 'stale') -> leave counter unchanged (don't penalize bad data)
    - counter >= LOOKBACK_DAYS -> set paused=True
    - Once paused: stays paused until manual reset (even if today non-severe)
    - History capped at LAST N entries
    - Bark notification fires only on the transition False -> True
    """
    state_file = _state_file_path(state_dir)
    state = _load_state(state_dir)
    was_paused = bool(state.get('paused', False))
    consecutive_severe_days = int(state.get('consecutive_severe_days', 0))

    # v8.7: Alpha Gate 只按交易日计数 —— 周六/周日/已确认的非交易日不碰状态。
    # Why: 计划任务 Daily 触发，周末如果也 +1，5 个交易日的门槛实际约 3 个交易日就误触发。
    if trading_day_ok is None:
        checker = is_trading_day_fn or _default_is_trading_day
        try:
            trading_day_ok, _reason = checker()
            trading_day_ok = bool(trading_day_ok)
        except Exception as exc:
            print(f"[ALPHA-GATE] trading-day check failed (fail-open): {exc}")
            trading_day_ok = True
    if not trading_day_ok:
        return AlphaGateResult(
            paused=was_paused,
            consecutive_severe_days=consecutive_severe_days,
            severity='non_trading',
            excess_pct=None,
            pause_triggered_now=False,
            pause_reason=str(state.get('pause_reason') or '') if was_paused else '',
            state_file=state_file,
            counted=False,
        )

    lookback_days = max(1, _cfg_int('alpha_gate.lookback_days', 5))
    history_keep_count = max(0, _cfg_int('alpha_gate.history_keep_count', 30))

    checked_at = _now_iso()

    etf_result: EtfGateResult = evaluate_etf_gate()
    severity = (getattr(etf_result, 'severity', 'unknown') or 'unknown').strip().lower()
    excess_pct = getattr(etf_result, 'excess_pct', None)

    # Round-2 修复（2026-05-30）：同一交易日重复运行不再二次累加 severe_days
    # Why: pipeline 多跑一次 / 手动 rerun 会让 consecutive_severe_days 一天 +2，
    # 5 日警戒在 3 个日历日内就误触发 → 系统冤枉暂停。改用 last_counted_date 去重。
    today_str = _now_iso()[:10]  # YYYY-MM-DD
    last_counted = str(state.get('last_counted_date') or '')
    counted_today = (last_counted == today_str)

    if severity == 'severe':
        if not counted_today:
            consecutive_severe_days += 1
            state['last_counted_date'] = today_str
        # else: 今天已计过一次 severe，不重复累加
    elif severity not in ('unknown', 'stale'):
        consecutive_severe_days = 0
        state['last_counted_date'] = today_str
    # unknown / stale: leave counter unchanged，不更新 last_counted_date

    paused = was_paused
    pause_started = state.get('pause_started')
    pause_reason = str(state.get('pause_reason') or '')
    pause_triggered_now = False

    if consecutive_severe_days >= lookback_days:
        paused = True
        if not was_paused:
            pause_triggered_now = True
            pause_started = checked_at
        if pause_triggered_now or not pause_reason:
            pause_reason = _build_pause_reason(
                consecutive_severe_days=consecutive_severe_days,
                lookback_days=lookback_days,
                excess_pct=excess_pct,
            )

    state.update({
        'paused': paused,
        'consecutive_severe_days': consecutive_severe_days,
        'last_check': checked_at,
        'last_severity': severity,
        'last_excess_pct': excess_pct,
        'pause_reason': pause_reason if paused else '',
        'pause_started': pause_started if paused else None,
    })

    history = state.get('history') or []
    history.append({
        'checked_at': checked_at,
        'severity': severity,
        'excess_pct': excess_pct,
        'consecutive_severe_days': consecutive_severe_days,
        'paused': paused,
        'pause_triggered_now': pause_triggered_now,
    })
    state['history'] = history[-history_keep_count:] if history_keep_count else []

    _atomic_write_json(state_file, state)

    if pause_triggered_now:
        _send_bark_notification(
            title='[Alpha Gate] 系统已暂停',
            body=(f'连续 {consecutive_severe_days} 天跑输沪深300 (latest {excess_pct:+.2f}%); '
                  f'选股流水线已停。建议直接买 510300 ETF 长持。'
                  f'确认要重启请运行: python alpha_gate.py --reset')
            if excess_pct is not None else
            (f'连续 {consecutive_severe_days} 天跑输沪深300; 选股流水线已停。'
             f'确认要重启请运行: python alpha_gate.py --reset'),
        )

    return AlphaGateResult(
        paused=paused,
        consecutive_severe_days=consecutive_severe_days,
        severity=severity,
        excess_pct=excess_pct,
        pause_triggered_now=pause_triggered_now,
        pause_reason=pause_reason if paused else '',
        state_file=state_file,
    )


def is_paused(state_dir: str = DATA_DIR) -> tuple[bool, str]:
    """Read state file. Returns (paused_bool, reason_str). Never raises.

    Used by core/pipeline.run_all() for early-return."""
    try:
        state = _load_state(state_dir)
        return bool(state.get('paused', False)), str(state.get('pause_reason') or '')
    except Exception:
        return False, ''


def reset_gate(state_dir: str = DATA_DIR) -> dict[str, Any]:
    """Clear paused flag and counter; preserve history. CLI: --reset."""
    state_file = _state_file_path(state_dir)
    state = _load_state(state_dir)
    state.update({
        'paused': False,
        'consecutive_severe_days': 0,
        'pause_reason': '',
        'pause_started': None,
    })
    _atomic_write_json(state_file, state)
    return state


def _reconfigure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            try:
                reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass


def main() -> int:
    _reconfigure_utf8()
    parser = argparse.ArgumentParser(description='Alpha Gate v1 — pipeline pause on HS300 underperformance')
    parser.add_argument('--reset', action='store_true', help='clear paused flag and counter')
    parser.add_argument('--status', action='store_true', help='print current status (read-only)')
    args = parser.parse_args()

    if args.reset:
        state = reset_gate()
        print(f"[RESET] paused=False consecutive_severe_days={state.get('consecutive_severe_days', 0)}")
        return 0

    if args.status:
        state = _load_state(DATA_DIR)
        paused = bool(state.get('paused', False))
        print(f"[STATUS] paused={paused} "
              f"consecutive_severe_days={state.get('consecutive_severe_days', 0)} "
              f"last_severity={state.get('last_severity', 'unknown')} "
              f"last_excess_pct={state.get('last_excess_pct')}")
        if paused:
            print(f"[PAUSED] {state.get('pause_reason', '')}")
        return 0

    result = check_alpha_gate()
    print(f"[ALPHA-GATE] paused={result.paused} "
          f"consecutive_severe_days={result.consecutive_severe_days} "
          f"severity={result.severity} "
          f"excess_pct={result.excess_pct}")
    if result.paused:
        print(f"[PAUSED] {result.pause_reason}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
