"""
开盘前简报 digest v1（v8.7 预备：LLM 融合层 · 交付层 P0-1）

借鉴 TradingAgents-CN-studio 的 digest 模块：把当天所有本地产出（选股 / 订单 / 出场顾问 /
市场状态 / Alpha Gate / 研究复盘 / shadow 多空分析）提炼成一条 180~240 字的四段简报：

    【结论】【信号】【风险】【动作】

原则：
- 有 LLM key → LLM 提炼（只允许引用输入里的事实，不许编数字）；输出必须含四个标签、长度受控，否则收紧重试一次
- 无 LLM key / 提炼失败 → 规则兜底，保证流水线一定有产出（成本优先原则）
- 不改任何决策：简报只是"读得完"的交付层，订单仍以 position_sizer / exit_advisor 为准

产出：
- results/digest_YYYYMMDD.md            简报正文 + 来源清单
- orders/digest_bark_YYYYMMDD.txt       TITLE: 一行 + 正文（send_to_bark.py 会自动前置到推送里）

用法：
    python digest.py               # 生成今日简报（自动判定是否用 LLM）
    python digest.py --no-llm      # 强制规则兜底
    python digest.py --dry-run     # 只打印，不落盘
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
DATA_DIR = os.path.join(BASE_DIR, 'data')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

TAGS = ('【结论】', '【信号】', '【风险】', '【动作】')
# MIN_CHARS=80：清淡日（无订单/无持仓）的规则兜底简报天然只有 ~110 字，四段齐全即合格；
# 180~240 字是给 LLM 的目标区间（写在 SYSTEM_PROMPT 里），不是硬下限。
MIN_CHARS, MAX_CHARS, HARD_LIMIT = 80, 260, 400
MAX_INPUT_CHARS = 12000  # 输入裁剪：保头 2/3 + 尾 1/3

SYSTEM_PROMPT = """\
你是一名小资金 A 股个人投资者的交易助理，用户每天开盘前只有 5 分钟读你写的一段话。

把输入的量化系统当日产出提炼成一份【开盘前简报】，硬性要求：
- 全文 180~240 个汉字，一条手机消息能读完，不许超
- 严格四段，每段一行，格式（去掉书名号本身之外都保留）：
  【结论】看多/看空/中性/空仓 + 一句话核心理由（先看市场状态和风控门）
  【信号】2-3 条关键事实：选出几只、首选是谁、评分/量比/RSI 等，用分号隔开
  【风险】1-2 条最值得盯的风险：出场顾问告警、Alpha Gate、板块集中、摩擦成本
  【动作】一句可执行建议：买什么/多少股/止损位，或"今日不操作"
