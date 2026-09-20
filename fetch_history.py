"""
历史日线数据下载（过去60个交易日）
使用新浪财经 K 线 API + 多线程加速
数据保存到 data/history.csv，支持增量更新
"""
import requests
import time
import random
import os
import sys
import shutil
import json
import logging
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ========== 配置 ==========
HISTORY_DAYS = 60
# v8.5+: 8线程 + 0.2s 延迟会触发 Sina 456 限流（实测 4400 只里 3870 失败）
# 降至 3线程 + 0.5-1.0s 延迟 ≈ 3 req/s 总量，稳过 Sina 频率门槛；
# 损失约 50% 速度但保住成功率，对每天 ≤4500 只增量更新足够（~25min 完成）
MAX_WORKERS = 3
REQUEST_DELAY = (0.5, 1.0)
MAX_RETRIES = 3
BATCH_SAVE_INTERVAL = 50  # 每50只股票保存一次进度——避免 5 分钟跑了一半却没写盘

from core.paths import DATA_DIR  # S4-b 路径收敛：仓根/data 唯一来源
HISTORY_FILE = DATA_DIR / 'history.csv'

# 线程安全锁（写文件用）
write_lock = Lock()

# q920-01：重试吞异常要有声——真 bug 不许伪装成网络不稳
logger = logging.getLogger(__name__)

# ========== dry-run 保护（q916-04 切片1，设计稿 quant-dryrun-fetch-design-20260916）==========
# 契约：网络请求路径不变；命中写点/备份副作用时短路并打印 [DRY-RUN]；默认行为（无旗标）逐字节不变。
DRY = False
DRY_HITS = []        # 本次运行被拦的写点记录（W0/W1/W2/W3），收尾汇总用

# ========== 反反爬配置 ==========
HEADERS_TEMPLATES = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://finance.sina.com.cn/',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://money.finance.sina.com.cn/',
    },
]


def get_random_headers():
    return random.choice(HEADERS_TEMPLATES).copy()


# ========== v8.6.1 快路径：东方财富全市场当日快照 ==========
# 一次请求返回全市场（含北交所）当日 OHLC 快照，覆盖「仅缺今日」的股票，
# 把每天 ~5500 次逐股请求压成 1 次（58 分钟 → 秒级）。
# 任何环节失败都会整体放弃快路径、回退到下方新浪逐股路径 —— 数据正确性优先于速度。
EM_CLIST_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
# 首选含北交所（m:0 t:81 s:2048）的全市场口径；若返回空则回退沪深四段口径（历史验证可用）
EM_CLIST_FS = 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048'
EM_CLIST_FS_FALLBACK = 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23'
EM_CLIST_FIELDS = 'f2,f5,f12,f14,f124,f15,f16,f17,f18'


