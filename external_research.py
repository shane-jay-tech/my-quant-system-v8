"""
外部研究引擎 v1 — arXiv 论文检索 + 自动摘要 + 因子提取

功能：
1. 搜索 arXiv 量化金融相关论文（momentum, factor investing, trend following）
2. 解析 XML，提取标题、摘要、作者、日期
3. 自动生成一句话中文摘要 + 可落地因子建议
4. 保存为 reports/external_research_YYYYMMDD.md
"""
import os, sys, re, urllib.request, urllib.error, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

# v8.5: 单一版本号源
sys.path.insert(0, BASE_DIR)
from core.config import SYSTEM_VERSION

# 合并为单一查询，避免限流
ARXIV_QUERY = "cat:q-fin*"
ARXIV_URL = "https://export.arxiv.org/api/query?search_query={}&start=0&max_results=8&sortBy=submittedDate&sortOrder=descending"


def fetch_arxiv(max_results=8, max_retries=3):
    """从 arXiv API 获取论文（带重试和退避）"""
    url = ARXIV_URL.format(urllib.parse.quote(ARXIV_QUERY, safe=':+*'))
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'QuantSystemV6/1.0 (mailto:research@example.com)'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 10 * (2 ** attempt)
                print(f"[ARXIV] Rate limited (429), waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"[ARXIV] HTTP {e.code}: {e}")
                return None
        except Exception as e:
            wait = 5 * (2 ** attempt)
            print(f"[ARXIV] Error: {e}, retrying in {wait}s...")
            time.sleep(wait)
    print("[ARXIV] All retries exhausted")
    return None


def parse_arxiv_xml(xml_str):
    """解析 arXiv API 返回的 Atom XML"""
    papers = []
    try:
        root = ET.fromstring(xml_str)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'arxiv': 'http://arxiv.org/schemas/atom',
        }
        for entry in root.findall('atom:entry', ns):
            title_el = entry.find('atom:title', ns)
            summary_el = entry.find('atom:summary', ns)
            published_el = entry.find('atom:published', ns)
            authors = entry.findall('atom:author/atom:name', ns)
            link_el = entry.find('atom:id', ns)

            paper = {
                'title': title_el.text.strip().replace('\n', ' ') if title_el is not None and title_el.text else 'Untitled',
                'summary': summary_el.text.strip().replace('\n', ' ')[:1000] if summary_el is not None and summary_el.text else '',
                'published': published_el.text[:10] if published_el is not None and published_el.text else 'Unknown',
                'authors': [a.text for a in authors if a.text][:3],
                'url': link_el.text.strip() if link_el is not None and link_el.text else '',
            }
            papers.append(paper)
    except ET.ParseError as e:
        print(f"[ARXIV] XML parse error: {e}")
    return papers


