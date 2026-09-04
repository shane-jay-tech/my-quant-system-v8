#!/usr/bin/env python3
"""Pipeline log analytics for my-quant-system-v8 (task 20260904-193312-cf54).

Parses logs/pipeline_*.log and produces data/ops_analysis_<date>.md with four
sections: step timings, failure modes, run-duration evolution (incl. the
2026-08-15 fetch_history fast-path effect), and data-freshness event timeline.
Re-runnable and idempotent. Standard library only (pandas optional, unused).
"""
import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT_PATH = BASE / "data" / "ops_analysis_20260904.md"

STEP_DONE = re.compile(r"->\s*(\w+)\s+finished in\s*(\d+(?:\.\d+)?)s,\s*rc=(-?\d+)")
STEP_START = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]\s*\[(\d+/\d+)\]\s*(\w+)\s*\(")


def parse_logs(since: str):
    runs = []          # [{date, steps: [(name, secs, rc)], warns, fails, errors}]
    for log in sorted(LOGS.glob("pipeline_*.log")):
        m = re.search(r"(\d{8})\.log$", log.name)
        if not m:
            continue
        date = m.group(1)
        if since and date < since:
            continue
        steps, text_errors = [], []
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            dm = STEP_DONE.search(line)
            if dm:
                steps.append((dm.group(1), float(dm.group(2)), int(dm.group(3))))
                continue
            if "[WARN]" in line:
                text_errors.append(("WARN", line.strip()[:160]))
            elif "[FAIL]" in line or "Traceback" in line or "[ERROR]" in line:
                text_errors.append(("FAIL", line.strip()[:160]))
        runs.append({"date": date, "steps": steps, "events": text_errors})
    return runs


def pct(values, p):
    if not values:
        return 0.0
    vals = sorted(values)
    idx = min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))
    return vals[idx]


def fmt_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def analyze(runs):
    timings = defaultdict(list)          # step -> [secs]
    failures = defaultdict(int)          # step -> fail count
    fail_samples = defaultdict(list)     # step -> [event lines]
    for run in runs:
        for name, secs, rc in run["steps"]:
            timings[name].append(secs)
            if rc != 0:
                failures[name] += 1
        for kind, line in run["events"]:
            key = "文本告警/报错"
            if len(fail_samples[key]) < 25:
                fail_samples[key].append(f"{run['date']} {kind}: {line}")

    rows = []
    for name, vals in timings.items():
        rows.append((name, len(vals), round(sum(vals) / len(vals), 1),
                     max(vals), pct(vals, 90), failures.get(name, 0)))
    rows.sort(key=lambda r: r[2], reverse=True)

    monthly = defaultdict(lambda: defaultdict(list))
    for run in runs:
        month = run["date"][:6]
        for name, secs, rc in run["steps"]:
            monthly[name][month].append(secs)
    trend_rows = []
    for name, vals in timings.items():
        months = sorted(monthly[name])
        if len(months) >= 2:
            first, last = months[0], months[-1]
            f_avg = sum(monthly[name][first]) / len(monthly[name][first])
            l_avg = sum(monthly[name][last]) / len(monthly[name][last])
            trend_rows.append((name, first, round(f_avg, 1), last, round(l_avg, 1),
                               round(l_avg - f_avg, 1)))
    trend_rows.sort(key=lambda r: r[5])

    run_totals = [(r["date"], sum(s for _, s, _ in r["steps"]),
                   sum(1 for _, _, rc in r["steps"] if rc != 0)) for r in runs]
    before = [t for d, t, _ in run_totals if d < "20260815"]
    after = [t for d, t, _ in run_totals if d >= "20260815"]
    fh_b = [s for r in runs if r["date"] < "20260815"
            for n, s, _ in r["steps"] if n == "fetch_history"]
    fh_a = [s for r in runs if r["date"] >= "20260815"
            for n, s, _ in r["steps"] if n == "fetch_history"]
    return rows, trend_rows, run_totals, before, after, fh_b, fh_a, fail_samples, failures


