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


def parse_pick_line(parts):
    """统一解析 pick_*.md 表格行（v8.7 审查重构：三处重复逻辑收敛到一处）。

    兼容 v8.6 新老表头：老 13 列（无板块），新 14 列（parts[3]=板块，最新价后移到 parts[4]）。
    parts 是 split('|') 后 strip 过的非空列表。解析失败返回 None。
    """
    if len(parts) < 8:
        return None
    try:
        float(parts[3])
        o = 0  # 老格式：parts[3] 是最新价
    except (ValueError, TypeError):
        o = 1  # 新格式：parts[3] 是板块
    try:
        return {
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
        }
    except (ValueError, IndexError):
        return None


@st.cache_data(ttl=60)
def load_latest_picks():
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'pick_*.md')), reverse=True)
    if not files:
        return None, None, None
    latest = files[0]
    date_match = re.search(r'pick_(\d{8})', os.path.basename(latest))
    pick_date = date_match.group(1) if date_match else '未知'
    try:
        with open(latest, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as exc:
        st.warning(f"选股报告读取失败：{exc}")
        return None, pick_date, latest
    stocks = []
    for line in content.split('\n'):
        if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            row = parse_pick_line(parts)
            if row:
                stocks.append(row)
    return pd.DataFrame(stocks), pick_date, latest


@st.cache_data(ttl=600)
def load_index_data():
    f = os.path.join(DATA_DIR, 'hs300_index.csv')
    if not os.path.exists(f):
        return None
    try:
        df = pd.read_csv(f)
    except Exception as exc:
        st.warning(f"沪深300 指数数据读取失败：{exc}")
        return None
    if df is None or len(df) < 2 or '日期' not in df.columns or '收盘' not in df.columns:
        st.warning("沪深300 指数数据不足（空文件或缺少日期/收盘列）")
        return None
    try:
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        df['MA20'] = df['收盘'].rolling(20).mean()
        df['MA5'] = df['收盘'].rolling(5).mean()
        df['ret'] = df['收盘'].pct_change()
        return df
    except Exception as exc:
        st.warning(f"沪深300 指标计算失败：{exc}")
        return None


@st.cache_data(ttl=60)
def load_evaluation():
    f = os.path.join(RESULTS_DIR, 'honest_evaluation.md')
    if not os.path.exists(f):
        return None
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            return fh.read()
    except Exception:
        return None


def parse_honest_eval_md(text):
    """解析 honest_evaluation.md 的核心指标/牛熊/超额收益（v8.7 修复：按表头列名解析，
    不再用易碎正则——旧正则在 '| 持有 | 交易数 | 胜率 | 毛收益 | 净收益 | 死叉出场 |' 格式下全部匹配不到）。

    返回 {'periods': {'1日': {...}}, 'bull': {...}|None, 'bear': {...}|None, 'excess': float|None}
    """
    out = {'periods': {}, 'bull': None, 'bear': None, 'excess': None}
    if not text:
        return out
    in_core = False

    def _num(s):
        try:
            return float(str(s).replace('%', '').replace('+', '').strip())
        except (ValueError, AttributeError):
            return None

    for line in text.splitlines():
        if line.startswith('## 核心指标'):
            in_core = True
            continue
        if in_core and line.startswith('## '):
            in_core = False
            continue
        if re.match(r'^\|\s*(1日|5日|10日)\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 6:
                out['periods'][parts[0]] = {
                    '交易数': int(_num(parts[1]) or 0),
                    '胜率': _num(parts[2]),
                    '毛收益': _num(parts[3]),
                    '净收益': _num(parts[4]),
                    '死叉出场': _num(parts[5]),
                }
        if re.match(r'^\|\s*牛市\s*\|', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 4:
                out['bull'] = {'笔数': int(_num(parts[1]) or 0), '胜率': _num(parts[2]), '净收益': _num(parts[3])}
        if re.match(r'^\|\s*熊市', line):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 4:
                out['bear'] = {'笔数': int(_num(parts[1]) or 0), '胜率': _num(parts[2]), '净收益': _num(parts[3])}
        m = re.search(r'\*\*超额收益\*\*\s*:\s*([+-]?\d+\.?\d*)%', line)
        if m:
            out['excess'] = float(m.group(1))
    return out


def load_latest_digest():
    """读取最新开盘前简报（digest.py 生成），无则返回 None。"""
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'digest_*.md')), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


@st.cache_data(ttl=60)
def load_daily_insight():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'daily_insight_*.md')), reverse=True)
    if not files:
        files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'ab_test_*.md')), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            return f.read()[:3000]
    except Exception:
        return None


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
        try:
            with open(pf, 'r', encoding='utf-8') as fh:
                pcontent = fh.read()
        except Exception:
            continue
        for line in pcontent.split('\n'):
            if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
                parts = [p.strip() for p in line.split('|') if p.strip()]
                row = parse_pick_line(parts)
                if row:
                    all_records.append({
                        '选股日期': pdate, '代码': row['代码'], '名称': row['名称'], '入场价': row['最新价'],
                    })
    return pd.DataFrame(all_records) if all_records else pd.DataFrame()


@st.cache_data(ttl=300)
def load_current_prices():
    stock_files = sorted(glob.glob(os.path.join(DATA_DIR, 'stock_*.csv')), reverse=True)
    if not stock_files:
        return {}
    try:
        df = pd.read_csv(stock_files[0], dtype={'代码': str})
    except Exception as exc:
        st.warning(f"行情文件读取失败：{exc}")
        return {}
    if df is None or df.empty or '代码' not in df.columns:
        return {}
    # v8.7 审查优化：去掉逐行 iterrows，向量化构建字典
    df = df.assign(_code=df['代码'].astype(str).str.zfill(6))
    name = df.get('名称', pd.Series('', index=df.index)).astype(str)
    price = pd.to_numeric(df.get('最新价', pd.Series(0, index=df.index)), errors='coerce').fillna(0.0)
    return {
        code: {'name': str(n), 'price': float(p)}
        for code, n, p in zip(df['_code'], name, price)
    }
