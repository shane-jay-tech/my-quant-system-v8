"""fetch_etf_data 纯函数零覆盖补齐（916p-a1-003）。

只测不上网：本文件仅触达 code_to_sina_symbol / looks_like_etf /
_parse_sina_list / merge_codes_from_sources（requests 路径零调用、零 monkeypatch
需求——不 import 触网函数即可）。只断言「代码→市场前缀」「是否 ETF」「解析结构」；
涨跌幅仅断言公式与舍入位数。禁止断言任何资金/收益/统计数值。
可复跑：python -m pytest tests/test_fetch_etf_data_pure.py -q
"""
import fetch_etf_data as m


# ── ① code_to_sina_symbol：代码→市场前缀（:46）──

def test_code_to_sina_symbol_shanghai_etf():
    assert m.code_to_sina_symbol("510300") == "sh510300"
    assert m.code_to_sina_symbol("588000") == "sh588000"


def test_code_to_sina_symbol_shenzhen_etf():
    assert m.code_to_sina_symbol("159915") == "sz159915"


def test_code_to_sina_symbol_beijing_and_fallback():
    """8/9 开头 → bj（:55-56）；任务书示例 430047（4 开头）实际走最终兜底 sz
    （实现无 '4' 分支，落到 :57 return sz）——按现状如实断言，规格差异留报告。"""
    assert m.code_to_sina_symbol("830799") == "bj830799"
    assert m.code_to_sina_symbol("920099") == "bj920099"
    assert m.code_to_sina_symbol("430047") == "sz430047"


def test_code_to_sina_symbol_zfill_short_code():
    """短码补零到 6 位（:51 zfill）。"""
    assert m.code_to_sina_symbol("300") == "sz000300"
    assert m.code_to_sina_symbol(510300) == "sh510300"  # int 入参同容


# ── ② looks_like_etf：首位近似判定（:63）──

def test_looks_like_etf_true_for_5_and_1_prefix():
    assert m.looks_like_etf("510300") is True
    assert m.looks_like_etf("159915") is True


def test_looks_like_etf_false_for_stock_prefixes():
    assert m.looks_like_etf("600000") is False
    assert m.looks_like_etf("000001") is False
    assert m.looks_like_etf("300750") is False


# ── ③ _parse_sina_list：解析结构（:151）──

def test_parse_sina_list_normal_line_full_fields():
    """正常一行 → 键为 6 位码、8 个约定字段齐全（:186-195 结构契约）。"""
    line = 'var hq_str_sh510300="沪深300ETF,4.000,4.010,4.050,4.060,3.990,0,0,123456,7890.0,0,0";'
    rows = m._parse_sina_list(line, ["510300"])
    assert set(rows.keys()) == {"510300"}
    row = rows["510300"]
    assert set(row.keys()) == {"代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "换手率", "流通市值"}
    assert row["名称"] == "沪深300ETF"
    # 涨跌幅仅断言公式与舍入位数：(latest-prev)/prev*100 保留 4 位
    assert row["涨跌幅"] == round((4.050 - 4.000) / 4.000 * 100, 4)


def test_parse_sina_list_skips_short_payload_without_error():
    """字段不足 10 个 → 跳过不报错（:165-168 停牌/退市容错）。"""
    line = 'var hq_str_sh510300="沪深300ETF,4.000,4.010"'
    assert m._parse_sina_list(line, ["510300"]) == {}


def test_parse_sina_list_skips_non_target_codes():
    """非目标代码（不在 original_codes）→ 不返回（:159 code_set 过滤）。"""
    line = 'var hq_str_sh600000="浦发银行,1.0,1.0,1.0,1.0,1.0,0,0,0,0,0,0";'
    assert m._parse_sina_list(line, ["510300"]) == {}


# ── ④ merge_codes_from_sources：无来源文件 → 空且不抛错（:101）──

def test_merge_codes_from_sources_empty_when_no_files(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "WATCHLIST_PATH", tmp_path / "no_watchlist.json")
    monkeypatch.setattr(m, "REAL_TRADES_PATH", tmp_path / "no_trades.csv")
    assert m.merge_codes_from_sources() == []