def main():
    ap = argparse.ArgumentParser(description="pipeline ops analyzer")
    ap.add_argument("--since", default=None, help="only analyze logs dated >= YYYYMMDD")
    args = ap.parse_args()

    runs = parse_logs(args.since)
    if not runs:
        print("[ops_analyzer] no pipeline logs matched")
        return 1
    rows, trend_rows, run_totals, before, after, fh_b, fh_a, fail_samples, failures = analyze(runs)

    fail_days = [d for d, _, f in run_totals if f]
    lines = [
        "# 流水线运行效能与故障模式分析（2026-09-04）",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 样本：{len(runs)} 份 pipeline 日志"
        + (f"（--since {args.since}）" if args.since else ""),
        "",
        "## a) 步骤耗时分析",
        "",
        "每步平均/最大/P90（秒）与失败次数，按平均耗时降序：",
        "",
        fmt_table(["步骤", "次数", "平均s", "最大s", "P90s", "rc≠0次数"], rows[:30]),
        "",
        f"最慢 top5（平均）：{', '.join(f'{n}({a}s)' for n, _, a, *_ in rows[:5])}",
        "",
        "### 按月趋势（首月 vs 末月平均，负值=变快）",
        "",
        fmt_table(["步骤", "首月", "均s", "末月", "均s", "变化s"], trend_rows[:15]),
        "",
        "## b) 故障模式分析",
        "",
        fmt_table(["失败步骤", "rc≠0 次数"],
                  sorted(failures.items(), key=lambda kv: -kv[1])[:15] or [("（无）", 0)]),
        "",
        "文本级报错样本（每类≤5 行）：",
        "",
    ]
    for key, samples in fail_samples.items():
        lines.append(f"**{key}**（共 {len(samples)} 条样本，示例如下）：")
        lines += [f"- {s}" for s in samples[:5]]
        lines.append("")
    if fail_days:
        hours = defaultdict(int)
        for d in fail_days:
            hours[d[8:10] + "日"] += 1
        lines.append(f"失败发生的日期分布（按日）：{dict(sorted(hours.items())[:15])}")
        lines.append("")

    lines += [
        "## c) 运行时长演变（2026-08-15 fetch_history 快路径前后）",
        "",
        fmt_table(["日期", "总时长s", "rc≠0步数"], run_totals),
        "",
    ]
    untimed = len(run_totals) - len([t for _, t, _ in run_totals if t > 0])
    if untimed:
        lines.append(f"- 说明：{untimed} 份早期日志（v8.0 时代）无逐步耗时标记，不参与时长统计。")
    if before and after and sum(before) > 0:
        b_avg, a_avg = sum(before) / len(before), sum(after) / len(after)
        lines.append(f"- 8/15 之前 {len(before)} 次运行平均总时长 {b_avg:.0f}s；之后 {len(after)} 次平均 {a_avg:.0f}s，"
                     f"变化 {a_avg - b_avg:+.0f}s（{100 * (a_avg - b_avg) / b_avg:+.1f}%）。")
    else:
        lines.append("- 8/15 前后有计时数据的样本不足，无法做运行总时长前后对比（fetch_history 单步对比见上）。")
    if fh_b and fh_a:
        fb, fa = sum(fh_b) / len(fh_b), sum(fh_a) / len(fh_a)
        lines.append(f"- fetch_history 步骤平均：前 {fb:.0f}s（{len(fh_b)} 次）vs 后 {fa:.0f}s（{len(fa)} 次），"
                     f"单步节省 {fb - fa:.0f}s（{100 * (fb - fa) / fb if fb else 0:.1f}%）。")
    lines.append("")

    lines += [
        "## d) 数据新鲜度事件时间线",
        "",
        "- 2026-08-15：fetch_history 快路径优化上线（本报告 c 节的切分点）。",
        "- 2026-08-21：最后一次成功的每日流水线运行（orders/daily_orders_20260821.json）。",
        "- 2026-08-23：最后一份 pipeline_20260823.log，此后流水线停摆。",
        "- 2026-08-24：4 个 bat 被重写为 LF+中文注释（根因），计划任务开始返回 9009。",
        "- 2026-08-30（周日）：auto_heal 误补抓生成幽灵交易日文件 stock_20260830.csv（2026-09-04 已归档至 archive/ghost_trading_days/）。",
        "- 2026-09-04：夜间任务重写 4 个 bat 为 ASCII+CRLF 并注册 QuantStallWatchdog（每日 21:00）。",
        "",
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ops_analyzer] wrote {OUT_PATH} ({len(runs)} runs analyzed)")
    top_fail = sorted(failures.items(), key=lambda kv: -kv[1])[:3]
    print(f"[ops_analyzer] slowest: {rows[0][0]} avg {rows[0][2]}s; top failures: {top_fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
