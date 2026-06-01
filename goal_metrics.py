#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目标验收指标（本地快照，无网络）

每天计算并落盘三项验收指标：
1. 流水线成功率 —— 扫描 logs/pipeline_*.log 最近 20 个有终态的交易日运行；
   非交易日 [SKIP] 不计入分母；Alpha Gate 主动暂停视作成功（设计内行为）。
2. 数据完整率 —— 读最新 reports/data_health_*.md 的 stock_csv / history / multi_vote 行。
3. 测试/自检通过率 —— 读 reports/system_self_check_v86.json（每日测试代理指标）。

输出：reports/goal_metrics_YYYYMMDD.md + 同名 json。任何文件缺失/解析失败都
降级为 UNKNOWN 并继续，rc 恒为 0。
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
DATA_DIR = os.path.join(BASE_DIR, 'data')

RECENT_LOG_LIMIT = 20
DEFAULT_MIN_STOCK_ROWS = 4000
MAX_HISTORY_LAG_DAYS = 5
COMPLETENESS_OK = 95.0
COMPLETENESS_DEGRADED = 80.0

_DATE_RE = re.compile(r'pipeline_(\d{8})\.log$')
_DATAHEALTH_RE = re.compile(r'data_health_(\d{8})\.md$')


def _today_str():
    return datetime.now().strftime('%Y%m%d')


def _fmt(value, suffix=''):
    if value is None:
        return 'N/A'
    return f'{value}{suffix}'


def _parse_int(text, key):
    m = re.search(rf'{key}\s*=\s*(\d+)', text or '')
    return int(m.group(1)) if m else None


def _parse_float(text, key):
    m = re.search(rf'{key}\s*=\s*([\d.]+)', text or '')
    return float(m.group(1)) if m else None


def _parse_date(text, key):
    m = re.search(rf'{key}\s*=\s*([\d-]+)', text or '')
    return m.group(1) if m else None


# ---------------------------------------------------------------- pipeline
_RUN_START_MARK = '=== RUN START ['


def _last_run_segment(text):
    """append-only 日志可能含多次运行；只分析最后一段。旧日志无 RUN START 时整段分析。"""
    if _RUN_START_MARK not in text:
        return text
    parts = text.split(_RUN_START_MARK)
    # 最后一段是最近一次运行（空段说明刚启动，视为无终态）
    return parts[-1] if parts else text


def _classify_log(text, date_str, today_str):
    segment = _last_run_segment(text)

    # 按“最后出现的终态标记”分类；append 后同一天多次运行以最后一次为准
    markers = [
        ('skipped_non_trading', '[SKIP] 非交易日'),
        ('failed', '[FATAL]'),
        ('success', 'Pipeline complete'),
        ('success', '[ALPHA-GATE] PAUSED'),
        ('interrupted', '^C'),
    ]
    last_pos, last_state = -1, None
    for state, marker in markers:
        pos = segment.rfind(marker)
        if pos > last_pos:
            last_pos, last_state = pos, state

    if last_state is not None:
        # 旧日志在「非交易日干净跳过」修复前，周末会以 check_trading_day FATAL 结束；
        # 这些不是交易日执行失败，按 skip 计。
        if last_state == 'failed' and date_str and date_str != today_str:
            try:
                dt = datetime.strptime(date_str, '%Y%m%d')
                if dt.weekday() >= 5:
                    return 'skipped_non_trading'
            except ValueError:
                pass
        return last_state

    # 无终态标记：今天 = 正在跑；更早 = 失败（截断/被强杀但没留下 ^C）
    return 'in_progress' if date_str == today_str else 'failed'


def compute_pipeline_metrics(logs_dir=LOGS_DIR, today_str=None, limit=RECENT_LOG_LIMIT):
    today_str = today_str or _today_str()
    out = {
        'name': '流水线成功率', 'status': 'UNKNOWN', 'attempts': 0,
        'success': 0, 'failed': 0, 'skipped_non_trading': 0,
        'interrupted': 0, 'in_progress': 0, 'success_rate_pct': None,
        'raw_evidence': [], 'error': None,
    }
    files = [f for f in glob.glob(os.path.join(logs_dir, 'pipeline_*.log'))
             if _DATE_RE.search(os.path.basename(f))]
    if not files:
        out['error'] = '未找到 pipeline_*.log'
        return out
    files = sorted(files, reverse=True)[:limit]
    unreadable = 0
    for path in files:
        date_str = _DATE_RE.search(os.path.basename(path)).group(1)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            unreadable += 1
            out['raw_evidence'].append(f'{os.path.basename(path)}: UNREADABLE')
            continue
        state = _classify_log(text, date_str, today_str)
        if state in ('success', 'failed'):
            out[state] += 1
        elif state == 'skipped_non_trading':
            out['skipped_non_trading'] += 1
        elif state == 'interrupted':
            out['interrupted'] += 1
        else:
            out['in_progress'] += 1
        out['raw_evidence'].append(f'{os.path.basename(path)}: {state} ({date_str})')
    out['attempts'] = out['success'] + out['failed']
    if out['attempts'] > 0 and unreadable == 0:
        out['success_rate_pct'] = round(100.0 * out['success'] / out['attempts'], 2)
        out['status'] = 'OK' if out['failed'] == 0 else 'DEGRADED'
    elif unreadable:
        out['error'] = f'{unreadable} 个日志读取失败'
    return out


