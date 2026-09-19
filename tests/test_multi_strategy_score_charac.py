# -*- coding: utf-8 -*-
"""multi_strategy 评分钩子与 StrategyVoter 并列票型 characterization（q918-37）。

⚠ 红线自查：本文件**不写任何"该产品数值对不对"的期望**，只钉"今天这段码算了什么"。
所有数字都是当场构造的输入喂进 `StrategyVoter.vote()` 后**实测回填**的（探针脚本见 result 第五节），
不改 `multi_strategy.py` 一行。资金/统计结论的判断留给日间与多模型评审。

与存量测试的分工：
- `tests/test_characterization_multi_strategy.py`（18 例）已覆盖单策略百分位、两策略加权、空输入、
  两个 screen 的门槛、权重更新、报告文本、TrendFollowing 委托；
- 本单补它没碰的：并列/同分票型、零权重退化、同码重复、排名列口径、共识度分母、score_stock 桩。
可复跑：python -m pytest tests/test_multi_strategy_score_charac.py -q
"""
from __future__ import annotations

import pandas as pd
import pytest

from multi_strategy import (
    BaseStrategy,
    LowVolatilityStrategy,
    MeanReversionStrategy,
    StrategyVoter,
    TrendFollowingStrategy,
)


class _Strat:
    """最小策略替身：vote() 只用到 .name 与 .weight。"""

    def __init__(self, name, weight=1.0):
        self.name = name
        self.weight = weight


def _df(rows):
    """rows: [(代码, 综合评分, 最新价)]，列序与生产 screen() 输出一致。"""
    return pd.DataFrame(
        [{"代码": c, "名称": f"n{c}", "最新价": p, "涨跌幅": 0.0, "综合评分": s} for c, s, p in rows]
    )


# --- score_stock：一个没有任何实现、也没有任何调用方的钩子 ----------------------


def test_score_stock_is_unimplemented_stub_on_every_strategy():
    """任务书要求"score_stock 评分带直测"——磁盘实况是：`multi_strategy.py:43` 只有
    `raise NotImplementedError`，三个策略子类**一个都没覆写**（评分写在各自 screen() 里内联累加，
    如 MeanReversion :143-196 的 score+=25/15/10…）。真正的同名函数在另一个模块 `strategy.py:154`，
    其评分带由 `tests/test_strategy_core.py:150` 覆盖。"""
    with pytest.raises(NotImplementedError):
        BaseStrategy().score_stock(None, None)

    for cls in (TrendFollowingStrategy, MeanReversionStrategy, LowVolatilityStrategy):
        assert "score_stock" not in cls.__dict__, f"{cls.__name__} 覆写了 score_stock，本用例需重写"
        assert cls.score_stock is BaseStrategy.score_stock


def test_base_screen_is_also_an_untested_stub():
    """配对钉住：`:39 BaseStrategy.screen` 同样是 `raise NotImplementedError`，
    改前连这一条也没有用例（本单顺手补齐，不动生产码）。"""
    with pytest.raises(NotImplementedError):
        BaseStrategy().screen(pd.DataFrame(), pd.DataFrame())


def test_strategy_name_mismatch_silently_drops_that_strategy():
    """`vote()` 用 `all_results.get(strat.name)` 取数（:398）：策略名与结果字典的 key 对不上时
    该策略**静默不参与**，不报错也不警告。三个策略的 name 是中文串且被当作数据键用，
    存量测试里没人断言过 `TrendFollowingStrategy().name == '趋势跟随'`。"""
    voter = StrategyVoter([_Strat("趋势跟随")])
    out = voter.vote({"均值回归": _df([("600001", 90, 1), ("600002", 50, 2)])})

    assert out.shape == (0, 0)  # 名字对不上 → 等价于"全空"，而不是"该策略没数据"
    # 反证：同一个结果换个 key 就正常出票
    assert len(StrategyVoter([_Strat("均值回归")]).vote(
        {"均值回归": _df([("600001", 90, 1), ("600002", 50, 2)])})) == 2


# --- 并列 / 同分票型 -----------------------------------------------------------


def test_equal_scores_inside_one_strategy_are_spread_0_to_100():
    """同分不代表同分：三分组内 综合评分 全相等，百分位仍按 argsort 出来的名次摊成 100/50/0。

    实测顺序还与输入顺序**相反**（输入 600001/2/3 → 输出 600003/2/1）：
    `:408 scores.argsort()` 用默认 quicksort（非稳定），而 :407 注释写的是
    "ties按出现顺序，近似处理"——注释给的保证算法本身不提供。这里只钉现状。
    """
    out = StrategyVoter([_Strat("A")]).vote({"A": _df([("600001", 50, 1), ("600002", 50, 2), ("600003", 50, 3)])})

    assert list(out["代码"]) == ["600003", "600002", "600001"]
    assert list(out["最终得分"]) == [100.0, 50.0, 0.0]


def test_cross_strategy_reversal_ties_keep_first_seen_order():
    """两策略互为对方主场（A: X>Y，B: Y>X）→ 两者最终得分都是 50.0 并列；
    并列时的先后由 `sorted()` 的稳定性 + dict 插入序决定＝**首次被看到的代码在前**，
    与分数无关（换个输入顺序就会换个人排前面）。"""
    out = StrategyVoter([_Strat("A"), _Strat("B")]).vote(
        {"A": _df([("600001", 90, 1), ("600002", 10, 2)]),
         "B": _df([("600002", 90, 2), ("600001", 10, 1)])}
    )

    assert list(out["代码"]) == ["600001", "600002"]
    assert list(out["最终得分"]) == [50.0, 50.0]
    assert list(out["共识度"]) == ["2/2", "2/2"]
    assert out.loc[0, "各策略排名"] == {"A": 1, "B": 2}
    assert out.loc[1, "各策略排名"] == {"A": 2, "B": 1}


