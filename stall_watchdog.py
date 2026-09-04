#!/usr/bin/env python3
"""Pipeline stall watchdog (read-only).

Compares last pipeline activity (latest logs/pipeline_*.log and
orders/daily_orders_*.json dates) against the reference trading day
(latest data/stock_*.csv filename date). Trading days are approximated
as Mon-Fri calendar weekdays between the two dates. If the pipeline
lags the reference by >= 2 trading days, push a Bark alert.

--dry-run prints the verdict without pushing anything.
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _latest_date(pattern):
    dates = []
    for p in BASE.glob(pattern):
        m = re.search(r"[0-9]{8}", p.name)
        if m:
            dates.append(m.group(0))
    return max(dates) if dates else None


def parse_yyyymmdd(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def weekdays_between(start_exclusive, end_inclusive):
    """Count Mon-Fri dates in (start, end]. Reversed window yields 0."""
    if end_inclusive <= start_exclusive:
        return 0
    count = 0
    d = start_exclusive + timedelta(days=1)
    while d <= end_inclusive:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def main():
    ap = argparse.ArgumentParser(description="pipeline stall watchdog (read-only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the verdict without pushing any alert")
    ap.add_argument("--threshold", type=int, default=2,
                    help="alert when lag >= this many trading days (default 2)")
    args = ap.parse_args()

    log_date = _latest_date("logs/pipeline_*.log")
    orders_date = _latest_date("orders/daily_orders_*.json")
    ref_date = _latest_date("data/stock_*.csv")

    if not ref_date:
        print("[watchdog] no data/stock_*.csv found, cannot determine reference trading day")
        return 1
    known = [x for x in (log_date, orders_date) if x]
    if not known:
        print("[watchdog] no pipeline logs and no orders files found")
        return 1
    activity = max(known)

    lag = weekdays_between(parse_yyyymmdd(activity), parse_yyyymmdd(ref_date))
    stalled = lag >= args.threshold

    print("[watchdog] latest pipeline log : %s" % log_date)
    print("[watchdog] latest orders file  : %s" % orders_date)
    print("[watchdog] reference trade day : %s (max data/stock_*.csv)" % ref_date)
    print("[watchdog] last activity       : %s" % activity)
    print("[watchdog] lag                 : %d trading days (threshold %d)" % (lag, args.threshold))
    print("[watchdog] verdict             : %s" % ("STALL" if stalled else "OK"))

    if not stalled:
        return 0

    title = "Quant pipeline stall alert"
    body = ("pipeline stalled: last activity %s, reference %s, lag %d trading days"
            % (activity, ref_date, lag))
    print("[watchdog] would push: %s | %s" % (title, body))
    if args.dry_run:
        print("[watchdog] dry-run: alert NOT sent")
        return 0

    from bark_sender import send_bark
    send_bark(title, body)
    print("[watchdog] alert sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
