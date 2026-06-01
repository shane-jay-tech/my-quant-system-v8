"""
带自愈能力的全部 A 股当日行情爬虫
主数据源：新浪财经 API → 备用：东方财富 → 最后：同花顺
所有反反爬策略均从 books/反反爬实战笔记.md 中应用

字段：代码、名称、最新价、涨跌幅、成交量、成交额、换手率、流通市值
"""
import requests
import time
import random
import sys
import os
from datetime import datetime

# ========== 反反爬：请求头伪装 ==========
def get_sina_headers():
    """新浪财经专用请求头"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://vip.stock.finance.sina.com.cn/',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'close',
    }


def get_em_headers():
    """东方财富专用请求头（备用源）"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://quote.eastmoney.com/',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'close',
    }


# ========== 反反爬：指数退避重试 ==========
def safe_request(url, params, headers, max_retries=3, label=""):
    """带指数退避的请求函数，用于所有 API 调用"""
    for attempt in range(max_retries):
        try:
            # 反反爬：随机延时 0.3-0.8 秒
            time.sleep(random.uniform(0.3, 0.8))
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 403:
                print(f"[WARN] 403 Forbidden on {label}, attempt {attempt+1}/{max_retries}")
            else:
                print(f"[WARN] HTTP {resp.status_code} on {label}, attempt {attempt+1}/{max_retries}")
            time.sleep(2 ** (attempt + 1))
        except Exception as e:
            wait = 2 ** (attempt + 1) + random.uniform(0, 1)
            print(f"[RETRY] {label} attempt {attempt+1}/{max_retries}: {e}, waiting {wait:.1f}s")
            time.sleep(wait)
    return None


# ========== 数据源 1：新浪财经 API（主） ==========
def fetch_sina():
    """
    新浪财经 A 股行情接口（首选）
    通过 /Market_Center.getHQNodeData 获取，JSON 格式，无需 HTML 解析
    返回所有需要的字段：代码、名称、最新价、涨跌幅、成交量、成交额、换手率、流通市值
    """
    print("[SINA] Attempting to fetch from 新浪财经...")

    url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
    headers = get_sina_headers()

    PAGE_SIZE = 100
    all_stocks = []

    # Step 1: 先获取第1页来确定总数
    params = {
        'page': '1',
        'num': str(PAGE_SIZE),
        'sort': 'symbol',
        'asc': '1',
        'node': 'hs_a',
        'symbol': '',
        '_s_r_a': 'init',
    }

    resp = safe_request(url, params, headers, label="Sina page 1")
    if not resp:
        print("[SINA] Failed to fetch page 1, trying backup...")
        return None

    resp.encoding = 'utf-8'
    first_page = resp.json()

    if not first_page or len(first_page) == 0:
        print("[SINA] Empty page 1, trying backup...")
        return None

    all_stocks.extend(first_page)
    print(f"[SINA] Page 1: {len(first_page)} stocks (total pages unknown, will paginate until empty)")

    # Step 2: 循环获取剩余页面，直到返回空
    page = 2
    max_empty_pages = 3  # 连续空页数上限
    empty_count = 0

    while empty_count < max_empty_pages:
        params['page'] = str(page)

        resp = safe_request(url, params, headers, label=f"Sina page {page}")
        if not resp:
            # 网络错误后重试一次
            time.sleep(3)
            resp = safe_request(url, params, headers, label=f"Sina page {page} (retry)")
            if not resp:
                empty_count += 1
                page += 1
                continue

        resp.encoding = 'utf-8'
        try:
            page_data = resp.json()
        except Exception as e:
            print(f"[SINA] Page {page} JSON parse error: {e}")
            empty_count += 1
            page += 1
            continue

        if not page_data or len(page_data) == 0:
            empty_count += 1
            page += 1
            continue

        all_stocks.extend(page_data)
        empty_count = 0  # 重置空页计数

        if page % 10 == 0:
            print(f"[SINA] Progress: page {page}, {len(all_stocks)} stocks so far")

        page += 1

    if len(all_stocks) < 100:
        print(f"[SINA] Only {len(all_stocks)} stocks, insufficient, trying backup...")
        return None

    print(f"[SINA] Success! Total: {len(all_stocks)} stocks from {page-1} pages.")

    # Step 3: 转换为标准格式
    result = []
    for s in all_stocks:
        try:
            code = str(s.get('code', '')).zfill(6)
            name = s.get('name', '')
            if not code or not name:
                continue

            trade = float(s.get('trade', 0) or 0)
            change_pct = float(s.get('changepercent', 0) or 0)
            volume = float(s.get('volume', 0) or 0)
            amount = float(s.get('amount', 0) or 0)
            turnover = float(s.get('turnoverratio', 0) or 0)
            nmc = float(s.get('nmc', 0) or 0) * 10000  # 新浪返回万元，转为元

            row = {
                '代码': code,
                '名称': name,
                '最新价': trade,
                '涨跌幅': change_pct,
                '成交量': volume,
                '成交额': amount,
                '换手率': turnover,
                '流通市值': nmc,
            }
            result.append(row)
        except (ValueError, TypeError) as e:
            continue

    print(f"[SINA] Parsed {len(result)} valid stock records.")
    return result if result else None