def test_unanimous_ranking_has_no_consensus_bonus():
    """v8 已删共识加成（:439-442 注释块）：3/3 共识的股票不会乘任何系数，得分就是百分位本身。"""
    same = _df([("600001", 90, 1), ("600002", 80, 2), ("600003", 70, 3)])
    out = StrategyVoter([_Strat("A"), _Strat("B"), _Strat("C")]).vote({"A": same, "B": same, "C": same})

    assert list(out["最终得分"]) == [100.0, 50.0, 0.0]
    assert list(out["共识度"]) == ["3/3"] * 3


def test_vote_docstring_still_advertises_the_deleted_bonus():
    """钉住文档漂移：`vote()` docstring 仍写"最终得分 = 百分位排名 × 共识加成"，
    而实现已于 v8 删掉加成。改 docstring 时本用例会红——那是预期的提醒，不是回归。"""
    assert "共识加成" in StrategyVoter.vote.__doc__
    assert "最终得分 = 百分位排名 × 共识加成" in StrategyVoter.vote.__doc__


# --- 退化路径 ------------------------------------------------------------------


def test_all_zero_weights_collapse_every_score_to_int_zero():
    """权重和为 0 时走 :446-447 else 分支 → 最终得分写成 int `0`（不是 0.0），
    列里 int/float 混型；且全员并列，排序完全退化成"首次出现顺序"。"""
    res = {"A": _df([("600001", 90, 1), ("600002", 50, 2)]),
           "B": _df([("600001", 90, 1), ("600002", 50, 2)])}
    out = StrategyVoter([_Strat("A", 0.0), _Strat("B", 0.0)]).vote(res)

    assert list(out["最终得分"]) == [0, 0]
    assert all(type(v) is int for v in out["最终得分"])  # 非 0.0
    assert list(out["共识度"]) == ["2/2", "2/2"]  # 共识度照算，哪怕分都是 0


def test_duplicate_code_in_one_strategy_double_counts_weight_and_overwrites_rank():
    """同一策略的 df 里代码重复时不做去重：权重和 1.0+1.0=2.0，
    `各策略排名` 被后一行覆盖（留下 2 而不是 1），最终得分变成两次百分位的平均。"""
    out = StrategyVoter([_Strat("A")]).vote({"A": _df([("600001", 90, 1), ("600001", 50, 2)])})

    assert len(out) == 1
    assert out.loc[0, "权重和"] == 2.0
    assert out.loc[0, "各策略排名"] == {"A": 2}
    assert out.loc[0, "最终得分"] == 50.0  # (100×1 + 0×1) / 2


def test_rank_column_is_row_order_while_percentile_is_score_order():
    """df 未按 综合评分 降序时两列口径打架：600002 拿满分位 100.0 却记"排名 2"，
    600001 分位 0.0 记"排名 1"。⇒ vote() 隐含要求 screen() 已排序
    （MeanRev :222 / LowVol :365 确实 sort_values 降序，TrendFollowing 委托 strategy.screen_stocks）。"""
    out = StrategyVoter([_Strat("A")]).vote({"A": _df([("600001", 10, 1), ("600002", 90, 2)])})

    top = out.iloc[0]
    assert top["代码"] == "600002" and top["最终得分"] == 100.0
    assert top["各策略排名"] == {"A": 2}  # 行序，不是分序
    assert out.iloc[1]["各策略排名"] == {"A": 1}


def test_consensus_denominator_counts_registered_strategies_not_participating():
    """注册 3 个但只有一个非空（另两个一个空 df、一个 None）→ 共识度写 "1/3" 而非 "1/1"：
    分母取 `self.n_strategies`（构造时的策略个数），与本轮是否真出票无关。"""
    out = StrategyVoter([_Strat("A"), _Strat("B"), _Strat("C")]).vote(
        {"A": _df([("600001", 90, 1)]), "B": pd.DataFrame(), "C": None}
    )

    assert list(out["共识度"]) == ["1/3"]
    assert list(out["最终得分"]) == [100.0]  # 组内 n==1 走 :412-413 分支，直接给 100


def test_all_strategies_empty_yields_columnless_frame():
    """全员空 → `pd.DataFrame()`（0 行 **0 列**），不是带表头的空表。
    下游若按列名取数（`generate_comparison_report` 之类）会 KeyError，而非拿到空序列。"""
    out = StrategyVoter([_Strat("A")]).vote({"A": pd.DataFrame()})

    assert out.empty and out.shape == (0, 0)
    assert list(out.columns) == []
    with pytest.raises(KeyError):
        out["最终得分"]


# --- initial_weights 形状 ------------------------------------------------------


def test_initial_weights_zip_silently_truncates():
    """`initial_weights` 比策略数短时，多出来的策略保持默认 1.0，不报错也不警告。"""
    a, b, c = _Strat("A", 1.0), _Strat("B", 1.0), _Strat("C", 1.0)
    voter = StrategyVoter([a, b, c], initial_weights=[3.0, 1.0])

    assert (voter.n_strategies, a.weight, b.weight) == (3, 3.0, 1.0)
    assert c.weight == 1.0  # 被 zip 丢掉，静默沿用旧值
