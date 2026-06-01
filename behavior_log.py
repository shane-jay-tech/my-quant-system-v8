"""
行为日志系统 v1 — 量化用户的损失厌恶/过度交易/确认偏误等决策偏差

数据格式（data/behavior_log.csv）：
日期, 系统推荐(JSON), 用户实际(JSON), deviation_type, deviation_count, 备注

deviation_type:
- "全执行"      : 系统推荐的全部下单，且数量价格一致
- "拒绝执行"    : 系统推荐 N 只但用户实际下单 < N 只
- "自主决策"    : 用户下单了系统未推荐的票
- "数量调整"    : 票一致但股数偏离 > 10%
- "未操作"      : 系统推荐但用户当日完全没下单
- "无推荐+无操作": 系统因 regime 等原因未推荐 → 用户也未操作（合规）
- "无推荐+自主" : 系统未推荐但用户自己下单（信号外交易）

设计：
- 系统推荐部分由 daily_pipeline 末尾自动写入（读最新 daily_orders）
- 用户实际下单部分由 log_real_trade.py 写 real_trades.csv 后，本模块读取并合并
- deviation 由本模块自动计算

供月度报告 monthly_behavior_report.py 消费
"""
import os
import sys
import json
import glob
import csv
import pandas as pd
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
LOG_FILE = os.path.join(DATA_DIR, 'behavior_log.csv')

sys.path.insert(0, BASE_DIR)
from core.config import get as cfg_get, SYSTEM_VERSION


def _read_log():
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame(columns=['日期', '系统推荐', '用户实际', 'deviation_type', 'deviation_count', '备注'])
    try:
        return pd.read_csv(LOG_FILE, encoding='utf-8-sig', dtype={'日期': str})
    except Exception as e:
        print(f"[BEHAVIOR] read failed: {e}; resetting")
        return pd.DataFrame(columns=['日期', '系统推荐', '用户实际', 'deviation_type', 'deviation_count', '备注'])


def _write_log(df):
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(LOG_FILE, index=False, encoding='utf-8-sig')


def load_latest_recommendations():
    """从最新 daily_orders 读出系统推荐"""
    files = sorted(glob.glob(os.path.join(ORDERS_DIR, 'daily_orders_*.json')), reverse=True)
    if not files:
        return None, []
    # 文件名提取日期
    fname = os.path.basename(files[0])
    date_str = fname.replace('daily_orders_', '').replace('.json', '')
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None, []
    orders = data.get('订单', []) if isinstance(data, dict) else data
    recs = []
    for o in orders:
        recs.append({
            'code': str(o.get('代码', '')).zfill(6),
            'name': o.get('名称', ''),
            'price': float(o.get('价格', 0)),
            'shares': int(o.get('股数', 0)),
            'amount': float(o.get('金额', 0)),
        })
    return date_str, recs


def load_user_actuals(target_date):
    """从 real_trades.csv 读 target_date 当日的实际下单

    Args:
        target_date: 'YYYYMMDD' or 'YYYY-MM-DD'
    """
    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if not os.path.exists(real_file):
        return []

    try:
        df = pd.read_csv(real_file, dtype={'代码': str})
    except Exception:
        return []

    # 标准化日期匹配
    norm = target_date.replace('-', '')
    if '日期' not in df.columns:
        return []
    df['_date_norm'] = df['日期'].astype(str).str.replace('-', '').str[:8]
    if '备注' in df.columns:
        df = df[~df['备注'].astype(str).str.contains('示例数据', na=False)]
    today_df = df[df['_date_norm'] == norm]

    actuals = []
    for _, row in today_df.iterrows():
        actuals.append({
            'code': str(row.get('代码', '')).zfill(6),
            'name': row.get('名称', ''),
            'direction': row.get('方向', '买入'),
            'price': float(row.get('价格', 0)),
            'shares': int(row.get('数量', 0) or row.get('股数', 0)),
        })
    return actuals


def classify_deviation(recs, actuals):
    """按规则分类用户行为相对系统推荐的偏离

    Returns: (deviation_type, deviation_count, detail_dict)
    """
    rec_codes = {r['code'] for r in recs}
    actual_buy = [a for a in actuals if a.get('direction') == '买入']
    act_codes = {a['code'] for a in actual_buy}

    # 子集划分
    only_in_rec = rec_codes - act_codes  # 系统推荐但用户没买
    only_in_act = act_codes - rec_codes  # 用户买了但系统没推
    both = rec_codes & act_codes

    detail = {
        '推荐数': len(rec_codes),
        '实际买入数': len(act_codes),
        '推荐但未买': sorted(only_in_rec),
        '系统未推但买': sorted(only_in_act),
        '推荐且买': sorted(both),
    }

    if not rec_codes and not act_codes:
        return '无推荐+无操作', 0, detail
    if not rec_codes and act_codes:
        return '无推荐+自主', len(act_codes), detail
    if rec_codes and not act_codes:
        return '未操作', len(rec_codes), detail

    # 数量调整检测
    qty_adjust = 0
    rec_map = {r['code']: r for r in recs}
    act_map = {a['code']: a for a in actual_buy}
    for code in both:
        r_qty = rec_map[code]['shares']
        a_qty = act_map[code]['shares']
        if r_qty > 0 and abs(a_qty - r_qty) / r_qty > 0.10:
            qty_adjust += 1

    if only_in_rec and not only_in_act:
        return '拒绝执行', len(only_in_rec), detail
    if only_in_act and not only_in_rec:
        return '自主决策', len(only_in_act), detail
    if only_in_rec and only_in_act:
        return '混合偏离', len(only_in_rec) + len(only_in_act), detail
    if qty_adjust > 0:
        return '数量调整', qty_adjust, detail
    return '全执行', len(both), detail


def log_today():
    """主入口：把今日的推荐 + 实际 + deviation 写入 behavior_log.csv"""
    if not cfg_get('behavior_log.enabled', True):
        print("[BEHAVIOR] disabled in config")
        return 0

    rec_date, recs = load_latest_recommendations()
    if rec_date is None:
        print("[BEHAVIOR] no recommendations found, skip")
        return 0

    # 标准化日期
    try:
        d = datetime.strptime(rec_date, '%Y%m%d').strftime('%Y-%m-%d')
    except ValueError:
        d = rec_date

    actuals = load_user_actuals(rec_date)
    dev_type, dev_count, detail = classify_deviation(recs, actuals)

    df = _read_log()
    # upsert：同一天覆盖
    df = df[df['日期'] != d]
    new_row = {
        '日期': d,
        '系统推荐': json.dumps([{'code': r['code'], 'name': r['name'], 'shares': r['shares']} for r in recs], ensure_ascii=False),
        '用户实际': json.dumps([{'code': a['code'], 'name': a['name'], 'direction': a['direction'], 'shares': a['shares']} for a in actuals], ensure_ascii=False),
        'deviation_type': dev_type,
        'deviation_count': dev_count,
        '备注': f"推荐{detail['推荐数']}只 实买{detail['实际买入数']}只",
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.sort_values('日期').reset_index(drop=True)
    _write_log(df)

    print(f"[BEHAVIOR] {d} | {dev_type} (count={dev_count}) | {new_row['备注']}")
    return 0


def main():
    print(f"{'='*50}")
    print(f"  行为日志 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")
    return log_today()


if __name__ == '__main__':
    sys.exit(main())