# ========== 数据源 2：东方财富 API（备用） ==========
def fetch_eastmoney():
    """
    东方财富 API（备用源）
    当新浪失败时自动切换
    注意：可能因请求频率过高被临时封 IP
    """
    print("[EASTMONEY] Attempting to fetch from 东方财富（备用）...")

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    headers = get_em_headers()

    FIELD_LIST = 'f2,f3,f5,f6,f7,f8,f12,f14,f20'
    PAGE_SIZE = 100

    # 第1页获取总数
    params = {
        'pn': '1', 'pz': str(PAGE_SIZE), 'po': '1', 'np': '1',
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': '2', 'invt': '2', 'fid': 'f3',
        'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
        'fields': FIELD_LIST,
        '_': str(int(time.time() * 1000)),
    }

    resp = safe_request(url, params, headers, label="Eastmoney page 1")
    if not resp:
        print("[EASTMONEY] Failed to get page 1")
        return None

    try:
        data = resp.json()
    except Exception:
        print("[EASTMONEY] JSON parse error")
        return None

    if 'data' not in data or not data['data']:
        print("[EASTMONEY] Empty data")
        return None

    total = data['data'].get('total', 0)
    if total == 0:
        print("[EASTMONEY] total=0")
        return None

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"[EASTMONEY] Total: {total} stocks, {total_pages} pages")

    all_stocks = []

    # Parse first page
    for s in data['data'].get('diff', []):
        all_stocks.append({
            '代码': str(s.get('f12', '')).zfill(6),
            '名称': s.get('f14', ''),
            '最新价': float(s.get('f2', 0) or 0),
            '涨跌幅': float(s.get('f3', 0) or 0),
            '成交量': float(s.get('f5', 0) or 0),
            '成交额': float(s.get('f6', 0) or 0),
            '换手率': float(s.get('f7', 0) or 0),
            '流通市值': float(s.get('f20', 0) or 0),
        })

    # Paginate remaining
    for page in range(2, total_pages + 1):
        params['pn'] = str(page)
        params['_'] = str(int(time.time() * 1000))

        resp = safe_request(url, params, headers, label=f"Eastmoney page {page}")
        if not resp:
            print(f"[EASTMONEY] Page {page} failed, skipping")
            continue

        try:
            page_data = resp.json()
            for s in page_data.get('data', {}).get('diff', []):
                all_stocks.append({
                    '代码': str(s.get('f12', '')).zfill(6),
                    '名称': s.get('f14', ''),
                    '最新价': float(s.get('f2', 0) or 0),
                    '涨跌幅': float(s.get('f3', 0) or 0),
                    '成交量': float(s.get('f5', 0) or 0),
                    '成交额': float(s.get('f6', 0) or 0),
                    '换手率': float(s.get('f7', 0) or 0),
                    '流通市值': float(s.get('f20', 0) or 0),
                })
        except Exception as e:
            print(f"[EASTMONEY] Page {page} parse error: {e}")
            continue

        if page % 10 == 0:
            print(f"[EASTMONEY] Progress: {page}/{total_pages}")

    if len(all_stocks) < 100:
        return None
    print(f"[EASTMONEY] Success! Got {len(all_stocks)} stocks")
    return all_stocks


