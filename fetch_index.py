"""沪深300基准指数刷新 — 全系统单一写入源（v8.7 抽取）。

Why this exists:
    data/hs300_index.csv（HS300 收盘价基准）此前唯一的刷新者是
    enhanced_backtest.fetch_index()，而 enhanced_backtest 属于 pipeline 的
    `backtest` 步骤，只在 advanced+ 档运行。beginner 档每天的流水线从不刷新
    基准 → 数据冻结 → etf_gate / position_sizer / benchmark_comparison 全部
    吃陈旧数据（实测曾冻结 24 天）。

    本模块把"抓 HS300 → 合并写 csv"独立出来，注册为每天、所有档位都跑的
    pipeline 步骤（core/pipeline.py: fetch_index），并由 enhanced_backtest
    复用，确保全系统只有一个写入方（避免"合并写入"与"全量覆盖"两份逻辑打架）。

数据源：新浪行情 sh000300（与历史实现一致）。
输出契约（下游 benchmark_comparison.load_hs300 / position_sizer.fetch_hs300_data /
enhanced_backtest.fetch_index / data_loader 依赖，不可破坏）：
    列 `日期,收盘`；编码 utf-8-sig；按日期升序。
"""
from __future__ import annotations

import os
import random
import sys
import time

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "data")
INDEX_FILE = "hs300_index.csv"

_SINA_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
# 反反爬：轮换 UA + 固定 Referer（沿用历史实现验证可用的请求形态）
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_MAX_RETRY = 3
_TIMEOUT = 15
# 取最近 ~200 个交易日，再与现有文件合并 → 既拿到最新，又不丢更早历史
_DATALEN = 200


def _fetch_sina_hs300():
    """抓新浪 sh000300 日线收盘。

    成功返回 [{'日期': 'YYYY-MM-DD', '收盘': float}, ...]；
    全部重试失败或返回空 → 返回 None（调用方据此决定不动现有文件）。
    """
    sess = requests.Session()
    params = {"symbol": "sh000300", "scale": "240", "ma": "no", "datalen": str(_DATALEN)}
    for attempt in range(1, _MAX_RETRY + 1):
        headers = {
            "User-Agent": random.choice(_UA_POOL),
            "Referer": "https://finance.sina.com.cn/",
        }
        try:
            resp = sess.get(_SINA_URL, params=params, headers=headers, timeout=_TIMEOUT)
            if resp.status_code != 200:
                print(f"[FETCH_INDEX] 第 {attempt}/{_MAX_RETRY} 次：HTTP {resp.status_code}")
                raise requests.HTTPError(f"status {resp.status_code}")
            data = resp.json()
            recs = []
            for d in data:
                day, close = d.get("day"), d.get("close")
                if not day or close is None:
                    continue
                try:
                    recs.append({"日期": str(day)[:10], "收盘": float(close)})
                except (TypeError, ValueError):
                    continue
            if recs:
                print(f"[FETCH_INDEX] 抓到 {len(recs)} 条 HS300 收盘（最新 {recs[-1]['日期']}）")
                return recs
            print(f"[FETCH_INDEX] 第 {attempt}/{_MAX_RETRY} 次：解析后为空")
        except Exception as exc:  # 反反爬：吞掉单次异常，退避后重试
            print(f"[FETCH_INDEX] 第 {attempt}/{_MAX_RETRY} 次失败：{exc}")
        if attempt < _MAX_RETRY:
            wait = min(2 ** attempt, 16) + random.uniform(0, 1)  # 指数退避 + 抖动
            time.sleep(wait)
    return None


def _merge(existing, fresh: pd.DataFrame) -> pd.DataFrame:
    """合并新旧数据：按日期去重（新覆盖旧）+ 升序。

    保留 existing 中早于本次抓取窗口的历史行（datalen 只回看 ~200 个交易日）。
    """
    fresh = fresh.copy()
    fresh["日期"] = fresh["日期"].astype(str).str[:10]
    fresh = fresh[["日期", "收盘"]]
    if existing is not None and not existing.empty and "日期" in existing.columns and "收盘" in existing.columns:
        existing = existing.copy()
        existing["日期"] = existing["日期"].astype(str).str[:10]
        combined = pd.concat([existing[["日期", "收盘"]], fresh], ignore_index=True)
    else:
        combined = fresh
    # fresh 在后 → keep='last' 让同一交易日以新数据为准
    combined = combined.drop_duplicates(subset="日期", keep="last")
    # 日期为 ISO 字符串，字典序 == 时间序
    combined = combined.sort_values("日期").reset_index(drop=True)
    return combined


def update_hs300_index(data_dir: str | None = None) -> bool:
    """抓 HS300 并合并写入 data/hs300_index.csv。

    成功返回 True；网络/解析/合并失败返回 False，且**绝不覆盖或清空现有文件**。
    """
    d = data_dir or DEFAULT_DATA_DIR
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, INDEX_FILE)

    recs = _fetch_sina_hs300()
    if not recs:
        print(f"[FETCH_INDEX] 全部重试失败，保留现有文件不动：{path}")
        return False

    fresh = pd.DataFrame(recs)
    existing = None
    if os.path.exists(path):
        try:
            existing = pd.read_csv(path)
        except Exception as exc:
            # 现有文件坏了也不删：仅用新数据写出（仍是合理超集），并告警
            print(f"[FETCH_INDEX] 现有文件读取失败（仅用新数据重写）：{exc}")
            existing = None

    try:
        merged = _merge(existing, fresh)
    except Exception as exc:
        print(f"[FETCH_INDEX] 合并失败，保留现有文件不动：{exc}")
        return False

    if merged.empty:
        print("[FETCH_INDEX] 合并后为空，保留现有文件不动")
        return False

    # 原子写：先写临时文件再替换，避免中途崩溃损坏 csv
    tmp = path + ".tmp"
    try:
        merged.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, path)
    except Exception as exc:
        print(f"[FETCH_INDEX] 写入失败，保留现有文件不动：{exc}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False

    print(
        f"[FETCH_INDEX] 写入 {len(merged)} 行 → {path}"
        f"（{merged['日期'].iloc[0]} ~ {merged['日期'].iloc[-1]}）"
    )
    return True


def main() -> int:
    # Windows cmd 默认 GBK，强制 UTF-8 避免日志乱码
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    ok = update_hs300_index()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