- 只用输入里的事实和数字，绝不编造；输入没有的信息不要写
- 直接输出简报正文，不要任何前后缀解释\
"""


# ============================================================
# 输入收集
# ============================================================
def _latest(pattern: str, date_str: str | None = None) -> str | None:
    if date_str:
        cand = pattern.replace('*', date_str)
        return cand if os.path.exists(cand) else None
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


def _load_json(path: str | None, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _read_text(path: str | None, limit: int = 4000) -> str:
    if not path or not os.path.exists(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()[:limit]
    except Exception:
        return ''


def gather_inputs(date_str: str | None = None) -> dict:
    """收集当日（或最近一日）全部本地产出。缺哪个就空着，不抛异常。"""
    from bark_sender.parsers import parse_report_full

    pick_path = _latest(os.path.join(RESULTS_DIR, 'pick_*.md'), date_str)
    pick_date, stocks = ('', [])
    if pick_path:
        try:
            pick_date, stocks = parse_report_full(pick_path)
        except Exception:
            pass
    if not date_str and pick_path:
        m = re.search(r'pick_(\d{8})\.md', pick_path)
        date_str = m.group(1) if m else None
    date_str = date_str or datetime.now().strftime('%Y%m%d')

    regime = ''
    if pick_path:
        m = re.search(r'\*\*市场状态\*\*：([^|\n]+)', _read_text(pick_path, 3000))
        regime = m.group(1).strip() if m else ''
    regime_state = _load_json(os.path.join(DATA_DIR, 'regime_state.json'), {})
    regime = regime or str(regime_state.get('last_regime', ''))

    orders = _load_json(_latest(os.path.join(ORDERS_DIR, 'daily_orders_*.json'), date_str), {})
    exits = _load_json(_latest(os.path.join(RESULTS_DIR, 'exit_advisor_*.json'), date_str), [])
    alpha = _load_json(os.path.join(DATA_DIR, 'alpha_gate_state.json'), {})
    insight = _read_text(_latest(os.path.join(REPORTS_DIR, 'daily_insight_*.md'), date_str), 2500)
    analyst = _load_json(_latest(os.path.join(RESULTS_DIR, 'llm_analyst_*.json'), date_str), {})

    return {
        'date': date_str, 'pick_date': pick_date, 'pick_path': pick_path,
        'stocks': stocks or [], 'regime': regime,
        'orders': orders if isinstance(orders, dict) else {},
        'exits': exits if isinstance(exits, list) else [],
        'alpha': alpha if isinstance(alpha, dict) else {},
        'insight': insight, 'analyst': analyst if isinstance(analyst, dict) else {},
    }


# ============================================================
# 文本组装
# ============================================================
def _clip(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = limit * 2 // 3, limit // 3
    return text[:head] + '\n\n……（中间部分省略）……\n\n' + text[-tail:]


def _alpha_summary(alpha: dict) -> str:
    if not alpha:
        return ''
    hist = alpha.get('history') or []
    last = hist[-1] if hist else {}
    paused = bool(last.get('paused') or alpha.get('paused'))
    days = alpha.get('consecutive_severe_days', 0)
    excess = last.get('excess_pct')
    excess_s = f"，近期超额{excess:+.2f}%" if isinstance(excess, (int, float)) else ''
    return f"Alpha Gate：{'已暂停选股，建议 ETF' if paused else '未触发'}（连续跑输{days}日{excess_s}）"


def _exit_alerts(exits: list, limit: int = 4) -> list[str]:
    out = []
    for e in exits:
        if e.get('action', 'hold') == 'hold':
            continue
        sig = (e.get('signals') or [{}])[0].get('reason', '')
        out.append(f"{e.get('code')} {e.get('name')}：{e.get('action_label', '')} {sig}".strip())
    return out[:limit]


def build_source_text(inp: dict) -> str:
    """把结构化输入压成给 LLM 看的事实清单（也是 md 报告的"来源"段）。"""
    lines = [f"日期：{inp['pick_date'] or inp['date']}", f"市场状态：{inp['regime'] or '未知'}"]
    a = _alpha_summary(inp['alpha'])
    if a:
        lines.append(a)

    stocks = inp['stocks']
    lines.append(f"选股数量：{len(stocks)} 只")
    for s in stocks[:5]:
        lines.append(f"  #{s.get('code')} {s.get('name')} 价{s.get('price')} 涨跌{s.get('change')}% "
                     f"RSI{s.get('rsi')} 量比{s.get('vol_ratio')} 评分{s.get('score')} 风险{s.get('risk')} 理由：{s.get('reason')}")

    od = inp['orders']
    if od:
        ms = od.get('市场状态') or {}
        fa = od.get('资金分配') or {}
        lines.append(f"仓位计划：档位{ms.get('档位', '')} 沪深300 {ms.get('沪深300', '')} 总资金{fa.get('总资金', '')} "
                     f"仓位比例{fa.get('仓位比例', '')} 已用{fa.get('已用资金', '')} 剩余现金{fa.get('剩余现金', '')}")
        for o in (od.get('订单') or [])[:3]:
            lines.append(f"  买入 {o.get('代码')} {o.get('名称')} {o.get('股数')}股@{o.get('价格')} 金额{o.get('金额')} "
                         f"止损{o.get('止损价')}（{o.get('止损幅度')}）")
        for s in (od.get('今日卖出') or [])[:3]:
            sig = (s.get('signals') or [{}])[0].get('reason', '')
            lines.append(f"  卖出 {s.get('code')} {s.get('name')} {s.get('shares')}股：{s.get('action_label', '')} {sig}")
        for tip in (od.get('风控提示') or [])[:2]:
            lines.append(f"  风控提示：{tip}")

    alerts = _exit_alerts(inp['exits'])
    if alerts:
        lines.append('出场顾问告警：')
        lines += [f"  {x}" for x in alerts]
    else:
        lines.append(f"出场顾问：{len(inp['exits'])} 只持仓，无告警")

    an = inp['analyst']
    if an.get('verdicts'):
        lines.append('shadow 多空分析（不影响订单）：')
        for v in an['verdicts'][:3]:
            lines.append(f"  {v.get('code')} {v.get('name')}：{v.get('verdict')}（置信{v.get('confidence')}）{v.get('key_risk', '')}")

    if inp['insight']:
        lines.append('研究复盘摘录：')
        lines.append(_clip(inp['insight'], 1500))
    return _clip('\n'.join(lines))


# ============================================================
# 简报生成
# ============================================================
def validate_digest(text: str) -> bool:
    if not text:
        return False
    if not all(t in text for t in TAGS):
        return False
    return MIN_CHARS <= len(text.strip()) <= HARD_LIMIT


def rule_based_digest(inp: dict) -> str:
    """无 LLM 时的规则兜底：只拼事实，不做判断。"""
    stocks, od, regime = inp['stocks'], inp['orders'], inp['regime'] or '未知'
    alpha_paused = bool(inp['alpha'].get('paused') or ((inp['alpha'].get('history') or [{}])[-1]).get('paused'))
    buys = od.get('订单') or []
    sells = od.get('今日卖出') or []

    if alpha_paused:
        verdict = f"空仓观望：Alpha Gate 已暂停选股（连续跑输沪深300），市场{regime}"
    elif '熊' in regime:
        verdict = f"中性偏防守：市场{regime}，仓位从严、严格止损"
    elif '牛' in regime:
        verdict = f"看多：市场{regime}，趋势策略可正常执行"
    else:
        verdict = f"中性：市场{regime}，按计划小仓位执行"

    sig = [f"规则筛出{len(stocks)}只"]
    if stocks:
        s = stocks[0]
        sig.append(f"首选{s.get('code')} {s.get('name')} 评分{s.get('score')} 量比{s.get('vol_ratio')} RSI{s.get('rsi')}")
    fa = od.get('资金分配') or {}
    if fa:
        sig.append(f"仓位比例{fa.get('仓位比例', '')} 剩余现金{fa.get('剩余现金', '')}")

    risks = _exit_alerts(inp['exits'], 2) or [f"{len(inp['exits'])}只持仓无告警" if inp['exits'] else '无持仓']
    if sells and not _exit_alerts(inp['exits'], 1):
        risks = [f"{s.get('code')} {s.get('name')} {s.get('action_label', '')}" for s in sells[:2]]
    if len(risks) < 2:
        risks.append('小资金摩擦成本≈10元/笔，勿频繁交易')

    if buys:
        o = buys[0]
        action = f"按计划买入{o.get('代码')} {o.get('名称')} {o.get('股数')}股@{o.get('价格')}，止损{o.get('止损价')}"
        if sells:
            action = f"先卖{sells[0].get('code')}再" + action
        if len(buys) > 1:
            action += f"；另{len(buys) - 1}笔见订单文件"
    elif sells:
        action = f"执行卖出{sells[0].get('code')} {sells[0].get('name')}，今日不新开仓"
    else:
        action = '今日不操作，持仓按出场顾问执行'

    return '\n'.join([
        f"【结论】{verdict}",
        f"【信号】{'；'.join(sig)}",
        f"【风险】{'；'.join(risks[:2])}",
        f"【动作】{action}",
    ])


def llm_digest(source: str, inp: dict) -> str:
    """LLM 提炼；超长/缺标签收紧重试一次；仍不合格抛异常由调用方兜底。"""
    from core.llm import chat
    user = (f"股票池日期：{inp['pick_date'] or inp['date']}\n市场状态：{inp['regime'] or '未知'}\n\n"
            f"以下是量化系统当日全部产出（事实清单）：\n\n{source}")
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': user}]
    text, _ = chat(msgs, max_tokens=600, temperature=0.2, operation='digest', detail=inp['date'])
    if validate_digest(text) and len(text.strip()) <= MAX_CHARS + 40:
        return text.strip()
    msgs.append({'role': 'assistant', 'content': text})
    msgs.append({'role': 'user', 'content': f"不合格：必须严格四段（{'、'.join(TAGS)}）且 180~240 字。请只输出修正后的简报正文。"})
    text2, _ = chat(msgs, max_tokens=400, temperature=0.1, operation='digest_retry', detail=inp['date'])
    if validate_digest(text2):
        return text2.strip()
    raise RuntimeError(f'LLM 简报两次均不合格（len={len(text)}/{len(text2)}）')


def make_digest(inp: dict, use_llm: bool | None = None) -> tuple[str, str]:
    """返回 (简报文本, 生成方式 llm|rule)。"""
    source = build_source_text(inp)
    if use_llm is None:
        try:
            from core.llm import llm_available
            use_llm = llm_available()
        except Exception:
            use_llm = False
    if use_llm:
        try:
            return llm_digest(source, inp), 'llm'
        except Exception as exc:
            print(f"[DIGEST] LLM 提炼失败，改用规则兜底: {exc}", flush=True)
    return rule_based_digest(inp), 'rule'


# ============================================================
# 产出
# ============================================================
def bark_title(text: str, date_str: str) -> str:
    first = text.splitlines()[0] if text else ''
    verdict = next((v for v in ('看多', '看空', '中性', '空仓') if v in first), '')
    d = f"{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str
    return f"开盘前简报 {d}" + (f"（{verdict}）" if verdict else '')


def write_outputs(text: str, mode: str, inp: dict, source: str) -> dict:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(ORDERS_DIR, exist_ok=True)
    d = inp['date']
    md_path = os.path.join(RESULTS_DIR, f'digest_{d}.md')
    bark_path = os.path.join(ORDERS_DIR, f'digest_bark_{d}.txt')
    title = bark_title(text, d)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join([
            f"# 开盘前简报 — {inp['pick_date'] or d}",
            '',
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 方式：{'LLM 提炼' if mode == 'llm' else '规则兜底'} | 字数：{len(text)}",
            '',
            text,
            '',
            '---',
            '',
            '## 事实来源（简报只允许引用以下内容）',
            '',
            '```', source, '```',
            '',
            '*简报是交付层，不改变任何订单；买卖以 daily_orders / exit_advisor 为准。不构成投资建议。*',
        ]))
    with open(bark_path, 'w', encoding='utf-8') as f:
        f.write(f"TITLE: {title}\n{text}\n")
    return {'md': md_path, 'bark': bark_path, 'title': title}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='开盘前四段简报')
    p.add_argument('--date', help='YYYYMMDD，默认取最近一次选股')
    p.add_argument('--no-llm', action='store_true', help='强制规则兜底')
    p.add_argument('--dry-run', action='store_true', help='只打印不落盘')
    args = p.parse_args(argv)

    print(f"[DIGEST] v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    inp = gather_inputs(args.date)
    if not inp['stocks'] and not inp['orders'] and not inp['exits']:
        print('[DIGEST] 没有任何本地产出（pick/orders/exit_advisor 均缺失），跳过', flush=True)
        return 0
    text, mode = make_digest(inp, use_llm=False if args.no_llm else None)
    source = build_source_text(inp)
    print(f"[DIGEST] mode={mode} chars={len(text)}\n{text}", flush=True)
    if args.dry_run:
        return 0
    out = write_outputs(text, mode, inp, source)
    print(f"[DIGEST] saved: {out['md']} | {out['bark']}", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
