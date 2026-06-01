"""
A股行业分类 v1 — 基于股票名称关键词的快速行业映射

规则优先级：
1. 名称关键词匹配（如"电力"→电力能源）
2. 代码规则（如601xxx→银行/券商，600xxx→主板通用）
3. 兜底：其他综合
"""
import re

# 关键词 → 板块名（按优先级排列，先匹配到的生效）
SECTOR_KEYWORDS = {
    # 电力能源
    '电力': '电力能源', '电投': '电力能源', '能源': '电力能源', '华能': '电力能源',
    '华电': '电力能源', '国电': '电力能源', '大唐': '电力能源', '核电': '电力能源',
    '风电': '电力能源', '光伏': '电力能源', '太阳能': '电力能源', '节能': '电力能源',
    '新能源': '电力能源', '长江电力': '电力能源', '涪陵电力': '电力能源',

    # 银行
    '银行': '银行金融',

    # 保险/券商/信托
    '保险': '银行金融', '证券': '银行金融', '券商': '银行金融', '信托': '银行金融',
    '期货': '银行金融', '金控': '银行金融', '资管': '银行金融',

    # 房地产
    '地产': '地产建筑', '房产': '地产建筑', '万科': '地产建筑', '保利': '地产建筑',
    '建筑': '地产建筑', '建材': '地产建筑', '水泥': '地产建筑', '玻璃': '地产建筑',
    '装饰': '地产建筑', '园林': '地产建筑',

    # 科技TMT
    '科技': '科技TMT', '软件': '科技TMT', '网络': '科技TMT', '信息': '科技TMT',
    '数据': '科技TMT', '通信': '科技TMT', '电子': '科技TMT', '半导体': '科技TMT',
    '芯片': '科技TMT', '集成': '科技TMT', '计算机': '科技TMT', '互联': '科技TMT',
    '智能': '科技TMT', '数字': '科技TMT', '云': '科技TMT', '讯': '科技TMT',
    '微': '科技TMT', '光电': '科技TMT', '光学': '科技TMT', '电路': '科技TMT',

    # 高端制造
    '制造': '高端制造', '机械': '高端制造', '设备': '高端制造', '机器': '高端制造',
    '重工': '高端制造', '电气': '高端制造', '电器': '高端制造', '电机': '高端制造',
    '工程': '高端制造', '工业': '高端制造', '精密': '高端制造', '仪器': '高端制造',
    '自动化': '高端制造', '机器人': '高端制造',

    # 汽车
    '汽车': '汽车产业链', '汽配': '汽车产业链', '轮胎': '汽车产业链',
    '比亚迪': '汽车产业链', '长城': '汽车产业链', '吉利': '汽车产业链',
    '锂': '汽车产业链', '电池': '汽车产业链', '充电': '汽车产业链',

    # 化工
    '化工': '化工材料', '化学': '化工材料', '石化': '化工材料', '化纤': '化工材料',
    '塑料': '化工材料', '橡胶': '化工材料', '涂料': '化工材料', '染料': '化工材料',
    '化肥': '化工材料', '农药': '化工材料', '碳': '化工材料',

    # 有色/钢铁/煤炭
    '钢': '有色资源', '铁': '有色资源', '煤': '有色资源', '矿': '有色资源',
    '铝': '有色资源', '铜': '有色资源', '锌': '有色资源', '黄金': '有色资源',
    '稀土': '有色资源', '钨': '有色资源', '钛': '有色资源', '镍': '有色资源',
    '有色': '有色资源', '资源': '有色资源',

    # 医药
    '医药': '医药生物', '药业': '医药生物', '制药': '医药生物', '生物': '医药生物',
    '医疗': '医药生物', '基因': '医药生物', '疫苗': '医药生物', '诊断': '医药生物',
    '器械': '医药生物', '中药': '医药生物', '药': '医药生物',

    # 食品饮料/白酒
    '酒': '食品饮料', '食品': '食品饮料', '饮料': '食品饮料', '乳': '食品饮料',
    '粮': '食品饮料', '油': '食品饮料', '肉': '食品饮料', '调味': '食品饮料',
    '盐': '食品饮料', '糖': '食品饮料',

    # 交通物流
    '航空': '交通物流', '机场': '交通物流', '港口': '交通物流', '高速': '交通物流',
    '铁路': '交通物流', '公路': '交通物流', '物流': '交通物流', '运输': '交通物流',
    '交运': '交通物流', '船舶': '交通物流', '海运': '交通物流',

    # 传媒娱乐
    '传媒': '传媒娱乐', '影视': '传媒娱乐', '出版': '传媒娱乐', '广电': '传媒娱乐',
    '游戏': '传媒娱乐', '广告': '传媒娱乐', '娱乐': '传媒娱乐', '文化': '传媒娱乐',
    '教育': '传媒娱乐', '体育': '传媒娱乐', '旅游': '传媒娱乐',

    # 军工
    '军工': '军工航天', '航天': '军工航天', '航空': '军工航天', '兵器': '军工航天',
    '导航': '军工航天', '卫星': '军工航天', '雷达': '军工航天', '防务': '军工航天',

    # 环保
    '环保': '环保公用', '水务': '环保公用', '供水': '环保公用', '燃气': '环保公用',
    '供热': '环保公用', '公用': '环保公用',
}