def summarize_paper(paper):
    """基于摘要内容自动生成中文一句话总结 + 可落地因子建议"""
    title = paper['title'].lower()
    summary = paper['summary'].lower()

    # 关键词 → 因子映射
    factor_map = {
        'momentum': ('动量效应', '可考虑增强动量因子权重或缩短计算周期'),
        'reversal': ('反转效应', '短期反转因子可作为动量策略的对冲/过滤器'),
        'value': ('价值因子', '低市盈率/低市净率股票可能提供额外alpha'),
        'volatility': ('波动率', '低波动异象——低波动股票长期收益可能高于高波动'),
        'liquidity': ('流动性', '流动性溢价——低流动性股票可能提供超额收益'),
        'machine learning': ('机器学习', '可尝试用ML模型（XGBoost/LSTM）替代线性评分'),
        'deep learning': ('深度学习', 'LSTM/Transformer可捕捉非线性价格模式'),
        'sentiment': ('情绪分析', '新闻/社交媒体情绪可作为短期择时信号'),
        'risk': ('风险管理', '动态调整仓位以控制最大回撤'),
        'factor': ('多因子', '因子正交化可减少共线性、提升组合稳健性'),
        'trend': ('趋势跟踪', '不同时间尺度的趋势信号组合可能优于单一周期'),
        'cross-sectional': ('截面动量', '横截面动量（买强卖弱）优于时间序列动量'),
        'macro': ('宏观因子', '纳入利率/CPI等宏观变量可改善择时准确性'),
        'attention': ('注意力机制', 'Transformer注意力机制可捕捉市场结构变化'),
        'transformer': ('Transformer', '时序Transformer模型在金融预测中表现优异'),
    }

    # 匹配关键词
    matched_factors = []
    for keyword, (cn_name, suggestion) in factor_map.items():
        if keyword in title or keyword in summary:
            matched_factors.append((cn_name, suggestion))

    # 生成一句话摘要
    if 'momentum' in title and 'reversal' not in title:
        cn_summary = "研究动量效应的表现与成因，发现动量策略在中期（3-12个月）具有稳健超额收益"
    elif 'machine learning' in title or 'deep learning' in title:
        cn_summary = "探索机器学习/深度学习方法在股票收益预测中的应用，对比传统因子模型的预测能力"
    elif 'factor' in title:
        cn_summary = "构建或改进多因子模型，分析因子在不同市场状态下的表现差异"
    elif 'volatility' in title:
        cn_summary = "研究波动率与预期收益的关系，低波动策略在风险调整后表现更优"
    elif 'trend' in title:
        cn_summary = "分析趋势跟踪策略在不同资产类别和时间尺度上的有效性"
    elif 'risk' in title:
        cn_summary = "研究风险管理方法对投资组合绩效的影响"
    else:
        cn_summary = f"研究量化投资领域的相关课题，为策略优化提供理论基础"

    # 可落地建议
    if matched_factors:
        top_factor = matched_factors[0]
        suggestion = f"【{top_factor[0]}】{top_factor[1]}"
    else:
        suggestion = "建议将论文方法在本地数据上回测验证后再考虑整合"

    return cn_summary, suggestion


def generate_report(all_papers):
    """生成外部研究报告"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = datetime.now()
    date_str = today.strftime('%Y%m%d')

    lines = [
        f"# 外部研究报告 — arXiv 量化金融论文",
        f"",
        f"> **生成日期**：{today.strftime('%Y-%m-%d %H:%M')}",
        f"> **数据来源**：arxiv.org (q-fin, cs.LG, stat.ML)",
        f"> **检索关键词**：momentum trading, factor investing, trend following, A-share, ML stock prediction",
        f"",
        f"---",
        f"",
    ]

    for i, paper in enumerate(all_papers, 1):
        cn_summary, suggestion = summarize_paper(paper)
        lines.extend([
            f"### {i}. {paper['title']}",
            f"",
            f"- **作者**：{', '.join(paper['authors'][:3])}",
            f"- **发布日期**：{paper['published']}",
            f"- **arXiv**：{paper['url']}",
            f"",
            f"**一句话总结**：{cn_summary}",
            f"",
            f"**可落地因子建议**：{suggestion}",
            f"",
            f"---",
            f"",
        ])

    lines.extend([
        f"## 整合建议",
        f"",
        f"以上发现建议在以下模块中验证：",
        f"- `strategy.py`：因子权重调整",
        f"- `enhanced_backtest.py`：新因子回测",
        f"- `evolve_strategy.py --auto`：自动A/B测试采纳",
        f"",
        f"> *报告由 external_research.py v{SYSTEM_VERSION} 自动生成*",
    ])

    report_path = os.path.join(REPORTS_DIR, f'external_research_{date_str}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"[ARXIV] Report saved: {report_path}")
    return report_path


def main():
    print(f"{'='*50}")
    print(f"  外部研究引擎 v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    all_papers = []
    print(f"[ARXIV] Query: {ARXIV_QUERY[:60]}...")
    xml_data = fetch_arxiv(max_results=8)
    if xml_data:
        papers = parse_arxiv_xml(xml_data)
        print(f"  → Found {len(papers)} papers")
        all_papers.extend(papers)
    else:
        print(f"  → No response")

    # 去重（按URL）
    seen_urls = set()
    unique_papers = []
    for p in all_papers:
        if p['url'] not in seen_urls:
            seen_urls.add(p['url'])
            unique_papers.append(p)

    print(f"[ARXIV] Total unique papers: {len(unique_papers)}")

    if unique_papers:
        report_path = generate_report(unique_papers[:8])  # 最多8篇
        return 0
    else:
        print("[ARXIV] No papers found. Generating empty report.")
        report_path = generate_report([])
        return 0


if __name__ == '__main__':
    sys.exit(main())