# ---------------------------------------------------------------- data health
def _latest_data_health(reports_dir=REPORTS_DIR):
    files = [f for f in glob.glob(os.path.join(reports_dir, 'data_health_*.md'))
             if _DATAHEALTH_RE.search(os.path.basename(f))]
    return max(files, key=lambda f: _DATAHEALTH_RE.search(os.path.basename(f)).group(1)) if files else None


def _collect_recent_trading_dates(data_dir, n=5):
    """最近 n 个已发生交易日候选（YYYYMMDD 降序）。

    来源 = data/history.csv 的日期列 ∪ data/stock_*.csv 文件名。
    这样即使某天 history 没写、但 stock 快照存在，也会被列为期望日。
    局限（已知）：若某天两个文件都没有，无法从本地还原该缺失交易日。
    """
    dates = set()
    stock_pat = re.compile(r'stock_(\d{8})\.csv$')
    for f in glob.glob(os.path.join(data_dir, 'stock_*.csv')):
        m = stock_pat.search(os.path.basename(f))
        if m:
            dates.add(m.group(1))
    hist_path = os.path.join(data_dir, 'history.csv')
    if os.path.exists(hist_path):
        try:
            import pandas as pd
            df = pd.read_csv(hist_path, usecols=['日期'], dtype={'日期': str})
            for raw in df['日期'].dropna().astype(str):
                for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
                    try:
                        dates.add(datetime.strptime(raw[:10] if len(raw) >= 10 else raw, fmt).strftime('%Y%m%d'))
                        break
                    except ValueError:
                        continue
        except Exception:
            pass  # pandas 不可用/文件损坏：仍可用 stock 文件名
    return sorted(dates, reverse=True)[:n]


def _count_csv_rows(path):
    """普通 CSV 行数（不含表头）；读取失败返回 None。"""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return None


def compute_data_coverage(data_dir=DATA_DIR, window=5):
    """逐交易日覆盖：最近 window 个实际交易日，stock_*.csv 是否存在且行数达标。"""
    out = {
        'name': '数据覆盖（最近交易日）', 'status': 'UNKNOWN',
        'expected_days': [], 'covered_days': [], 'missing_days': [],
        'coverage_pct': None, 'raw_evidence': [], 'error': None,
    }
    expected = _collect_recent_trading_dates(data_dir, n=window)
    if not expected:
        out['error'] = '无法确定最近交易日（history.csv 与 stock_*.csv 均缺失）'
        return out
    out['expected_days'] = expected

    try:
        sys.path.insert(0, BASE_DIR)
        from core.config import get as cfg_get
        min_rows = int(cfg_get('data_validation.min_stock_rows', DEFAULT_MIN_STOCK_ROWS))
    except Exception:
        min_rows = DEFAULT_MIN_STOCK_ROWS

    for day in expected:
        path = os.path.join(data_dir, f'stock_{day}.csv')
        rows = _count_csv_rows(path)
        evidence = f'{day}: rows={rows} (min={min_rows})'
        if rows is not None and rows >= min_rows:
            out['covered_days'].append(day)
            out['raw_evidence'].append(evidence + ' OK')
        else:
            out['missing_days'].append(day)
            out['raw_evidence'].append(evidence + ' MISSING')
    out['coverage_pct'] = round(100.0 * len(out['covered_days']) / len(expected), 2)
    if out['coverage_pct'] >= 100:
        out['status'] = 'OK'
    elif out['coverage_pct'] >= 80:
        out['status'] = 'DEGRADED'
    else:
        out['status'] = 'FAIL'
    return out


