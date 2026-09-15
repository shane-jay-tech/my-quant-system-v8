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
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# ---------------------------------------------------------------------------
# 内置中国法定节假日表（工作日落假日，MM-DD 按年分组）。
# 方向性约定：**宁可少标不可多标**——少标一天假日=lag 多算一天=误报方向（符合
# e06f「宁可误报不漏报」）；多标则可能漏报真实停摆。
# 2025：已对官方安排核实（verified）。2026/2027：仅内置高置信法定节日正日推算
# （verified=False，未对官方文件逐条核对，精确清单日间可从 akshare 刷新）。
# 表外年份自动退化为 Mon-Fri 近似（本文件原行为）。
# ---------------------------------------------------------------------------
HOLIDAY_SETS = {
    2025: ({"01-01", "01-28", "01-29", "01-30", "01-31", "02-03", "02-04",
            "04-04", "05-01", "05-02", "05-05", "06-02",
            "10-01", "10-02", "10-03", "10-06", "10-07", "10-08"}, True),
    2026: ({"01-01", "01-02", "02-16", "02-17", "02-18", "02-19", "02-20",
            "04-06", "05-01", "06-19", "09-25",
            "10-01", "10-02", "10-05", "10-06", "10-07"}, False),
    2027: ({"01-01"}, False),
}


def _is_holiday(d: date) -> bool:
    entry = HOLIDAY_SETS.get(d.year)
    if not entry:
        return False
    md, _verified = entry
    return d.strftime("%m-%d") in md


def _is_trading(d: date, cal) -> bool:
    """trading_calendar 可用（非 None）时以真实日历为准；否则工作日-内置节假日。"""
    if cal is not None:
        return d.isoformat() in cal
    return d.weekday() < 5 and not _is_holiday(d)



def _latest_date(pattern):
    dates = []
    for p in BASE.glob(pattern):
        m = re.search(r"[0-9]{8}", p.name)
        if m:
            dates.append(m.group(0))
    return max(dates) if dates else None


def parse_yyyymmdd(s):
    """把 ``YYYYMMDD`` 8 位日期串解析为 ``date``。

    契约（q916-05，仅文档，不改行为）：
    - 参数语义：``s`` 为 ``YYYYMMDD`` 形态的日期串（年 ``s[:4]``、月 ``s[4:6]``、
      日 ``s[6:8]``），文件名日期与活动日均由此归一；
    - 边界：不预校验位数——短串/空串在 ``int('')`` 处抛 ``ValueError``；
      月/日越界（如 ``20260230``）由 ``date()`` 构造抛 ``ValueError``；
    - 返回值：成功→``datetime.date``；无第三态（不返回 None）；
    - 异常路径：任何非法输入一律 ``ValueError`` 向上抛，调用方自行兜底。
    """
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def weekdays_between(start_exclusive, end_inclusive, cal=None):
    """统计 ``(start_exclusive, end_inclusive]``——左开右闭区间——内的交易日天数。

    语义显式化（q914-33，仅文档，不改行为）：
    - ``start_exclusive``：**不含当日**（左开）。起点当天即使为交易日也不计入；
      参数名中的 ``_exclusive`` 即此义；
    - ``end_inclusive``：**含当日**（右闭）。终点当天为交易日则计 1；
    - 周末/节假日处理：``cal`` 提供交易日集合（'YYYY-MM-DD'）时按真实日历计数；
      ``cal=None`` 退化为「周一至周五 − 内置节假日表(HOLIDAY_SETS)」近似（原行为）；
    - 反向窗口（``end_inclusive <= start_exclusive``）一律返回 0，不抛错。
    （原简注：统计 (start, end] 内的交易日；反向窗口 yield 0。）
    """
    if end_inclusive <= start_exclusive:
        return 0
    count = 0
    d = start_exclusive + timedelta(days=1)
    while d <= end_inclusive:
        if _is_trading(d, cal):
            count += 1
        d += timedelta(days=1)
    return count


def main():
    """看门狗主入口：比对最后活动日与参照交易日，lag≥阈值则 Bark 告警。

    契约（q916-05，仅文档，不改行为）：
    - 参数语义：argv 接 ``--dry-run``（只打印判定，不推送任何告警）与
      ``--threshold``（告警阈值，单位交易日，默认 2）；
    - 边界：参照日＝max(最新 stock csv 日, ≤今天的最近交易日)——stock 缺失时
      退化用最近交易日，故「无 stock csv」返回 1 分支实际不可达（防御保留）；
      logs 与 orders 全缺→活动日无法确定→返回 1；日历不可用逐级退化
      （真实日历→内置节假日表→Mon-Fri），参见 wt7 注；
    - 返回值：0＝正常收敛（OK 判定，或 STALL 但 ``--dry-run`` 未推送）；
      1＝输入缺失（无任何活动记录）；不返回 None；
    - 异常路径：非 dry-run 的 STALL 分支才 ``import bark_sender`` 并推送，
      其异常不在此捕获（向上抛）。
    """
    ap = argparse.ArgumentParser(description="pipeline stall watchdog (read-only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the verdict without pushing any alert")
    ap.add_argument("--threshold", type=int, default=2,
                    help="alert when lag >= this many trading days (default 2)")
    args = ap.parse_args()

    log_date = _latest_date("logs/pipeline_*.log")
    orders_date = _latest_date("orders/daily_orders_*.json")
    stock_date = _latest_date("data/stock_*.csv")

    # 参照日 = max(最新 stock csv 日, ≤今天的最近一个交易日)。
    # 幽灵文件归档后 stock 日可能早于最后活动日，反向窗口会漏报；
    # 参照日永不早于活动日即可保证停摆可检出。
    # wt7（2026-09-09）：交易日判定接入 utils.trading_calendar（缓存/akshare），
    # 不可用时退化为工作日-内置节假日表（HOLIDAY_SETS），再退化 Mon-Fri 近似。
    cal = None
    try:
        from utils.trading_calendar import get_trading_days
        cal = get_trading_days(str(BASE / "data"))
    except Exception as _cal_exc:
        print("[watchdog] calendar unavailable (%s), fallback to builtin table" % _cal_exc)

    today = date.today()
    recent_weekday = today
    while not _is_trading(recent_weekday, cal):
        recent_weekday -= timedelta(days=1)
    ref_date = stock_date
    if not ref_date or parse_yyyymmdd(recent_weekday.isoformat().replace("-", "")) > parse_yyyymmdd(ref_date):
        ref_date = recent_weekday.isoformat().replace("-", "")

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
    print("[watchdog] reference trade day : %s (max(stock csv, recent weekday))" % ref_date)
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