def classify_sector(code, name):
    """
    根据股票代码+名称进行行业分类

    Args:
        code: 股票代码 (如 '000001')
        name: 股票名称 (如 '平安银行')

    Returns:
        str: 板块名称
    """
    if not name:
        return '其他综合'

    # 代码规则先判断（用于兜底和修正）
    code_str = str(code).zfill(6)

    # 银行股代码特征
    if code_str.startswith('601') and ('银行' in name or '行' == name[-1]):
        return '银行金融'

    # 关键词匹配（按优先级）
    for keyword, sector in SECTOR_KEYWORDS.items():
        if keyword in str(name):
            return sector

    # 代码兜底
    if code_str.startswith('601'):
        return '银行金融'  # 多数601为金融地产
    elif code_str.startswith('600') or code_str.startswith('000'):
        return '其他综合'
    elif code_str.startswith('002') or code_str.startswith('003'):
        return '高端制造'  # 中小板偏制造
    elif code_str.startswith('300') or code_str.startswith('301'):
        return '科技TMT'   # 创业板偏科技
    elif code_str.startswith('688'):
        return '科技TMT'   # 科创板
    else:
        return '其他综合'


def detect_sector_concentration(stocks, max_per_sector=3):
    """
    检测板块集中度风险

    Args:
        stocks: list of dict, 每只股票需含 '代码'/'code', '名称'/'name', '综合评分'/'score'
        max_per_sector: 单个板块最大股票数，超过则标记

    Returns:
        tuple: (stocks_with_sector_tags, sector_stats, warnings)
            - stocks: 添加了 '板块' 和 '集中风险' 字段
            - sector_stats: {板块: 股票数}
            - warnings: 风险提示列表
    """
    for s in stocks:
        code = s.get('代码', s.get('code', ''))
        name = s.get('名称', s.get('name', ''))
        s['板块'] = classify_sector(code, name)
        s['集中风险'] = False

    # 统计板块分布
    sector_stats = {}
    for s in stocks:
        sec = s['板块']
        sector_stats[sec] = sector_stats.get(sec, 0) + 1

    # 标记集中风险
    warnings = []
    for sec, count in sector_stats.items():
        if count >= max_per_sector:
            # 找到该板块中得分最低的股票
            sec_stocks = [s for s in stocks if s['板块'] == sec]
            sec_stocks_sorted = sorted(sec_stocks, key=lambda x: x.get('综合评分', x.get('score', 0)))
            # 标记超额部分（最低分的那些）
            excess = count - max_per_sector + 1  # 标记多余的数量
            for i in range(min(excess, len(sec_stocks_sorted))):
                sec_stocks_sorted[i]['集中风险'] = True

            warnings.append(f"板块集中风险：{sec}板块有{count}只选股（上限{max_per_sector}只），"
                          f"最低分{excess}只已标记为备选")

    return stocks, sector_stats, warnings


def apply_sector_cap(orders, max_sector_pct=0.30, total_capital=100_000):
    """
    检查订单列表的板块分布，如单板块超过总仓位max_sector_pct则按比例缩减

    Args:
        orders: list of dict, 每单需含 '板块' 和 '仓位占比'/'金额'
        max_sector_pct: 单板块最大仓位比例
        total_capital: 总资金（用于计算仓位占比）

    Returns:
        list: 调整后的订单
    """
    # v7.6 最终补丁：小资金（<=3,000元）跳过板块集中度限制，避免空仓
    if total_capital <= 3000:
        return orders

    if not orders:
        return orders

    # 统计板块仓位
    sector_amounts = {}
    for o in orders:
        sec = o.get('板块', '其他综合')
        # 解析金额
        amount = o.get('金额', 0)
        if isinstance(amount, str):
            amount = float(amount.replace('%', '').replace(',', ''))
        sector_amounts[sec] = sector_amounts.get(sec, 0) + amount

    total_amount = sum(sector_amounts.values())
    if total_amount == 0:
        return orders

    # 检查是否超标
    adjusted = []
    excess_pool = 0.0
    for sec, sec_amount in sector_amounts.items():
        sec_pct = sec_amount / total_amount
        if sec_pct > max_sector_pct:
            # 需要缩减
            target_amount = total_amount * max_sector_pct
            reduction = sec_amount - target_amount
            excess_pool += reduction
            print(f"[SECTOR] {sec}: {sec_pct*100:.1f}% -> {max_sector_pct*100:.0f}% (reduction {reduction:.0f})")

    # 应用缩减
    for o in orders:
        sec = o.get('板块', '其他综合')
        sec_amount = sector_amounts[sec]
        sec_pct = sec_amount / total_amount

        o_adj = dict(o)
        if sec_pct > max_sector_pct:
            # 按比例缩减该板块内的所有订单
            scale = max_sector_pct / sec_pct
            new_amount = round(o_adj['金额'] * scale, 2)
            if '股数' in o_adj and o_adj.get('价格', 0) > 0:
                # 按新金额重新计算股数（至少1手），保持金额与股数一致
                new_shares = max(100, int(new_amount / o_adj['价格'] / 100) * 100)
                o_adj['股数'] = new_shares
                o_adj['金额'] = round(new_shares * o_adj['价格'], 2)
            else:
                o_adj['金额'] = new_amount
            o_adj['仓位占比'] = f"{o_adj['金额']/total_capital*100:.1f}%"
            o_adj['缩减原因'] = f"板块风控：{sec}集中度超{max_sector_pct*100:.0f}%"

        adjusted.append(o_adj)

    return adjusted
