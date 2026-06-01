"""
ETF 实时行情抓取（v8.6 新增）

为什么需要：用户在 real_trades.csv 里持有 159325 半导体ETF南方，但 fetch_stock_data.py
只跑 Sina 'hs_a' 节点（A 股全市场），不含任何 ETF。结果就是用户问"我半导体ETF价格
为什么没变"——下游模块拿不到 ETF 当日价，只能回退到买入价当作"无变化"。

设计：
    1. watchlist 来源：data/etf_watchlist.json + 自动从 real_trades.csv 扫出 ETF 代码
       （5xxxxx / 15xxxx / 159xxx 三类前缀）
    2. 数据源：Sina list API（一行一个，URL 拼批量代码，免分页）
    3. 输出：追加到当日 data/stock_YYYYMMDD.csv，schema 完全一致
       关键：「流通市值」字段写 0 → strategy.py MCAP_MIN > 50亿 自动过滤掉，
       不会被选股策略误当成 A 股买。下游 portfolio_manager / exit_advisor /
       trade_analyzer 读 stock_*.csv 时能正常拿到价格。

Sina list API 返回格式：
    var hq_str_sh510300="华泰柏瑞沪深300ETF,3.870,3.870,3.882,3.890,3.866,...";
    字段索引：0=名称 1=昨收 2=今开 3=最新价 4=最高 5=最低 6=买1价 7=卖1价
              8=成交量(股) 9=成交额(元) ...
"""
import os
import sys
import json
import re
import time
import random
import requests
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
WATCHLIST_PATH = os.path.join(DATA_DIR, 'etf_watchlist.json')
REAL_TRADES_PATH = os.path.join(BASE_DIR, 'real_trades.csv')

# Sina list 批量行情接口（不限页数，一次最多 ~80 只稳）
SINA_LIST_URL = 'https://hq.sinajs.cn/list='
SINA_BATCH_SIZE = 60
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.sina.com.cn/',
}


def code_to_sina_symbol(code):
    """ETF 代码 → Sina 前缀代码

    沪市 ETF: 51xxxx / 52xxxx / 56xxxx / 58xxxx / 588xxx → sh
    深市 ETF: 15xxxx / 159xxx / 16xxxx / 18xxxx       → sz
    其他（兜底当 A 股代码处理）：6 → sh, 0/3 → sz
    """
    code = str(code).zfill(6)
    if code[0] in ('5', '6'):
        return f'sh{code}'
    if code[0] in ('0', '1', '2', '3'):
        return f'sz{code}'
    if code[0] in ('8', '9'):
        return f'bj{code}'
    return f'sz{code}'


def looks_like_etf(code):
    """判断代码是否像 ETF。

    A 股代码：6xx/0xx/3xx/2xx/688/8xx/9xx
    ETF 代码：51xxxx 沪 / 159xxx 深 / 588xxx 沪 / 15xxxx 深 / 56xxxx 沪 / 16xxxx 深
    用首位字符近似判断：5 / 1 开头 → ETF。
    """
    code = str(code).zfill(6)
    return code.startswith(('5', '1'))


def load_watchlist():
    """读 etf_watchlist.json，返回 [{code, name}, ...]"""
    if not os.path.exists(WATCHLIST_PATH):
        print(f'[ETF] watchlist not found: {WATCHLIST_PATH}')
        return []
    try:
        with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('etfs', [])
    except Exception as e:
        print(f'[ETF] watchlist parse error: {e}')
        return []


def extract_etfs_from_real_trades():
    """从 real_trades.csv 扫出 ETF 代码，返回 set."""
    if not os.path.exists(REAL_TRADES_PATH):
        return set()
    try:
        df = pd.read_csv(REAL_TRADES_PATH, dtype={'代码': str})
        df['代码'] = df['代码'].astype(str).str.zfill(6)
        return {c for c in df['代码'].unique() if looks_like_etf(c)}
    except Exception as e:
        print(f'[ETF] real_trades scan error (non-fatal): {e}')
        return set()


def merge_codes_from_sources():
    """合并 watchlist + real_trades 的 ETF 代码（保序去重）。"""
    watchlist = load_watchlist()
    seen = set()
    merged = []
    for item in watchlist:
        code = str(item.get('code', '')).zfill(6)
        if not code or code in seen:
            continue
        seen.add(code)
        merged.append({'code': code, 'name': item.get('name', '')})

    extra_codes = extract_etfs_from_real_trades()
    for code in sorted(extra_codes):
        if code not in seen:
            seen.add(code)
            merged.append({'code': code, 'name': ''})  # 名称用 Sina 返回的覆盖
    return merged


def fetch_sina_batch(codes, max_retries=3):
    """批量拉一批 ETF（≤60 只）。返回 dict {code: row_dict} 或空 dict."""
    if not codes:
        return {}
    symbols = [code_to_sina_symbol(c) for c in codes]
    url = SINA_LIST_URL + ','.join(symbols)
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(0.3, 0.8))
            resp = requests.get(url, headers=SINA_HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f'[ETF] HTTP {resp.status_code} on batch (attempt {attempt+1})')
                time.sleep(2 ** (attempt + 1))
                continue
            # Sina 返回 GBK 编码（即使 utf-8 客户端要 decode）
            try:
                resp.encoding = 'gbk'
                text = resp.text
            except Exception:
                text = resp.content.decode('gbk', errors='replace')
            return _parse_sina_list(text, codes)
        except Exception as e:
            print(f'[ETF] batch error (attempt {attempt+1}): {e}')
            time.sleep(2 ** (attempt + 1))
    return {}