def get_em_headers():
    """东方财富专用请求头（快路径用）"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://quote.eastmoney.com/',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'close',
    }


# ========== 反反爬：指数退避请求 ==========
# Sina 的限流状态码：403 = IP/UA 拦截，456 = 速率超限，429 = 标准限流
RATE_LIMIT_CODES = {403, 429, 456}


def request_with_backoff(url, params, max_retries=MAX_RETRIES):
    """带指数退避的请求

    v8.5+: 显式识别 Sina 的 456（频率超限）；它和 403 同等需要长退避。
    早期版本只对 403 退避，遇到 456 时只睡 1s 就重试，结果反复触发 → 看起来"卡住"实则被封禁。
    """
    last_exc = None
    for attempt in range(max_retries):
        last_exc = None
        try:
            time.sleep(random.uniform(*REQUEST_DELAY))
            resp = requests.get(url, params=params, headers=get_random_headers(), timeout=20)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                return resp
            if resp.status_code in RATE_LIMIT_CODES:
                # 指数退避，最多 16 秒，让 Sina 的限流窗口冷却
                backoff = min(2 ** (attempt + 1), 16)
                time.sleep(backoff)
            else:
                time.sleep(1)
        except Exception as exc:
            last_exc = exc
            time.sleep(2 ** (attempt + 1))
    if last_exc is not None:
        # 只在"最后一次尝试是以异常告终"时告警；中途抖过但最后是正常返回非 200 的不算
        logger.warning(
            "[WARN] request_with_backoff 连续 %s 次未能取回数据，最后一次是异常而非限流：%r（url=%s）",
            max_retries, last_exc, str(url)[:120],
        )
    return None


# ========== 股票代码格式转换 ==========
def code_to_sina_symbol(code):
    """将6位代码转为新浪格式：sh600000, sz000001, bj920000

    v8.6: 增加 ETF 前缀支持
        沪市 ETF: 51xxxx / 52xxxx / 56xxxx / 58xxxx / 588xxx → sh
        深市 ETF: 15xxxx / 159xxx / 16xxxx / 18xxxx       → sz
    """
    code = str(code).zfill(6)
    # 沪市：6xx 主板 / 5xx ETF / 110/113/118 可转债 / 588 科创板 ETF
    # Round-2 修复（2026-05-30）：110/113/118 是沪市可转债，旧版误归 sz
    if code[0] in ('5', '6') or code[:3] in ('110', '113', '118'):
        return f'sh{code}'
    # 深市：0xx 主板 / 3xx 创业板 / 1xx (含 159xxx ETF / 123/127/128 可转债) / 2xx B股
    if code[0] in ('0', '1', '2', '3'):
        return f'sz{code}'
    # 北交所：8xx / 9xx
    if code[0] in ('8', '9'):
        return f'bj{code}'
    return f'sz{code}'


# ========== 获取单只股票历史数据 ==========
def fetch_one_stock_history(code):
    """
    获取单只股票历史日线数据
    返回 DataFrame 或 None（失败时）
    """
    symbol = code_to_sina_symbol(code)

    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    params = {
        'symbol': symbol,
        'scale': '240',  # 日K
        'ma': 'no',
        'datalen': str(HISTORY_DAYS + 10),  # 多取一些防止不足
    }

    resp = request_with_backoff(url, params)
    if not resp:
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return None

    if not data or len(data) == 0:
        return None

    records = []
    for d in data:
        try:
            records.append({
                '代码': code,
                '日期': d.get('day', ''),
                '开盘': float(d.get('open', 0) or 0),
                '最高': float(d.get('high', 0) or 0),
                '最低': float(d.get('low', 0) or 0),
                '收盘': float(d.get('close', 0) or 0),
                '成交量': float(d.get('volume', 0) or 0),
            })
        except (ValueError, TypeError):
            continue

    if len(records) < 5:  # 数据太少不值得保留
        return None

    return pd.DataFrame(records)


# ========== 快路径：东财全市场快照 ==========
def fetch_em_snapshot():
    """拉取东财全市场当日快照，返回 diff 列表；失败返回 None。

    先试含北交所的全市场口径，空/失败再回退沪深口径；两套都失败返回 None。
    带指数退避重试 + 节流（反反爬）。
    """
    for fs in (EM_CLIST_FS, EM_CLIST_FS_FALLBACK):
        diff = _fetch_em_fs(fs)
        if diff:
            return diff
        print(f"[EM-FASTPATH] fs variant returned no data, trying next: {fs[:40]}...")
    return None


def _fetch_em_fs(fs):
    params = {'pn': '1', 'pz': '6000', 'po': '1', 'np': '1', 'fltt': '2', 'invt': '2',
              'fid': 'f3', 'fs': fs, 'fields': EM_CLIST_FIELDS}
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(random.uniform(*REQUEST_DELAY))  # 反反爬：单请求也保持节流
            resp = requests.get(EM_CLIST_URL, params=params,
                                headers=get_em_headers(), timeout=25)
            if resp.status_code == 200:
                resp.encoding = 'utf-8'
                data = resp.json()
                diff = (data.get('data') or {}).get('diff') or []
                if diff:
                    return diff
                print(f"[EM-FASTPATH] empty diff on attempt {attempt + 1}")
            elif resp.status_code in RATE_LIMIT_CODES:
                time.sleep(min(2 ** (attempt + 1), 16))
            else:
                print(f"[EM-FASTPATH] HTTP {resp.status_code} on attempt {attempt + 1}")
                time.sleep(1)
        except Exception as e:
            print(f"[EM-FASTPATH] attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** (attempt + 1))
    return None


def em_snapshot_rows(diff, target_date_str):
    """解析东财快照为 history.csv 行（代码,日期,开盘,最高,最低,收盘,成交量(股)）。

    行级校验：OHLC>0、低 ≤ 开/收 ≤ 高、成交量>0、f124 日期 == 目标日、代码合法。
    整体陈旧检测：快照里没有任何 f124 落在目标日 → 返回 None（接口数据陈旧）。
    """
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    ts_dates = set()
    for it in diff:
        code = str(it.get('f12') or '').zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue
        try:
            d = datetime.fromtimestamp(int(it.get('f124') or 0)).strftime('%Y-%m-%d')
        except (TypeError, ValueError, OSError):
            d = ''
        ts_dates.add(d)
        open_, high, low, close = (_num(it.get(k)) for k in ('f17', 'f15', 'f16', 'f2'))
        vol = _num(it.get('f5'))
        if None in (open_, high, low, close, vol) or d != target_date_str:
            continue
        vol = vol * 100  # 东财成交量单位是「手」，×100 转「股」，与新浪口径一致
        if vol <= 0 or min(open_, high, low, close) <= 0:
            continue
        if low > min(open_, close) or high < max(open_, close):
            continue
        rows.append({'代码': code, '日期': d, '开盘': open_, '最高': high,
                     '最低': low, '收盘': close, '成交量': vol})
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    if target_date_str not in ts_dates:
        print(f"[EM-FASTPATH] snapshot dates {sorted(x for x in ts_dates if x)[-3:]} "
              f"do not include target {target_date_str}; treat as stale")
        return None
    return df.drop_duplicates(subset=['代码'], keep='first').reset_index(drop=True)


def em_vs_sina_crosscheck(em_df, sina_file):
    """东财快照 vs 新浪当日快照（data/stock_YYYYMMDD.csv）量价交叉校验。

    价格偏差 >0.5% 或成交量偏差 >5% 的行数占比超阈值 → 判定快照不可信，返回 False。
    """
    try:
        sina = pd.read_csv(sina_file, dtype={'代码': str}, usecols=['代码', '最新价', '成交量'])
    except Exception as e:
        print(f"[EM-FASTPATH] cannot read sina snapshot for crosscheck: {e}")
        return False, 'sina-snapshot-unreadable'
    sina['代码'] = sina['代码'].astype(str).str.zfill(6)
    m = em_df.merge(sina, on='代码', how='inner')
    if len(m) < 100:
        return False, f'crosscheck sample too small ({len(m)})'
    price_dev = (m['收盘'] - m['最新价']).abs() / m['最新价'].clip(lower=0.01)
    vol_dev = (m['成交量_x'] - m['成交量_y']).abs() / m['成交量_y'].clip(lower=1.0)
    n_price_bad = int((price_dev > 0.005).sum())
    n_vol_bad = int((vol_dev > 0.05).sum())
    if n_price_bad / len(m) > 0.01 or n_vol_bad / len(m) > 0.05:
        return False, f'crosscheck mismatch: price_bad={n_price_bad}/{len(m)}, vol_bad={n_vol_bad}/{len(m)}'
    return True, f'crosscheck ok: price_bad={n_price_bad}, vol_bad={n_vol_bad} of {len(m)}'


def try_em_fastpath(codes_to_fetch, latest_by_code, target_date_str, sina_snapshot_file):
    """东财快路径主入口。成功返回已覆盖的代码集合；任何环节失败返回 None（走新浪兜底）。

    覆盖范围：仅「已有历史且最新日期 == 全市场最新日期」的股票（只缺今天一行）。
    新股/断档股/停牌股仍走新浪逐股路径补历史。首次建库（无 history.csv）不用快路径。
    开关：环境变量 QUANT_HISTORY_NO_FASTPATH=1 可整体关闭（运维回滚用）。
    """
    if os.environ.get('QUANT_HISTORY_NO_FASTPATH') == '1':
        print('[EM-FASTPATH] disabled by QUANT_HISTORY_NO_FASTPATH=1')
        return None
    # 盘中保护（评审必修项）：A股交易时段内 f2 是盘中价而非收盘价，绝不能入库
    _now = datetime.now()
    if _now.weekday() < 5 and datetime.strptime('09:25', '%H:%M').time() <= _now.time() <= datetime.strptime('15:05', '%H:%M').time():
        print('[EM-FASTPATH] market hours (09:25-15:05); snapshot is intraday, skip fast path')
        return None
    market_max = max(latest_by_code.values()) if latest_by_code else None
    if not market_max:
        print('[EM-FASTPATH] no existing history; first-run build must use Sina full path')
        return None
    fast_candidates = {c for c in codes_to_fetch if latest_by_code.get(c) == market_max}
    if not fast_candidates:
        return None

    diff = fetch_em_snapshot()
    if diff is None:
        print('[EM-FASTPATH] snapshot fetch failed; fall back to Sina per-stock path')
        return None
    em_df = em_snapshot_rows(diff, target_date_str)
    if em_df is None or em_df.empty:
        print('[EM-FASTPATH] snapshot parse/validate failed; fall back to Sina per-stock path')
        return None

    # 覆盖率按「快路径候选」计（采纳多模型评审：分母用 eligible，阈值 90%，宁可回退不可写半截）
    em_new = em_df[em_df['代码'].isin(fast_candidates)].copy()
    if len(em_new) < max(50, int(len(fast_candidates) * 0.9)):
        print(f"[EM-FASTPATH] coverage too low ({len(em_new)}/{len(fast_candidates)} eligible); "
              f"fall back to Sina per-stock path")
        return None
    ok, detail = em_vs_sina_crosscheck(em_new, sina_snapshot_file)
    if not ok:
        print(f'[EM-FASTPATH] crosscheck failed ({detail}); fall back to Sina per-stock path')
        return None

    # 写盘前先备份（保留 history.csv.bak），校验全部通过才追加
    if DRY:
        print(f'[DRY-RUN] W0 would-backup -> {HISTORY_FILE}.bak')
        DRY_HITS.append(('W0', str(HISTORY_FILE) + '.bak'))
    else:
        try:
            if os.path.exists(HISTORY_FILE):
                shutil.copy2(HISTORY_FILE, HISTORY_FILE.with_name(HISTORY_FILE.name + '.bak'))
        except Exception as e:
            print(f'[EM-FASTPATH] backup failed: {e}; fall back to Sina per-stock path')
            return None
    if DRY:
        print(f'[DRY-RUN] W1 would-append -> {HISTORY_FILE} ({len(em_new)} rows, mode=append)')
        DRY_HITS.append(('W1', str(HISTORY_FILE)))
    else:
        try:
            with write_lock:
                header = not os.path.exists(HISTORY_FILE)
                em_new.to_csv(HISTORY_FILE, mode='a', index=False,
                              encoding='utf-8-sig', header=header)
        except Exception as e:
            print(f'[EM-FASTPATH] append failed: {e}; fall back to Sina per-stock path')
            return None

    if DRY:
        print(f'[EM-FASTPATH] DRY: would append {len(em_new)} rows from eastmoney snapshot '
              f'({detail}); {len(codes_to_fetch) - len(em_new)} stocks left for Sina path')
    else:
        print(f'[EM-FASTPATH] OK: appended {len(em_new)} rows from eastmoney snapshot '
              f'({detail}); {len(codes_to_fetch) - len(em_new)} stocks left for Sina path')
    return set(em_new['代码'].tolist())


# ========== 增量更新逻辑 ==========
def get_existing_codes():
    """检查已存在的历史数据，返回已覆盖的股票代码集合"""
    if os.path.exists(HISTORY_FILE):
        try:
            existing = pd.read_csv(HISTORY_FILE, dtype={'代码': str})
            return set(existing['代码'].unique())
        except Exception:
            return set()
    return set()


def save_increment(df_new, mode='a'):
    """增量保存 CSV"""
    if DRY:
        print(f'[DRY-RUN] W2 would-append -> {HISTORY_FILE} ({len(df_new)} rows, mode={mode})')
        DRY_HITS.append(('W2', str(HISTORY_FILE)))
        return None
    with write_lock:
        header = not os.path.exists(HISTORY_FILE) or mode == 'w'
        df_new.to_csv(HISTORY_FILE, mode=mode, index=False,
                      encoding='utf-8-sig', header=header)


# ========== 主流程 ==========
def final_dedupe():
    """Step 4.5 最终去重——把 stream-append 写入的多版本压平（dry-run 下短路并打印将写计划）。"""
    # Round-2 修复（2026-05-30）：移除冗余的 existing_full concat，单 disk_df 自带去重
    # disk_df 已经包含了"原始记录 + 本次 stream-append 内容"，再合并 existing_full 是无意义的双倍内存
    try:
        if os.path.exists(HISTORY_FILE):
            disk_df = pd.read_csv(HISTORY_FILE, dtype={'代码': str})
            if not disk_df.empty:
                disk_df = disk_df.drop_duplicates(subset=['代码', '日期'], keep='first')
                disk_df = disk_df.sort_values(['代码', '日期']).reset_index(drop=True)
                if DRY:
                    print(f'[DRY-RUN] W3 would-rewrite -> {HISTORY_FILE} '
                          f'({len(disk_df)} rows, mode=rewrite)')
                    DRY_HITS.append(('W3', str(HISTORY_FILE)))
                    return
                # 原子写（.tmp + os.replace）：断电/异常不会留下半截文件
                tmp_path = HISTORY_FILE + '.tmp'
                disk_df.to_csv(tmp_path, index=False, encoding='utf-8-sig')
                os.replace(tmp_path, HISTORY_FILE)
    except Exception as e:
        print(f"[WARN] Final dedupe failed: {e}（已保留原有数据，不会丢失）")


def _resolve_increment_plan():
    """只读盘上状态算出"本次要拉哪些股票"的增量计划（零网络、零写盘）。

    `main()` 与 `--dry-run-plan`（q916-04 切片3）共用这一份算法：判定口径涉及
    股票池回退、目标日期解析与 latest_by_code 分组，两处各写一遍迟早漂，漂一次就是漏拉或多拉一整天数据。
    返回 None ＝ 连股票池文件都没有（main 侧原本就是 FATAL 退出）。
    """
    import glob
    import re
    today = datetime.now().strftime('%Y%m%d')
    today_file = DATA_DIR / f'stock_{today}.csv'
    used_fallback = False

    if not os.path.exists(today_file):
        files = sorted(glob.glob(str(DATA_DIR / 'stock_*.csv')), reverse=True)
        if not files:
            return None
        today_file = files[0]
        used_fallback = True

    stock_df = pd.read_csv(today_file, dtype={'代码': str})
    all_codes = list(dict.fromkeys(stock_df['代码'].tolist()))
    pool_size = len(all_codes)
    del stock_df        # 只要代码列，别把整张池表带到函数尾部

    m = re.search(r'stock_(\d{8})\.csv', os.path.basename(str(today_file)))
    if m:
        y = m.group(1)
        target_date_str = f'{y[0:4]}-{y[4:6]}-{y[6:8]}'
    else:
        target_date_str = datetime.now().strftime('%Y-%m-%d')

    # 只保留 latest_by_code 字典，不整表驻留（Round-2 的 OOM 教训，见 main 原注释）
    latest_by_code = {}
    if os.path.exists(HISTORY_FILE):
        try:
            _tmp_full = pd.read_csv(HISTORY_FILE, dtype={'代码': str}, usecols=['代码', '日期'])
            if not _tmp_full.empty:
                latest_by_code = _tmp_full.groupby('代码')['日期'].max().to_dict()
            del _tmp_full
        except Exception as e:
            print(f"[WARN] Failed to read existing history: {e}")

    new_codes = [c for c in all_codes if c not in latest_by_code]
    stale_codes = [c for c in all_codes
                   if c in latest_by_code and latest_by_code[c] < target_date_str]
    codes_to_fetch = list(dict.fromkeys(new_codes + stale_codes))   # 保序去重

    return {
        'pool_file': str(today_file), 'pool_size': pool_size,
        'target_date': target_date_str, 'latest_by_code': latest_by_code,
        'new_codes': new_codes, 'stale_codes': stale_codes,
        'codes_to_fetch': codes_to_fetch, 'used_fallback': used_fallback,
    }


def describe_plan(plan: dict) -> None:
    """把增量计划打成人类可读清单（--dry-run-plan 的全部输出；不碰网络、不落一个字节）。"""
    todo = plan['codes_to_fetch']
    print("[DRY-RUN-PLAN] 零网络 · 零写盘 —— 只读盘上状态得到的增量计划")
    print(f"  股票池文件: {plan['pool_file']}（{plan['pool_size']} 只）"
          + ("（当日文件缺失，回退用最新一份）" if plan['used_fallback'] else ""))
    print(f"  目标日期  : {plan['target_date']}")
    print(f"  待补代码  : {len(todo)} 只 = 全新 {len(plan['new_codes'])} + 落后 {len(plan['stale_codes'])}"
          f"；跳过 {plan['pool_size'] - len(todo)} 只")
    print(f"  目标文件  : {HISTORY_FILE}")
    print("  写入方式  : 逐批 stream-append（save_increment mode='a'）＋ 收尾整体重写去重（final_dedupe）")
    if todo:
        print(f"  待补样例  : {', '.join(todo[:10])}" + (" …" if len(todo) > 10 else ""))


def _parse_args(argv):
    """q916-04 切片1：--dry-run 旗标（网络照常、写点短路）。默认行为与历史版本完全一致。

    切片3（q918-19）另加 `--dry-run-plan`：连网络都不碰，只读盘上状态打一份增量计划就退出。
    两个旗标互斥意义不同——`--dry-run` 会真拉数据（能看到数据源问题），`--dry-run-plan` 是纯本地预演。
    """
    import argparse
    parser = argparse.ArgumentParser(description='历史日线数据下载器')
    # q920-01：两个旗标语义不同（前者真拉数据、后者零网络），同时给必须当场拒掉而不是先到先得
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument('--dry-run', action='store_true',
                       help='预演模式：网络请求照常，所有写点与备份副作用短路，仅打印 would-write')
    flags.add_argument('--dry-run-plan', action='store_true',
                       help='只读盘上状态打印增量计划（股票池/待补代码/目标文件/追加vs重写）后退出：零网络、零写盘')
    return parser.parse_args(argv)


def main(argv=None):
    global DRY
    args = _parse_args(argv)
    DRY = args.dry_run
    DRY_HITS.clear()

    if args.dry_run_plan:
        plan = _resolve_increment_plan()
        if plan is None:
            print("[FATAL] No stock data file found. Run fetch_stock_data.py first.")
            return 1
        describe_plan(plan)
        return 0

    print(f"{'='*50}")
    if DRY:
        print("  [DRY-RUN] 历史数据下载器预演（写点将短路）")
    print(f"  历史数据下载器启动 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标：过去 {HISTORY_DAYS} 个交易日，{MAX_WORKERS} 线程并发")
    print(f"{'='*50}")

    os.makedirs(DATA_DIR, exist_ok=True)

    # Step 1+2: 增量计划——与 --dry-run-plan 共用 _resolve_increment_plan（不复制第二份判定口径）
    plan = _resolve_increment_plan()
    if plan is None:
        print("[FATAL] No stock data file found. Run fetch_stock_data.py first.")
        sys.exit(1)
    today_file = plan['pool_file']
    target_date_str = plan['target_date']
    latest_by_code = plan['latest_by_code']
    new_codes = plan['new_codes']
    stale_codes = plan['stale_codes']
    codes_to_fetch = plan['codes_to_fetch']
    if plan['used_fallback']:
        print(f"[INFO] Using stock list from: {today_file}")
    print(f"[INFO] {plan['pool_size']} stocks to process")

    if len(codes_to_fetch) == 0:
        print(f"[OK] History up-to-date (all {plan['pool_size']} stocks ≥ {target_date_str})")
        return 0

    print(f"[INFO] Target date: {target_date_str}")
    print(f"[INFO] Need to fetch: {len(codes_to_fetch)} stocks")
    print(f"       new (no record): {len(new_codes)}")
    print(f"       stale (date < target): {len(stale_codes)}")
    print(f"       up-to-date: {plan['pool_size'] - len(codes_to_fetch)} (skipped)")

    # Step 3 (v8.6.1): 先试东财快路径 —— 一次请求覆盖「仅缺今日」的股票。
    # 失败/校验不过会自动回退，codes_to_fetch 剔除已覆盖部分。
    fast_covered = try_em_fastpath(codes_to_fetch, latest_by_code,
                                   target_date_str, today_file) or set()
    codes_to_fetch = [c for c in codes_to_fetch if c not in fast_covered]

    # Step 4: 剩余股票（新股/断档/快照缺失）走新浪逐股并发下载
    success_count = 0
    fail_count = 0
    buffer = []  # 缓存批量写入

    if codes_to_fetch:
        print(f"[INFO] Sina per-stock path for remaining {len(codes_to_fetch)} stocks")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_code = {
                executor.submit(fetch_one_stock_history, code): code
                for code in codes_to_fetch
            }

            for i, future in enumerate(as_completed(future_to_code)):
                code = future_to_code[future]
                try:
                    df = future.result()
                    if df is not None and len(df) > 0:
                        buffer.append(df)
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1

                # 批量保存
                if len(buffer) >= BATCH_SAVE_INTERVAL:
                    combined = pd.concat(buffer, ignore_index=True)
                    save_increment(combined)
                    buffer = []
                    print(f"[PROGRESS] {i+1}/{len(codes_to_fetch)} processed, "
                          f"{success_count} OK, {fail_count} FAIL")

        # Step 4.5: 保存剩余缓冲
        if buffer:
            combined = pd.concat(buffer, ignore_index=True)
            save_increment(combined)
    else:
        print("[INFO] Fast path covered all needed stocks; Sina path skipped")

    print(f"\n{'='*50}")
    print(f"  [DONE] Download complete!")
    print(f"  Fast path: {len(fast_covered)} stocks (eastmoney snapshot)")
    print(f"  Sina path: {success_count} OK, {fail_count} FAIL")
    print(f"  Saved to: {HISTORY_FILE}")
    print(f"{'='*50}")

    # Step 4.5 (v8.5): 最终去重——把 stream-append 写入的多版本压平（dry-run 下短路）
    final_dedupe()

    # Step 5: 验证数据
    if os.path.exists(HISTORY_FILE):
        final = pd.read_csv(HISTORY_FILE, dtype={'代码': str})
        unique_stocks = final['代码'].nunique()
        date_range = f"{final['日期'].min()} ~ {final['日期'].max()}"
        print(f"  Final: {len(final)} rows, {unique_stocks} unique stocks")
        print(f"  Date range: {date_range}")

    if DRY:
        targets = '; '.join(f'{w}->{p}' for w, p in DRY_HITS) or '（无）'
        print(f"[DRY-RUN] would-write: {len(DRY_HITS)} 个写点, 目标={targets}; 实际写盘 0 字节")

    return 0


if __name__ == '__main__':
    sys.exit(main())