def compute_data_completeness(reports_dir=REPORTS_DIR, data_dir=DATA_DIR):
    out = {
        'name': '数据完整率', 'status': 'UNKNOWN', 'source': None,
        'rows': None, 'nonzero_price_ratio': None, 'nonempty_volume_ratio': None,
        'latest_date': None, 'lag_days': None, 'multi_vote_count': None,
        'completeness_pct': None, 'rows_ok': None, 'lag_days_ok': None,
        'coverage_pct': None, 'coverage_expected_days': [],
        'coverage_missing_days': [], 'raw_evidence': [], 'error': None,
    }
    path = _latest_data_health(reports_dir)
    if not path:
        out['error'] = '未找到 data_health_*.md'
        return out
    out['source'] = os.path.basename(path)
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError as exc:
        out['error'] = f'读取失败: {exc}'
        return out

    lines = text.splitlines()
    stock_line = next((l for l in lines if 'stock_csv' in l.lower()), None)
    hist_line = next((l for l in lines if 'history_csv' in l.lower()), None)
    vote_line = next((l for l in lines if 'multi_vote' in l.lower()), None)
    for l in (stock_line, hist_line, vote_line):
        if l:
            out['raw_evidence'].append(l.strip())

    rows = _parse_int(stock_line, 'rows')
    nonzero = _parse_float(stock_line, 'nonzero_price_ratio')
    volume = _parse_float(stock_line, 'nonempty_volume_ratio')
    latest_date = _parse_date(hist_line, 'latest_date')
    lag_days = _parse_int(hist_line, 'lag_days')
    vote_count = _parse_int(vote_line, 'count')

    out.update(rows=rows, nonzero_price_ratio=nonzero,
               nonempty_volume_ratio=volume, latest_date=latest_date,
               lag_days=lag_days, multi_vote_count=vote_count)

    if nonzero is not None and volume is not None:
        out['completeness_pct'] = round(100.0 * (nonzero * 0.6 + volume * 0.4), 2)

    # 从 system_config 读真实阈值（失败用默认）
    try:
        sys.path.insert(0, BASE_DIR)
        from core.config import get as cfg_get
        min_rows = int(cfg_get('data_validation.min_stock_rows', DEFAULT_MIN_STOCK_ROWS))
        max_lag = int(cfg_get('data_validation.max_history_lag_days', MAX_HISTORY_LAG_DAYS))
    except Exception:
        min_rows, max_lag = DEFAULT_MIN_STOCK_ROWS, MAX_HISTORY_LAG_DAYS

    if rows is not None:
        out['rows_ok'] = rows >= min_rows
    if lag_days is not None:
        out['lag_days_ok'] = lag_days <= max_lag

    # 逐交易日覆盖：stock 快照文件本身是否齐全（与 data_health 报告是否生成解耦）
    coverage = compute_data_coverage(data_dir=data_dir)
    out['coverage_pct'] = coverage['coverage_pct']
    out['coverage_expected_days'] = coverage['expected_days']
    out['coverage_missing_days'] = coverage['missing_days']
    out['raw_evidence'] += coverage['raw_evidence']
    cov_status = coverage['status']
    cov_pct = coverage['coverage_pct']

    pct = out['completeness_pct']
    snapshot_status = 'UNKNOWN'
    if pct is None or rows is None or lag_days is None:
        snapshot_status = 'UNKNOWN'
    elif out['rows_ok'] is False or out['lag_days_ok'] is False or pct < COMPLETENESS_DEGRADED:
        snapshot_status = 'FAIL'
    elif pct < COMPLETENESS_OK:
        snapshot_status = 'DEGRADED'
    else:
        snapshot_status = 'OK'

    # 融合：快照与覆盖都 OK 才 OK；任一方 UNKNOWN 则 UNKNOWN；否则取更差一档
    if snapshot_status == 'UNKNOWN' or cov_status == 'UNKNOWN':
        out['status'] = 'UNKNOWN'
    elif 'FAIL' in (snapshot_status, cov_status):
        out['status'] = 'FAIL'
    elif 'DEGRADED' in (snapshot_status, cov_status):
        out['status'] = 'DEGRADED'
    else:
        out['status'] = 'OK'
    return out


# ---------------------------------------------------------------- self check
def compute_self_check_pass_rate(reports_dir=REPORTS_DIR):
    out = {
        'name': '测试/自检通过率', 'status': 'UNKNOWN', 'source': None,
        'passed': None, 'total': None, 'pass_rate_pct': None,
        'raw_evidence': [], 'error': None,
    }
    path = os.path.join(reports_dir, 'system_self_check_v86.json')
    out['source'] = os.path.basename(path)
    if not os.path.exists(path):
        out['error'] = 'system_self_check_v86.json 不存在'
        return out
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        score = data.get('score', {})
        passed, total = score.get('passed'), score.get('total')
        if passed is None or total is None or total <= 0:
            out['error'] = 'score.passed/total 缺失'
            return out
        passed, total = int(passed), int(total)
        out.update(passed=passed, total=total,
                   pass_rate_pct=round(100.0 * passed / total, 2), status='OK')
        out['raw_evidence'].append(f'score.passed={passed}, score.total={total}')
    except Exception as exc:
        out['error'] = f'JSON 解析失败: {exc}'
    return out