_LIST_LINE_RE = re.compile(r'var\s+hq_str_(\w+)="([^"]*)"')


def _parse_sina_list(text, original_codes):
    """解析 Sina list 响应文本。返回 {6位代码: row_dict}."""
    by_code = {}
    code_set = {str(c).zfill(6) for c in original_codes}

    for m in _LIST_LINE_RE.finditer(text):
        symbol = m.group(1)        # 'sh510300'
        payload = m.group(2)       # CSV 字段
        if not payload or len(symbol) < 8:
            continue
        code6 = symbol[2:].zfill(6)
        if code6 not in code_set:
            continue

        parts = payload.split(',')
        if len(parts) < 10:
            # ETF 接口偶尔字段不全（停牌/退市）→ 跳过但不报错
            continue
        try:
            name = parts[0]
            prev_close = float(parts[1] or 0)
            latest = float(parts[3] or 0)
            high = float(parts[4] or 0)
            low = float(parts[5] or 0)
            volume = float(parts[8] or 0)   # 单位：股
            amount = float(parts[9] or 0)   # 单位：元
        except ValueError:
            continue

        # 涨跌幅
        if prev_close > 0:
            change_pct = round((latest - prev_close) / prev_close * 100, 4)
        else:
            change_pct = 0.0

        # 换手率：ETF 没有"流通股本"概念，留 0 不影响下游
        # 流通市值：留 0 → strategy.py MCAP > 50亿 自动跳过 ETF
        by_code[code6] = {
            '代码': code6,
            '名称': name,
            '最新价': latest,
            '涨跌幅': change_pct,
            '成交量': volume,
            '成交额': amount,
            '换手率': 0.0,
            '流通市值': 0.0,
        }

    return by_code


def fetch_all_etfs(codes):
    """分批拉所有 ETF，返回 list[dict]."""
    all_rows = []
    for i in range(0, len(codes), SINA_BATCH_SIZE):
        batch = [c['code'] for c in codes[i:i + SINA_BATCH_SIZE]]
        print(f'[ETF] fetching batch {i // SINA_BATCH_SIZE + 1} '
              f'({len(batch)} codes: {batch[0]}...{batch[-1]})')
        result = fetch_sina_batch(batch)
        for code in batch:
            if code in result:
                all_rows.append(result[code])
        # 批间小停一下避免触发限流
        if i + SINA_BATCH_SIZE < len(codes):
            time.sleep(random.uniform(0.5, 1.0))
    return all_rows


def append_to_today_csv(etf_rows):
    """追加到 data/stock_YYYYMMDD.csv。

    覆盖规则：如果当日文件里已有同代码（理论不会，A 股 + ETF 代码段不重叠），新行替换旧行。
    如果当日文件不存在（fetch_stock_data 还没跑），创建一个仅含 ETF 的新文件，
    交易日早晨 fetch_stock_data 跑完后再追加（流水线顺序保证 stock 先 etf 后）。
    """
    today = datetime.now().strftime('%Y%m%d')
    today_file = os.path.join(DATA_DIR, f'stock_{today}.csv')

    new_df = pd.DataFrame(etf_rows)
    if new_df.empty:
        print('[ETF] no rows to append')
        return today_file

    # 统一字段顺序，跟 stock_*.csv schema 对齐
    cols = ['代码', '名称', '最新价', '涨跌幅', '成交量', '成交额', '换手率', '流通市值']
    new_df = new_df[cols]

    if os.path.exists(today_file):
        existing = pd.read_csv(today_file, dtype={'代码': str})
        existing['代码'] = existing['代码'].astype(str).str.zfill(6)
        # 去掉旧的 ETF 行（重复跑时覆盖）
        keep_mask = ~existing['代码'].isin(new_df['代码'])
        merged = pd.concat([existing[keep_mask], new_df], ignore_index=True)
        merged = merged.sort_values('代码').reset_index(drop=True)
    else:
        merged = new_df.sort_values('代码').reset_index(drop=True)

    merged.to_csv(today_file, index=False, encoding='utf-8-sig')
    return today_file


def main():
    print('=' * 50)
    print(f"  ETF 行情抓取 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('=' * 50)

    codes = merge_codes_from_sources()
    if not codes:
        print('[ETF] no codes to fetch (watchlist empty + real_trades has no ETF). Skip.')
        return 0

    print(f'[ETF] {len(codes)} ETFs to fetch: {", ".join(c["code"] for c in codes)}')

    rows = fetch_all_etfs(codes)
    if not rows:
        print('[ETF] FATAL: 0 rows returned from Sina')
        return 1

    print(f'[ETF] got {len(rows)}/{len(codes)} ETF rows')

    output = append_to_today_csv(rows)
    print(f'[ETF] appended to {output}')

    # 打印用户最关心的几只
    sample = pd.DataFrame(rows).head(10)
    if not sample.empty:
        print('\n实时价（采样）：')
        for _, r in sample.iterrows():
            print(f"  {r['代码']} {r['名称'][:12]:<12} {r['最新价']:>7.3f}  {r['涨跌幅']:>+6.2f}%")

    return 0


if __name__ == '__main__':
    sys.exit(main())
