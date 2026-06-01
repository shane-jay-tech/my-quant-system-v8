"""Tests for fetch_index.py — 沪深300基准刷新（全系统单一写入源）。

覆盖：
    - 合并：新数据覆盖同日旧值、保留更早历史、升序、无重复日期
    - 无 existing 时直接用新数据
    - 网络失败 / 空数据 → 返回 False 且**绝不破坏现有文件**
    - 成功写出为 utf-8-sig、列名 日期/收盘、升序

注意：全部用 monkeypatch 假造网络返回，**不真打网络**。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import fetch_index


class TestMerge:
    def test_dedup_new_overrides_and_preserves_history(self, tmp_path):
        path = tmp_path / "hs300_index.csv"
        path.write_text(
            "日期,收盘\n2025-07-23,4000.0\n2026-05-22,4845.0\n", encoding="utf-8-sig"
        )
        existing = pd.read_csv(path)
        fresh = pd.DataFrame(
            [
                {"日期": "2026-05-22", "收盘": 9999.0},  # 同日 → 应被新值覆盖
                {"日期": "2026-06-16", "收盘": 4884.0},  # 新日 → 追加
            ]
        )
        merged = fetch_index._merge(existing, fresh)
        d = dict(zip(merged["日期"].astype(str), merged["收盘"]))
        assert d["2025-07-23"] == 4000.0   # 历史保留
        assert d["2026-05-22"] == 9999.0   # 新覆盖旧
        assert d["2026-06-16"] == 4884.0   # 新追加
        dates = list(merged["日期"].astype(str))
        assert dates == sorted(dates)            # 升序
        assert merged["日期"].duplicated().sum() == 0  # 无重复

    def test_merge_without_existing(self, tmp_path):
        fresh = pd.DataFrame([{"日期": "2026-06-16", "收盘": 4884.0}])
        merged = fetch_index._merge(None, fresh)
        assert list(merged.columns) == ["日期", "收盘"]
        assert len(merged) == 1


class TestUpdate:
    def test_success_writes_utf8sig_ascending(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            fetch_index,
            "_fetch_sina_hs300",
            lambda: [
                {"日期": "2026-06-16", "收盘": 4884.0},
                {"日期": "2026-06-15", "收盘": 4891.0},  # 故意乱序，验证写出时已排序
            ],
        )
        ok = fetch_index.update_hs300_index(str(tmp_path))
        assert ok is True
        path = tmp_path / "hs300_index.csv"
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM
        df = pd.read_csv(path)
        assert "日期" in df.columns and "收盘" in df.columns
        assert list(df["日期"].astype(str)) == ["2026-06-15", "2026-06-16"]

    def test_network_failure_keeps_existing(self, tmp_path, monkeypatch):
        path = tmp_path / "hs300_index.csv"
        original = "日期,收盘\n2026-05-22,4845.0\n"
        path.write_text(original, encoding="utf-8-sig")
        monkeypatch.setattr(fetch_index, "_fetch_sina_hs300", lambda: None)
        ok = fetch_index.update_hs300_index(str(tmp_path))
        assert ok is False
        assert path.read_text(encoding="utf-8-sig") == original  # 原样保留

    def test_empty_data_keeps_existing(self, tmp_path, monkeypatch):
        path = tmp_path / "hs300_index.csv"
        original = "日期,收盘\n2026-05-22,4845.0\n"
        path.write_text(original, encoding="utf-8-sig")
        monkeypatch.setattr(fetch_index, "_fetch_sina_hs300", lambda: [])
        ok = fetch_index.update_hs300_index(str(tmp_path))
        assert ok is False
        assert path.read_text(encoding="utf-8-sig") == original
