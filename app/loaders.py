import os, glob, re, subprocess, shlex, sys, json
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


def _pipeline_python():
    """流水线子进程解释器：优先 QUANT_PYTHON 环境变量，否则用当前解释器。

    不再写死机器路径——换机器/换 venv 都能跑，且与 core.pipeline._python() 口径一致。
    """
    return os.environ.get("QUANT_PYTHON") or sys.executable

@st.cache_data(ttl=60)
def load_latest_picks():
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'pick_*.md')), reverse=True)
    if not files:
        return None, None, None
    latest = files[0]
    date_match = re.search(r'pick_(\d{8})', os.path.basename(latest))
    pick_date = date_match.group(1) if date_match else '未知'
    with open(latest, 'r', encoding='utf-8') as f:
        content = f.read()
    stocks = []
    for line in content.split('\n'):
        if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 8:
                # v8.6: 兼容新老表头 — 老13列(无板块)/新14列(有板块)
                # parts[3] 能转 float 即老格式（最新价）；否则新格式（板块），偏移 +1
                try:
                    float(parts[3])
                    o = 0  # 老格式偏移
                except ValueError:
                    o = 1  # 新格式：板块占位 parts[3]，最新价后移到 parts[4]
                try:
                    stocks.append({
                        '排名': int(parts[0]), '代码': parts[1], '名称': parts[2],
                        '最新价': float(parts[3 + o]),
                        '涨跌幅': float(parts[4 + o]) if parts[4 + o] != '0.00' else 0.0,
                        'MA5': float(parts[5 + o]), 'MA20': float(parts[6 + o]),
                        'RSI': float(parts[7 + o]),
                        '量比': float(parts[8 + o]) if len(parts) > 8 + o else 0,
                        '市值亿': float(parts[9 + o]) if len(parts) > 9 + o else 0,
                        '评分': int(parts[10 + o]) if len(parts) > 10 + o else 0,
                        '风险': parts[11 + o] if len(parts) > 11 + o else '-',
                        '选入理由': parts[12 + o] if len(parts) > 12 + o else '-',
                    })
                except (ValueError, IndexError):
                    continue
    return pd.DataFrame(stocks), pick_date, latest


@st.cache_data(ttl=600)


def load_index_data():
    f = os.path.join(DATA_DIR, 'hs300_index.csv')
    if not os.path.exists(f):
        return None
    df = pd.read_csv(f)
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期')
    df['MA20'] = df['收盘'].rolling(20).mean()
    df['MA5'] = df['收盘'].rolling(5).mean()
    df['ret'] = df['收盘'].pct_change()
    return df




def load_evaluation():
    f = os.path.join(RESULTS_DIR, 'honest_evaluation.md')
    if not os.path.exists(f):
        return None
    with open(f, 'r', encoding='utf-8') as fh:
        return fh.read()




def load_daily_insight():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'daily_insight_*.md')), reverse=True)
    if not files:
        files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'ab_test_*.md')), reverse=True)
    if not files:
        return None
    with open(files[0], 'r', encoding='utf-8') as f:
        return f.read()[:3000]




def run_pipeline_step(script, label, timeout=300):
    """执行一个流水线步骤。

    script 支持三种形式：
      - 'strategy.py'                         无参数
      - 'research_agent.py --daily "标题"'    带参数字符串（shlex 拆分，修复旧版整串当脚本名导致 FileNotFoundError 的 bug）
      - ['research_agent.py', '--daily', 't'] 参数列表
    超时会强制终止子进程（修复旧版 TimeoutExpired 后子进程继续孤儿运行的 bug）。
    """
    if isinstance(script, (list, tuple)):
        args = [str(a) for a in script]
    else:
        args = shlex.split(str(script))
    if not args:
        return False, "空命令"
    cmd = [_pipeline_python()] + args
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=BASE_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
        )
        out, err = proc.communicate(timeout=timeout)
        tail = ((out or "") + (err or "")).strip()[-500:]
        return proc.returncode == 0, tail
    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                proc.kill()
                proc.communicate()
            except Exception:
                pass
        return False, f"超时（>{timeout // 60}分钟），已终止该步骤"
    except Exception as e:
        return False, str(e)


@st.cache_data(ttl=300)
def load_all_system_picks():
    pick_files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'pick_*.md')))
    all_records = []
    for pf in pick_files:
        dm = re.search(r'pick_(\d{8})', os.path.basename(pf))
        if not dm:
            continue
        pdate = dm.group(1)
        with open(pf, 'r', encoding='utf-8') as fh:
            pcontent = fh.read()
        for line in pcontent.split('\n'):
            if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) < 7:
                    continue
                try:
                    code = parts[1]
                    name = parts[2]
                    try:
                        price = float(parts[3])
                    except ValueError:
                        price = float(parts[4]) if len(parts) > 4 else 0.0
                    all_records.append({
                        '选股日期': pdate, '代码': code, '名称': name, '入场价': price
                    })
                except (ValueError, IndexError):
                    continue
    return pd.DataFrame(all_records) if all_records else pd.DataFrame()


@st.cache_data(ttl=300)
def load_current_prices():
    stock_files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not stock_files:
        return {}
    df = pd.read_csv(stock_files[0], dtype={'代码': str})
    prices = {}
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        prices[code] = {
            'name': str(row.get('名称', '')),
            'price': float(row.get('最新价', 0)),
        }
    return prices




