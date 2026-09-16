# -*- coding: utf-8 -*-
"""特征测试（characterization）：multi_strategy.py 的当前行为。

背景：refactor-blueprint-20260907.md S1 阶段卡——multi_strategy 覆盖率 0% 为 P0
盲区，重构前先钉住现状（golden master）。CHARACTERIZATION：断言固化"现状"，
不是"正确值"；日间重构后若本文件 diff 出现变化，即为行为变化清单。

钉桩范围（纯逻辑优先，精确断言；pandas 重分支钉在档位/门控级别）：
  - StrategyVoter.vote：百分位排名 × 权重、最终得分=加权/权重和、共识度（手算精确值）
  - LowVolatilityStrategy.screen：常数序列的 35+5+0+20=60 分路径（手算精确值）
  - MeanReversionStrategy.screen：ST/市值/历史长度/RSI 门控的排除路径 + 入选 schema
  - update_strategy_weights：softmax+平滑更新的精确值（DATA_DIR 重定向 tmp，data/ 零触碰）
  - generate_comparison_report：表头/权重表/重叠矩阵/高共识节（字符串精确断言）
  - TrendFollowingStrategy：惰性 import 委托路径（注入假 strategy 模块，不触真模块）

全部使用合成 DataFrame 与 pytest tmp_path，严禁触碰真实 data/、results/、orders/
（tests/conftest.py 护栏继续生效；投票器/报告测试不发任何写盘）。
"""
import sys
import types

import pandas as pd
import pytest

import multi_strategy
from multi_strategy import (
    FINAL_TOP_N,
    TOP_N_PER_STRATEGY,
    LowVolatilityStrategy,
    MeanReversionStrategy,
    StrategyVoter,
    TrendFollowingStrategy,
    generate_comparison_report,
    update_strategy_weights,
)


# ---------------------------------------------------------------- --
# 合成数据工具
# ---------------------------------------------------------------- --
def _today(rows):
    """today_df：代码/名称/流通市值/涨跌幅。"""
    return pd.DataFrame(
        [
            {
                '代码': code,
                '名称': name,
                '流通市值': mcap,
                '涨跌幅': chg,
            }
            for code, name, mcap, chg in rows
        ]
    )


