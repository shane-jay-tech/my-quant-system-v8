"""
数据健康校验 v1 — 在 fetch 之后立即跑，脏数据 WARN（默认不阻流水线）

检查项：
1. stock_*.csv：行数 ≥ 4000、非零价比例 ≥ 99%、非空成交量 ≥ 95%
2. history.csv：日期连续性、最新日期 ≥ today - 5 日
3. multi_vote_*.json / orders/*.json：基本字段存在性

Why: 没有 validation 时 fetch 拿到脏数据（API 故障/限流/格式变更）会让下游全错乱、无人报警；
本模块作为流水线早期 sanity check。

输出: reports/data_health_YYYYMMDD.md
"""
import os
import sys
import glob
import json
import pandas as pd
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION


def check_stock_csv():
    """检查最新 stock_YYYYMMDD.csv"""
    files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not files:
        return {'status': 'FAIL', 'reason': 'no stock_*.csv files', 'metrics': {}}
    latest = files[0]
    try:
        df = pd.read_csv(latest, dtype={'代码': str})
    except Exception as e:
        return {'status': 'FAIL', 'reason': f'read failed: {e}', 'metrics': {}}

    metrics = {'file': os.path.basename(latest), 'rows': len(df)}

    min_rows = cfg_get('data_validation.min_stock_rows', 4000)
    if len(df) < min_rows:
        return {'status': 'FAIL', 'reason': f'row count {len(df)} < min {min_rows}', 'metrics': metrics}

    price_col = '最新价' if '最新价' in df.columns else '收盘'
    if price_col in df.columns:
        nonzero_ratio = (df[price_col] > 0).mean()
        metrics['nonzero_price_ratio'] = round(nonzero_ratio, 4)
        min_nonzero = cfg_get('data_validation.min_nonzero_price_pct', 0.99)
        if nonzero_ratio < min_nonzero:
            return {'status': 'WARN', 'reason': f'nonzero price {nonzero_ratio:.2%} < {min_nonzero:.0%}', 'metrics': metrics}
    else:
        return {'status': 'FAIL', 'reason': f'no price column', 'metrics': metrics}

    if '成交量' in df.columns:
        vol_nonempty = df['成交量'].notna().mean()
        metrics['nonempty_volume_ratio'] = round(vol_nonempty, 4)
        min_vol = cfg_get('data_validation.min_nonempty_volume_pct', 0.95)
        if vol_nonempty < min_vol:
            return {'status': 'WARN', 'reason': f'volume nonempty {vol_nonempty:.2%} < {min_vol:.0%}', 'metrics': metrics}

    return {'status': 'OK', 'reason': '', 'metrics': metrics}


def check_history_csv():
    """检查 history.csv 的连续性与新鲜度"""
    f = os.path.join(DATA_DIR, 'history.csv')
    if not os.path.exists(f):
        return {'status': 'FAIL', 'reason': 'history.csv missing', 'metrics': {}}
    try:
        df = pd.read_csv(f, dtype={'代码': str})
        df['日期'] = pd.to_datetime(df['日期'])
    except Exception as e:
        return {'status': 'FAIL', 'reason': f'read failed: {e}', 'metrics': {}}

    metrics = {'rows': len(df), 'unique_codes': df['代码'].nunique()}
    latest_date = df['日期'].max().date()
    metrics['latest_date'] = latest_date.isoformat()

    today = date.today()
    lag_days = (today - latest_date).days
    metrics['lag_days'] = lag_days

    max_lag = cfg_get('data_validation.max_history_lag_days', 5)
    if lag_days > max_lag:
        return {'status': 'WARN', 'reason': f'history lag {lag_days} days > {max_lag}', 'metrics': metrics}

    return {'status': 'OK', 'reason': '', 'metrics': metrics}


def check_multi_vote():
    """检查最新 multi_vote_*.json 字段完整性"""
    files = sorted(glob.glob(os.path.join(BASE_DIR, 'orders', 'multi_vote_*.json')), reverse=True)
    if not files:
        return {'status': 'WARN', 'reason': 'no multi_vote files yet', 'metrics': {}}
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            votes = json.load(f)
    except Exception as e:
        return {'status': 'FAIL', 'reason': f'read failed: {e}', 'metrics': {}}

    metrics = {'file': os.path.basename(files[0]), 'count': len(votes)}
    if not votes:
        return {'status': 'WARN', 'reason': 'multi_vote empty', 'metrics': metrics}

    required = {'代码', '名称', '最新价', '最终得分'}
    sample = votes[0]
    missing = required - set(sample.keys())
    if missing:
        return {'status': 'FAIL', 'reason': f'missing fields: {missing}', 'metrics': metrics}

    return {'status': 'OK', 'reason': '', 'metrics': metrics}


def write_report(results):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')
    path = os.path.join(REPORTS_DIR, f'data_health_{today_str}.md')

    lines = [
        f"# 数据健康检查 — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| 检查项 | 状态 | 原因/Metrics |",
        "|--------|------|--------------|",
    ]
    for name, r in results.items():
        icon = {'OK': '✅', 'WARN': '⚠️', 'FAIL': '❌'}.get(r['status'], '❓')
        m = r.get('metrics', {})
        m_str = ' '.join(f'{k}={v}' for k, v in m.items())
        reason_or_metrics = (r['reason'] + ' | ' + m_str) if r['reason'] else m_str
        lines.append(f"| {name} | {icon} {r['status']} | {reason_or_metrics} |")

    overall = 'FAIL' if any(r['status'] == 'FAIL' for r in results.values()) else (
              'WARN' if any(r['status'] == 'WARN' for r in results.values()) else 'OK')
    lines.extend(["", f"## 总体：{overall}", "", "---", f"*由 data_validator.py v{SYSTEM_VERSION} 自动生成*"])

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path, overall


def main():
    print(f"{'='*50}")
    print(f"  数据健康检查 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    results = {
        'stock_csv': check_stock_csv(),
        'history_csv': check_history_csv(),
        'multi_vote': check_multi_vote(),
    }

    # ASCII-only console print（emoji 仅在写入的 markdown 文件中保留）
    for name, r in results.items():
        prefix = {'OK': '[OK]', 'WARN': '[WARN]', 'FAIL': '[FAIL]'}.get(r['status'], '[?]')
        print(f"  {prefix} {name}: {r['status']} {('('+r['reason']+')') if r['reason'] else ''}")

    path, overall = write_report(results)
    print(f"\n[VALIDATOR] Report: {path}")
    print(f"[VALIDATOR] Overall: {overall}")

    fail_on_invalid = cfg_get('data_validation.fail_on_invalid', False)
    if overall == 'FAIL' and fail_on_invalid:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