# ---------------------------------------------------------------- report
def build_report(logs_dir=LOGS_DIR, reports_dir=REPORTS_DIR, data_dir=DATA_DIR, date_str=None):
    date_str = date_str or _today_str()
    metrics = {
        'pipeline_success_rate': compute_pipeline_metrics(logs_dir, date_str),
        'data_completeness': compute_data_completeness(reports_dir, data_dir),
        'self_check_pass_rate': compute_self_check_pass_rate(reports_dir),
    }
    conclusion = (
        f"流水线成功率 {_fmt(metrics['pipeline_success_rate']['success_rate_pct'], '%')}"
        f"（{metrics['pipeline_success_rate']['status']}）；"
        f"数据完整率 {_fmt(metrics['data_completeness']['completeness_pct'], '%')}"
        f"（{metrics['data_completeness']['status']}）；"
        f"自检通过率 {_fmt(metrics['self_check_pass_rate']['pass_rate_pct'], '%')}"
        f"（{metrics['self_check_pass_rate']['status']}）"
    )
    return {'date': date_str, 'metrics': metrics, 'conclusion': conclusion}


def render_markdown(report):
    m = report['metrics']
    p, d, s = m['pipeline_success_rate'], m['data_completeness'], m['self_check_pass_rate']
    lines = [
        f"# 目标验收指标 — {report['date']}",
        "",
        "## 1. 流水线成功率（最近 20 个有终态交易日运行；非交易日 skip 不计分母）",
        f"- 状态：{p['status']}",
        f"- attempts={p['attempts']} | success={p['success']} | failed={p['failed']}"
        f" | skipped_non_trading={p['skipped_non_trading']}"
        f" | interrupted={p['interrupted']} | in_progress={p['in_progress']}",
        f"- success_rate={_fmt(p['success_rate_pct'], '%')}",
    ]
    if p['error']:
        lines.append(f"- error：{p['error']}")
    lines.append("- 最近日志：")
    lines += [f"  - {ev}" for ev in p['raw_evidence'][-10:]] or ['  - 无']
    lines += [
        "",
        "## 2. 数据完整率（最新 data_health 快照）",
        f"- 状态：{d['status']} | 来源：{_fmt(d['source'])}",
        f"- stock rows={_fmt(d['rows'])} | nonzero_price_ratio={_fmt(d['nonzero_price_ratio'])}"
        f" | nonempty_volume_ratio={_fmt(d['nonempty_volume_ratio'])}",
        f"- history latest={_fmt(d['latest_date'])} | lag_days={_fmt(d['lag_days'])}",
        f"- multi_vote count={_fmt(d['multi_vote_count'])}",
        f"- completeness_pct={_fmt(d['completeness_pct'], '%')}"
        f" | rows_ok={_fmt(d['rows_ok'])} | lag_days_ok={_fmt(d['lag_days_ok'])}",
        f"- coverage_pct={_fmt(d['coverage_pct'], '%')}"
        f" | expected={','.join(d['coverage_expected_days']) or 'N/A'}"
        f" | missing={','.join(d['coverage_missing_days']) or '无'}",
        "",
        "## 3. 测试/自检通过率（每日代理指标）",
        f"- 状态：{s['status']} | 来源：{_fmt(s['source'])}",
        f"- passed={_fmt(s['passed'])} | total={_fmt(s['total'])}"
        f" | pass_rate={_fmt(s['pass_rate_pct'], '%')}",
        "",
        "## 结论",
        report['conclusion'],
        "",
    ]
    return '\n'.join(lines)


def write_report(report, reports_dir=REPORTS_DIR):
    os.makedirs(reports_dir, exist_ok=True)
    md_path = os.path.join(reports_dir, f"goal_metrics_{report['date']}.md")
    json_path = os.path.join(reports_dir, f"goal_metrics_{report['date']}.json")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(render_markdown(report))
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return md_path, json_path


def main():
    # 脚本自身永远以成功退出：指标报告本身允许 UNKNOWN，但脚本失败不能阻断流水线
    try:
        report = build_report()
        md_path, json_path = write_report(report)
        print(report['conclusion'])
        print(md_path)
        print(json_path)
    except Exception as exc:
        print(f'[goal_metrics] degraded (non-fatal): {exc}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
