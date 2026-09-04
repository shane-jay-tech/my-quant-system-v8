# -*- coding: utf-8 -*-
"""特征测试（characterization）：陈旧文件与兜底红线 R2/R3/R5。

红线定义见 docs/optimization/2026-09-04/01-my-quant-system-v8-优化方案.md 第 6 节：
  R2 position_sizer.load_from_multi_vote 取"文件名倒序第一个" multi_vote，无日期校验
  R3 sim_trade.load_daily_orders 同样只取最新文件名，无日期校验
  R5 position_sizer.load_latest_picks 多源缺失时兜底读最新 stock csv 的 head(10)（买任意票）

CHARACTERIZATION：断言固化"现状"。数据全部位于 tmp_path，
通过 monkeypatch 模块目录常量隔离，严禁触碰真实 data/ orders/ sim_results/。
日间修复（加日期校验/移除兜底）后应更新期望值。
"""
import json

import pandas as pd
import pytest

import position_sizer
import sim_trade


class TestR2StaleMultiVote:
    """R2：两周前的 multi_vote 文件会被无校验消费。"""

    def test_old_vote_file_consumed_without_date_check(self, tmp_path, monkeypatch, capsys):
        votes = [{"代码": "600000", "名称": "浦发银行", "最新价": 10.0,
                  "涨跌幅": 1.0, "最终得分": 80}]
        (tmp_path / "multi_vote_20260820.json").write_text(
            json.dumps(votes, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(position_sizer, "ORDERS_DIR", str(tmp_path))
        df = position_sizer.load_from_multi_vote()

        # 现状：旧文件被照常加载为选股结果（无任何"文件日期 vs 今日"检查）
        assert df is not None and len(df) == 1
        assert df.iloc[0]["代码"] == "600000"

    def test_newer_file_wins_by_name_order(self, tmp_path, monkeypatch):
        """对照：文件名倒序决定消费对象——这正是"无日期校验"的机理。"""
        (tmp_path / "multi_vote_20260820.json").write_text(
            json.dumps([{"代码": "600001", "名称": "旧", "最新价": 10.0}],
                       ensure_ascii=False), encoding="utf-8")
        (tmp_path / "multi_vote_20260901.json").write_text(
            json.dumps([{"代码": "600002", "名称": "新", "最新价": 11.0}],
                       ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(position_sizer, "ORDERS_DIR", str(tmp_path))
        df = position_sizer.load_from_multi_vote()
        assert df.iloc[0]["代码"] == "600002"


class TestR3StaleDailyOrders:
    """R3：旧日期 daily_orders 会被当日 sim_trade 无校验消费。"""

    def test_old_orders_file_consumed_without_date_check(self, tmp_path, monkeypatch):
        payload = {"订单": [{"代码": "600000", "名称": "浦发银行",
                             "股数": 100, "金额": 1000.0}]}
        (tmp_path / "daily_orders_20260801.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(sim_trade, "ORDERS_DIR", str(tmp_path))
        orders = sim_trade.load_daily_orders()

        # 现状：8/1 的订单文件被原样返回（无日期校验、无"是否为最新交易日"检查）
        assert orders == payload["订单"]


class TestR5FallbackTop10:
    """R5：多策略与 pick 报告双缺失时，兜底取最新 stock csv 的前 10 行（买任意票）。"""

    def test_both_missing_falls_back_to_head10(self, tmp_path, monkeypatch):
        orders_dir = tmp_path / "orders"
        data_dir = tmp_path / "data"
        results_dir = tmp_path / "results"
        orders_dir.mkdir()
        data_dir.mkdir()
        results_dir.mkdir()
        # 15 只股票的最新 csv（含 ST 股以验证过滤仍在兜底前生效）
        rows = [{"代码": f"{600000+i:06d}", "名称": ("ST危" if i == 0 else f"股票{i}"),
                 "最新价": 10.0 + i, "涨跌幅": 1.0} for i in range(15)]
        pd.DataFrame(rows).to_csv(data_dir / "stock_20260904.csv",
                                  index=False, encoding="utf-8")

        monkeypatch.setattr(position_sizer, "ORDERS_DIR", str(orders_dir))
        monkeypatch.setattr(position_sizer, "RESULTS_DIR", str(results_dir))
        monkeypatch.setattr(position_sizer, "DATA_DIR", str(data_dir))

        df = position_sizer.load_latest_picks()

        # 现状：返回 head(10) —— 等价于"按代码序买前 10 只"，与策略无关
        assert len(df) == 10
        assert "ST危" not in df["名称"].tolist()