# ========== 数据源 3：同花顺（最后备用） ==========
def fetch_10jqka():
    """
    同花顺（最后备用源）
    通过 HTML 页面解析股票数据
    """
    print("[10JQKA] Attempting to fetch from 同花顺（最后备用）...")

    url = "https://q.10jqka.com.cn/index/index/board/all/field/zdf/order/desc/page/1/ajax/1/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://q.10jqka.com.cn/',
        'Connection': 'close',
    }

    import re
    resp = safe_request(url, {}, headers, label="10jqka")
    if not resp:
        return None

    html = resp.text
    # 提取股票数据（同花顺页面结构）
    pattern = r'<tr[^>]*>.*?<td[^>]*>(\d+)</td>.*?<td[^>]*>.*?">([^<]+)</a>.*?<td[^>]*>.*?">([^<]+)</td>.*?<td[^>]*>.*?">([^<]+)</td>.*?</tr>'
    matches = re.findall(pattern, html, re.DOTALL)

    result = []
    for m in matches:
        result.append({
            '代码': m[0].zfill(6),
            '名称': m[1],
            '最新价': float(m[2]) if m[2] != '-' else 0,
            '涨跌幅': float(m[3].replace('%', '')) if m[3] != '-' else 0,
            '成交量': 0,
            '成交额': 0,
            '换手率': 0,
            '流通市值': 0,
        })

    if len(result) < 100:
        print(f"[10JQKA] Only {len(result)} stocks, insufficient")
        return None

    print(f"[10JQKA] Got {len(result)} stocks")
    return result


# ========== 主流程：多源自动切换 ==========
def main():
    print(f"{'='*50}")
    print(f"  A股行情爬虫启动 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    today = datetime.now().strftime('%Y%m%d')

    # 依次尝试三个数据源（自动故障转移）
    sources = [
        ('新浪财经', fetch_sina),
        ('东方财富', fetch_eastmoney),
        ('同花顺', fetch_10jqka),
    ]

    stocks = None
    for source_name, fetch_func in sources:
        try:
            stocks = fetch_func()
            if stocks and len(stocks) >= 100:
                print(f"[OK] Successfully fetched {len(stocks)} stocks from {source_name}")
                break
            else:
                print(f"[SWITCH] {source_name} returned insufficient data ({len(stocks) if stocks else 0}), switching...")
                time.sleep(random.uniform(2, 4))
        except Exception as e:
            print(f"[ERROR] {source_name} failed with exception: {e}")
            continue

    if not stocks or len(stocks) == 0:
        print("[FATAL] All data sources failed! No stock data available.")
        sys.exit(1)

    # 保存数据
    import pandas as pd
    df = pd.DataFrame(stocks)
    df = df.drop_duplicates(subset=['代码'], keep='first')
    df = df.sort_values('代码').reset_index(drop=True)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'stock_{today}.csv')
    df.to_csv(output_path, index=False, encoding='utf-8-sig')

    print(f"\n{'='*50}")
    print(f"  [DONE] {len(df)} stocks saved to {output_path}")
    print(f"  数据范围：{df['代码'].iloc[0]} ~ {df['代码'].iloc[-1]}")
    print(f"  涨跌幅范围：{df['涨跌幅'].min():.2f}% ~ {df['涨跌幅'].max():.2f}%")
    print(f"{'='*50}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
