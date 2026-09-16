"""classify_sector characterization（916p-a1-004）。

只钉板块映射与分支优先级，纯函数零 I/O；
apply_sector_cap / detect_sector_concentration 的数值分支属资金红线，本单不测不碰
（AGENTS.md：小资金账户跳过板块集中度限制，其上限数值与仓位语义不在本单范围）。
可复跑：python -m pytest tests/test_sector_classifier_classify.py -q
"""
from sector_classifier import classify_sector


def test_empty_name_returns_other():
    """①name 为空 → 其他综合（:106 早返回）。"""
    assert classify_sector("600000", "") == "其他综合"
    assert classify_sector("600000", None) == "其他综合"


def test_bank_keyword_601():
    """②601 码名称含「银行」→ 银行金融（:111 银行特征分支）。"""
    assert classify_sector("601398", "工商银行") == "银行金融"


def test_bank_601_last_char_hang():
    """③601xxx 且名称末字为「行」→ 银行金融（:111 '行' == name[-1]）。"""
    assert classify_sector("601988", "中国银行") == "银行金融"
    assert classify_sector("601229", "上海银行") == "银行金融"


def test_keyword_beats_code_fallback():
    """④关键词命中优先于代码兜底（:115-118 循环在代码兜底 :122 之前）：
    600 码本应兜底「其他综合」，名称含单一明确关键词「医药」（避开「科技」等
    更靠前关键词）→ 医药生物。"""
    assert classify_sector("600123", "某某医药事业") == "医药生物"


def test_600_000_fallback_other():
    """⑤600/000 兜底 → 其他综合（:124-125）。"""
    assert classify_sector("600000", "浦发某股") == "其他综合"
    assert classify_sector("000001", "平安某股") == "其他综合"


def test_002_003_fallback_manufacturing():
    """⑥002/003 → 高端制造（:126-127）。"""
    assert classify_sector("002594", "某某股份") == "高端制造"
    assert classify_sector("003816", "某公司") == "高端制造"


def test_300_301_688_fallback_tech():
    """⑦300/301/688 → 科技TMT（:128-131）。"""
    assert classify_sector("300750", "宁德某") == "科技TMT"
    assert classify_sector("301269", "华大某") == "科技TMT"
    assert classify_sector("688981", "中芯某") == "科技TMT"


def test_non_six_digit_code_no_throw_with_fallback():
    """⑧非 6 位码 zfill 后走兜底，不抛异常且有板块返回（:110 zfill＋:134 else）。"""
    assert classify_sector("12345", "某股") == "其他综合"
    assert classify_sector("", "某股") == "其他综合"
    assert classify_sector("600000", "无关键词名") == "其他综合"


def test_601_non_bank_name_uses_keyword_then_fallback():
    """补充：601 名称无关键词 → 601 兜底银行金融；命中关键词 → 词表优先于 601 兜底
    （「某石油炼化」含词表「油」→ 食品饮料，证明关键词分支在 601 兜底之前）。"""
    assert classify_sector("601888", "中国中免") == "银行金融"
    assert classify_sector("601857", "某石油炼化") == "食品饮料"