def _hist(series_by_code):
    """history_df：代码/日期/收盘/最高/最低/成交量。series_by_code: {code: [收盘...]}"""
    frames = []
    for code, closes in series_by_code.items():
        n = len(closes)
        frames.append(
            pd.DataFrame(
                {
                    '代码': [code] * n,
                    '日期': pd.date_range('2026-05-01', periods=n, freq='D'),
                    '收盘': closes,
                    '最高': [c * 1.01 for c in closes],
                    '最低': [c * 0.99 for c in closes],
                    '成交量': [10000.0] * n,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _oscillating(base=20.0, drift=0.999, up=1.01, down=0.99, days=80):
    """围绕温和下行趋势的 ±1% 震荡序列（RSI 天然落在中性区，MA20>现价）。"""
    price = base
    closes = []
    for k in range(days):
        price *= drift * (up if k % 2 == 0 else down)
        closes.append(round(price, 4))
    return closes


# ---------------------------------------------------------------- --
# 常量钉桩
# ---------------------------------------------------------------- --
class TestModuleConstants:
    def test_pins(self):
        assert TOP_N_PER_STRATEGY == 15
        assert FINAL_TOP_N == 20
        assert multi_strategy.WEIGHT_WINDOW == 20
        assert multi_strategy.WEIGHT_SMOOTH == 0.3

    def test_strategy_defaults(self):
        mr = MeanReversionStrategy()
        lv = LowVolatilityStrategy()
        assert (mr.name, mr.weight, mr.MCAP_MIN) == ('均值回归', 1.0, 5e9)
        assert (lv.name, lv.weight, lv.MCAP_MIN) == ('低波动率', 1.0, 5e9)


# ---------------------------------------------------------------- --
# StrategyVoter.vote —— 手算精确值
# ---------------------------------------------------------------- --
class TestVoterExact:
    def _res(self, rows):
        return pd.DataFrame(rows)

    def test_single_strategy_percentile_and_order(self):
        s = MeanReversionStrategy()  # weight 1.0
        df = self._res(
            [
                {'代码': '600001', '名称': 'A', '最新价': 30.0, '综合评分': 30},
                {'代码': '600002', '名称': 'B', '最新价': 20.0, '综合评分': 20},
                {'代码': '600003', '名称': 'C', '最新价': 10.0, '综合评分': 10},
            ]
        )
        out = StrategyVoter([s]).vote({'均值回归': df})
        # 百分位：n=3 → (r-1)/(n-1)*100 → [100, 50, 0]；权重 1.0 → 最终得分同值
        assert out['代码'].tolist() == ['600001', '600002', '600003']
        assert out['最终得分'].tolist() == [100.0, 50.0, 0.0]
        assert out['共识度'].tolist() == ['1/1', '1/1', '1/1']
        assert out['各策略排名'][0] == {'均值回归': 1}

    def test_weighted_two_strategies_consensus(self):
        s1 = MeanReversionStrategy()  # w=1.0
        s2 = LowVolatilityStrategy()  # w=1.0 → 改权重模拟
        s2.weight = 0.5
        d1 = self._res(
            [
                {'代码': '600001', '名称': 'A', '最新价': 30.0, '综合评分': 30},
                {'代码': '600002', '名称': 'B', '最新价': 20.0, '综合评分': 20},
            ]
        )
        d2 = self._res([{'代码': '600001', '名称': 'A', '最新价': 30.0, '综合评分': 10}])
        out = StrategyVoter([s1, s2]).vote({'均值回归': d1, '低波动率': d2})
        # A：pct=100(策略1,n=2 第一名) + 100(策略2,n=1 单元素=100)；加权=(100*1+100*0.5)/1.5=100.0
        # B：pct=0(策略1 第二名) → 0.0
        assert out['代码'].tolist() == ['600001', '600002']
        assert out['最终得分'].tolist() == [100.0, 0.0]
        # 现状：共识度分母 = 策略总数（2），未参与的策略不补权重
        assert out['共识度'].tolist() == ['2/2', '1/2']
        assert out['各策略得分'][0] == {'均值回归': 30, '低波动率': 10}

    def test_all_empty_returns_empty(self):
        s = MeanReversionStrategy()
        out = StrategyVoter([s]).vote({'均值回归': pd.DataFrame()})
        assert isinstance(out, pd.DataFrame)
        assert len(out) == 0


# ---------------------------------------------------------------- --
# LowVolatilityStrategy.screen —— 常数序列手算精确路径
# ---------------------------------------------------------------- --
class TestLowVolScreen:
    def test_constant_series_exact_score_60(self):
        """常数价格：ann_vol=0(+35)、ret_20d=0(+5)、sharpe=0(vol20=0 走 else 分支 +0)、
        drawdown=0(+20) → 现状总分 60，理由串 '极低波动 + 极小回撤'。"""
        closes = [10.0] * 40
        today = _today([('600100', '常数股', 6e9, 0.0)])
        hist = _hist({'600100': closes})
        out = LowVolatilityStrategy().screen(today, hist)
        assert len(out) == 1
        row = out.iloc[0]
        assert row['代码'] == '600100'
        assert row['年化波动率%'] == 0.0
        assert row['20日收益%'] == 0.0
        assert row['Sharpe'] == 0.0
        assert row['最大回撤%'] == 0.0
        assert row['综合评分'] == 60
        assert row['选入理由'] == '极低波动 + 极小回撤'
        assert row['流通市值_亿'] == 60.0  # 6e9/1e8

    def test_high_volatility_excluded(self):
        closes = [10.5, 9.5] * 20  # 剧烈震荡 → 年化波动率远超 45% 上限
        today = _today([('600200', '震荡股', 6e9, 0.0)])
        out = LowVolatilityStrategy().screen(today, _hist({'600200': closes}))
        assert len(out) == 0

    def test_steady_decline_excluded_by_ret20d_gate(self):
        closes = [round(10.0 * (0.99 ** k), 4) for k in range(40)]  # 每日 -1%
        today = _today([('600300', '阴跌股', 6e9, 0.0)])
        out = LowVolatilityStrategy().screen(today, _hist({'600300': closes}))
        # 现状：波动率门通过（常数涨跌幅 → std≈0），被 近20日收益<-12% 门排除
        assert len(out) == 0

    def test_short_history_excluded(self):
        closes = [10.0] * 29  # <30 行直接跳过
        today = _today([('600400', '短史股', 6e9, 0.0)])
        out = LowVolatilityStrategy().screen(today, _hist({'600400': closes}))
        assert len(out) == 0


# ---------------------------------------------------------------- --
# MeanReversionStrategy.screen —— 门控排除路径 + 入选 schema
# ---------------------------------------------------------------- --
class TestMeanReversionScreen:
    def test_all_gates_exclude(self):
        hist = _hist(
            {
                '600001': [round(20.0 * (1.02 ** k), 4) for k in range(80)],  # 上升 → price>MA20
                '600002': [round(20.0 * (0.98 ** k), 4) for k in range(80)],  # 崩跌 → price<0.85*MA60
                '600003': _oscillating()[:59],  # 历史 <60 行
            }
        )
        today = _today(
            [
                ('600001', '上升股', 6e9, 1.0),
                ('600002', '崩跌股', 6e9, -2.0),
                ('600003', '短史股', 6e9, 0.0),
                ('600004', 'ST 探路', 6e9, 0.0),  # ST 排除
                ('600005', '小市值', 4e9, 0.0),  # 市值 <5e9 排除
            ]
        )
        hist = pd.concat([hist, _hist({'600004': _oscillating(), '600005': _oscillating()})], ignore_index=True)
        out = MeanReversionStrategy().screen(today, hist)
        assert len(out) == 0

    def test_oscillating_downtrend_included_with_schema(self):
        closes = _oscillating()
        today = _today([('600600', '震荡股', 6e9, -0.5)])
        out = MeanReversionStrategy().screen(today, _hist({'600600': closes}))
        assert len(out) == 1
        row = out.iloc[0]
        assert row['代码'] == '600600'
        assert list(out.columns) == [
            '代码', '名称', '最新价', '涨跌幅', 'MA20', 'RSI', '偏离MA20%',
            '量比', '流通市值_亿', '综合评分', '选入理由',
        ]
        # 现状：该震荡序列的钉桩得分恰为 45（np.int64），属确定性工程数据的手算锚点
        assert int(row['综合评分']) == 45
        assert row['选入理由']  # 非空
        assert row['偏离MA20%'] > 0  # 现状门控：入选者必 price<MA20
        assert 25 < row['RSI'] < 55  # RSI 门控上下界钉桩

    def test_results_sorted_by_score_desc(self):
        closes_a = _oscillating()
        closes_b = list(reversed(closes_a))  # 同族不同形态，触发不同档位
        today = _today([('600601', '甲', 6e9, 0.0), ('600602', '乙', 6e9, 0.0)])
        out = MeanReversionStrategy().screen(today, _hist({'600601': closes_a, '600602': closes_b}))
        if len(out) >= 2:
            scores = out['综合评分'].tolist()
            assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------- --
# update_strategy_weights —— DATA_DIR 重定向 tmp，data/ 零触碰
# ------------------------------------------------------------------
class TestUpdateWeights:
    def _strats(self):
        return [MeanReversionStrategy(), LowVolatilityStrategy()]

    def _write_forward(self, path, rows):
        pd.DataFrame(rows, columns=['策略', '5日收益']).to_csv(path, index=False)

    def test_softmax_smooth_exact_values(self, tmp_path, monkeypatch):
        monkeypatch.setattr(multi_strategy, 'DATA_DIR', str(tmp_path))
        self._write_forward(
            tmp_path / 'fwd.csv',
            [('均值回归', 0.10), ('均值回归', -0.02), ('低波动率', -0.01), ('低波动率', -0.02)],
        )
        strats = self._strats()
        update_strategy_weights(strats, str(tmp_path / 'fwd.csv'))
        # scores: 均值回归=0.5*0.6+(0.04/0.05)*0.4=0.62；低波动率=0
        # softmax([0.62,0])≈[0.650219,0.349781]；平滑 0.5*0.7+w*0.3 → 现状实测 0.545066/0.454934
        assert strats[0].weight == pytest.approx(0.545066, abs=1e-5)
        assert strats[1].weight == pytest.approx(0.454934, abs=1e-5)
        import json
        saved = json.loads((tmp_path / 'strategy_weights.json').read_text(encoding='utf-8'))
        assert saved['current_weights'] == {'均值回归': 0.5451, '低波动率': 0.4549}
        assert len(saved['records']) == 1
        assert saved['records'][0]['scores'] == {'均值回归': 0.62, '低波动率': 0.0}

    def test_records_capped_at_60(self, tmp_path, monkeypatch):
        monkeypatch.setattr(multi_strategy, 'DATA_DIR', str(tmp_path))
        history = {
            'records': [{'date': f'seed-{i:02d}', 'scores': {}, 'weights': {}} for i in range(65)],
            'current_weights': {},
        }
        import json
        (tmp_path / 'strategy_weights.json').write_text(
            json.dumps(history, ensure_ascii=False), encoding='utf-8'
        )
        self._write_forward(tmp_path / 'fwd.csv', [('均值回归', 0.01), ('低波动率', 0.01)])
        update_strategy_weights(self._strats(), str(tmp_path / 'fwd.csv'))
        saved = json.loads((tmp_path / 'strategy_weights.json').read_text(encoding='utf-8'))
        assert len(saved['records']) == 60  # 现状：追加后裁到最近 60 条
        assert saved['records'][0]['date'] == 'seed-06'  # 65+1=66 条 → 裁掉最旧 6 条

    def test_no_forward_file_uses_stored_weights(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(multi_strategy, 'DATA_DIR', str(tmp_path))
        import json
        stored = {'records': [], 'current_weights': {'均值回归': 0.7, '低波动率': 0.3}}
        (tmp_path / 'strategy_weights.json').write_text(
            json.dumps(stored, ensure_ascii=False), encoding='utf-8'
        )
        strats = self._strats()
        update_strategy_weights(strats, None)
        assert strats[0].weight == pytest.approx(0.7)
        assert strats[1].weight == pytest.approx(0.3)
        assert '[VOTER] Using stored weights' in capsys.readouterr().out


# ---------------------------------------------------------------- --
# generate_comparison_report —— 字符串精确断言
# ---------------------------------------------------------------- --
class TestComparisonReport:
    def _vote(self, strategies, all_results):
        return StrategyVoter(strategies).vote(all_results)

    def test_report_structure_and_overlap(self):
        s1, s2 = MeanReversionStrategy(), LowVolatilityStrategy()
        d1 = pd.DataFrame(
            [
                {'代码': '600300', '名称': '甲', '最新价': 10.0, '综合评分': 80, 'RSI': 40.0, '量比': 1.2},
                {'代码': '600400', '名称': '乙', '最新价': 20.0, '综合评分': 60, 'RSI': 35.0, '量比': 0.9},
            ]
        )
        d2 = pd.DataFrame(
            [
                {'代码': '600300', '名称': '甲', '最新价': 10.0, '综合评分': 70, '年化波动率%': 15.0, 'Sharpe': 2.0},
                {'代码': '600500', '名称': '丙', '最新价': 30.0, '综合评分': 50, '年化波动率%': 20.0, 'Sharpe': 1.0},
            ]
        )
        all_results = {'均值回归': d1, '低波动率': d2}
        vote = self._vote([s1, s2], all_results)
        report = generate_comparison_report(all_results, vote, [s1, s2], '2026-09-08')

        assert '# 多策略对比报告 — 2026-09-08' in report
        assert '| 均值回归 | 1.000 |' in report  # 默认权重 1.0，三位小数
        assert '| 低波动率 | 1.000 |' in report
        assert '| 均值回归 vs 低波动率 | 1 | 50% |' in report  # 交集{600300}/min(2,2)
        assert '600300' in report.split('## 高共识股票')[1]  # 2/2 共识股进高共识节
        assert report.rstrip().endswith('自动生成*')

    def test_empty_strategy_section(self):
        s = MeanReversionStrategy()
        report = generate_comparison_report({'均值回归': pd.DataFrame()}, pd.DataFrame(), [s], '2026-09-08')
        assert '*无符合条件的股票*' in report
        assert '| 均值回归 vs 低波动率 | N/A | N/A |' not in report  # 单策略无对比行
        assert '*无投票结果*' in report


# ---------------------------------------------------------------- --
# TrendFollowingStrategy —— 惰性 import 委托（不触真 strategy 模块）
# ------------------------------------------------------------------
class TestTrendDelegation:
    def test_screen_delegates_to_strategy_screen_stocks(self, monkeypatch):
        sentinel = pd.DataFrame([{'代码': '000001', '综合评分': 99}])
        fake = types.ModuleType('strategy')
        fake.screen_stocks = lambda today_df, history_df: sentinel
        monkeypatch.setitem(sys.modules, 'strategy', fake)
        out = TrendFollowingStrategy().screen(pd.DataFrame(), pd.DataFrame())
        assert out is sentinel
