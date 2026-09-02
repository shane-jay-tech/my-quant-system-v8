"""
决策回放 decision_replay v1（v8.7 预备：LLM 融合层 · 交付层 P0-2）

借鉴 TradingAgents-CN-studio 的 replay 模块思路，但**纯本地、零 LLM 成本**：
把当天"为什么选中 / 为什么买 / 为什么卖 / 哪道门在拦"渲染成一个自包含单文件 HTML，
双击打开或直接发给别人，复盘不用再翻日志。

数据源（全是现有产出，缺哪个就空着）：
- results/pick_YYYYMMDD.md          选股表（因子评分 / 理由 / 板块）
- orders/daily_orders_YYYYMMDD.json 仓位计划（市场状态 / 资金分配 / 买入 / 卖出 / 风控提示）
- results/exit_advisor_YYYYMMDD.json 出场顾问逐仓分析
- results/llm_analyst_YYYYMMDD.json shadow 多空分析（如有）
- data/alpha_gate_state.json / regime_state.json / factor_weights.json

产出：results/replay_YYYYMMDD.html

用法：python decision_replay.py [--date YYYYMMDD] [--open]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
DATA_DIR = os.path.join(BASE_DIR, 'data')

# 选股漏斗的规则门（静态描述，来源 strategy.py / position_sizer.py / alpha_gate.py）
GATES = [
    ('停牌/退市/新股/ST 过滤', 'strategy.py'),
    ('基本面硬过滤：ROE>0 且净利润增速>-20%', 'strategy.py v7.6'),
    ('MA 多头排列 + RSI 区间 + MACD 正向 + 量比>1.2 + 流通市值>50亿', 'strategy.py'),
    ('板块集中度：单板块≤3只/≤30%（本金<3000 自动跳过）', 'sector_classifier.py'),
    ('Alpha Gate：连续 5 日跑输沪深300 → 暂停选股', 'alpha_gate.py'),
    ('市场状态五档 → 仓位比例 + ATR 止损', 'position_sizer.py'),
    ('订单成本门槛：佣金/成交额超阈值拒单', 'cost_model.py'),
    ('组合风控锁：回撤>10% 或年化波动>20% 拦截新买入', 'portfolio_risk.py'),
]


def _e(x) -> str:
    return html.escape('' if x is None else str(x))


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def collect(date_str: str | None = None) -> dict:
    from digest import gather_inputs
    inp = gather_inputs(date_str)
    d = inp['date']
    inp['weights'] = _load_json(os.path.join(DATA_DIR, 'factor_weights.json'), {})
    inp['regime_state'] = _load_json(os.path.join(DATA_DIR, 'regime_state.json'), {})
    inp['analyst'] = _load_json(os.path.join(RESULTS_DIR, f'llm_analyst_{d}.json'), inp.get('analyst') or {})
    return inp


# ============================================================
# 渲染
# ============================================================
_CSS = """
:root{--bg:#0f1117;--panel:#171a23;--line:#262b38;--fg:#dbe2f0;--dim:#8b93a7;--acc:#4f8cff;--up:#ef6c6c;--dn:#3ecf8e;--warn:#e59a3c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;z-index:9}
h1{margin:0;font-size:16px}.meta{color:var(--dim);font-size:12px}
main{max-width:980px;margin:0 auto;padding:16px 14px 60px}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:14px 0}
h2{font-size:14px;color:var(--acc);margin:0 0 8px;letter-spacing:1px}
table{width:100%;border-collapse:collapse;font-size:12.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:5px 8px;white-space:nowrap;text-align:left}th{background:#1d2230;color:#fff}
.tag{display:inline-block;border-radius:10px;padding:0 8px;font-size:11px;border:1px solid var(--line);margin-right:4px}
.up{color:var(--up)}.dn{color:var(--dn)}.warn{color:var(--warn)}.dim{color:var(--dim)}
.gate{display:flex;gap:8px;margin:4px 0}.gate .n{color:var(--acc);min-width:22px}
details{margin:6px 0}summary{cursor:pointer;color:var(--acc)}
footer{text-align:center;color:var(--dim);font-size:11px;padding:16px}
@media(max-width:700px){main{padding:10px}section{padding:10px 12px}}
"""


def _section_market(inp: dict) -> str:
    od = inp['orders']
    ms = od.get('市场状态') or {}
    alpha = inp['alpha'] or {}
    hist = alpha.get('history') or []
    last = hist[-1] if hist else {}
    paused = bool(last.get('paused') or alpha.get('paused'))
    rs = inp.get('regime_state') or {}
    rows = [
        ('市场状态', inp['regime'] or ms.get('档位', '未知')),
        ('沪深300 / MA20 / MA60', f"{ms.get('沪深300', '-')} / {ms.get('MA20', '-')} / {ms.get('MA60', '-')}"),
        ('近5日涨跌 / 波动率', f"{ms.get('近5日涨跌', '-')} / {ms.get('波动率', '-')}"),
        ('状态切换候选', f"{rs.get('candidate_regime', '-')}（已确认 {rs.get('candidate_trading_days', '-')} 个交易日）"),
        ('Alpha Gate', ('<span class="up">已暂停选股 → 建议 ETF</span>' if paused else '<span class="dn">未触发</span>')
         + f" · 连续跑输 {alpha.get('consecutive_severe_days', 0)} 日"
         + (f" · 最近超额 {last.get('excess_pct'):+.2f}%" if isinstance(last.get('excess_pct'), (int, float)) else '')),
    ]
    body = ''.join(f"<tr><th>{_e(k)}</th><td>{v if k == 'Alpha Gate' else _e(v)}</td></tr>" for k, v in rows)
    return f"<section><h2>① 市场与风控门</h2><table>{body}</table></section>"


def _section_gates(inp: dict) -> str:
    od = inp['orders']
    tips = od.get('风控提示') or []
    items = ''.join(f'<div class="gate"><span class="n">{i + 1}</span><span>{_e(n)} <span class="dim">— {_e(src)}</span></span></div>'
                    for i, (n, src) in enumerate(GATES))
    tips_html = ''.join(f'<div class="warn">⚠ {_e(t)}</div>' for t in tips) or '<div class="dim">今日无额外风控提示</div>'
    return f"<section><h2>② 选股漏斗（全市场 → 规则筛选 → 风控门 → 订单）</h2>{items}<hr style='border-color:var(--line)'>{tips_html}</section>"


def _section_picks(inp: dict) -> str:
    stocks = inp['stocks']
    w = inp.get('weights') or {}
    wtxt = ''
    if isinstance(w, dict) and w:
        inner = w.get('weights', w)
        if isinstance(inner, dict):
            wtxt = '因子权重（IC/IR 推荐）：' + '，'.join(f"{_e(k)} {v}" for k, v in list(inner.items())[:8])
    if not stocks:
        return f"<section><h2>③ 选股结果</h2><div class='dim'>今日无选股产出</div><div class='dim'>{wtxt}</div></section>"
    head = '<tr><th>#</th><th>代码</th><th>名称</th><th>价</th><th>涨跌%</th><th>MA5/MA20</th><th>RSI</th><th>量比</th><th>市值亿</th><th>评分</th><th>风险</th><th>为什么选中</th></tr>'
    rows = ''
    for i, s in enumerate(stocks, 1):
        chg = str(s.get('change', ''))
        cls = 'up' if chg.startswith('+') else ('dn' if chg.startswith('-') else '')
        rows += (f"<tr><td>{i}</td><td>{_e(s.get('code'))}</td><td>{_e(s.get('name'))}</td><td>{_e(s.get('price'))}</td>"
                 f"<td class='{cls}'>{_e(chg)}</td><td>{_e(s.get('ma5'))}/{_e(s.get('ma20'))}</td><td>{_e(s.get('rsi'))}</td>"
                 f"<td>{_e(s.get('vol_ratio'))}</td><td>{_e(s.get('mcap'))}</td><td><b>{_e(s.get('score'))}</b></td>"
                 f"<td>{_e(s.get('risk'))}</td><td>{_e(s.get('reason'))}</td></tr>")
    return f"<section><h2>③ 选股结果（{len(stocks)} 只）</h2><div class='dim'>{wtxt}</div><table>{head}{rows}</table></section>"


def _section_orders(inp: dict) -> str:
    od = inp['orders']
    fa = od.get('资金分配') or {}
    buys = od.get('订单') or []
    sells = od.get('今日卖出') or []
    picked = {s.get('code') for s in inp['stocks']}
    bought = {o.get('代码') for o in buys}
    fa_html = ' · '.join(f"{_e(k)} {_e(v)}" for k, v in fa.items()) or '<span class="dim">无资金分配数据</span>'
    b = ''
    if buys:
        b = '<table><tr><th>方向</th><th>代码</th><th>名称</th><th>股数@价</th><th>金额</th><th>仓位</th><th>止损</th><th>板块</th></tr>'
        for o in buys:
            b += (f"<tr><td class='up'>买入</td><td>{_e(o.get('代码'))}</td><td>{_e(o.get('名称'))}</td>"
                  f"<td>{_e(o.get('股数'))}@{_e(o.get('价格'))}</td><td>{_e(o.get('金额'))}</td><td>{_e(o.get('仓位占比'))}</td>"
                  f"<td>{_e(o.get('止损价'))}（{_e(o.get('止损幅度'))}，{_e(o.get('止损方式'))}）</td><td>{_e(o.get('板块'))}</td></tr>")
        b += '</table>'
    else:
        b = '<div class="dim">今日无买入订单</div>'
    s = ''
    for x in sells:
        sig = (x.get('signals') or [{}])[0].get('reason', '')
        s += f"<div class='warn'>卖出 {_e(x.get('code'))} {_e(x.get('name'))} {_e(x.get('shares'))}股 — {_e(x.get('action_label'))} {_e(sig)}</div>"
    not_bought = [c for c in picked if c not in bought]
    nb = (f"<details><summary>选中但未下单 {len(not_bought)} 只（资金/仓位/成本门未通过）</summary>"
          f"<div class='dim'>{_e('、'.join(not_bought))}</div></details>") if not_bought else ''
    return f"<section><h2>④ 仓位计划与订单</h2><div>{fa_html}</div>{b}{s}{nb}</section>"


def _section_exits(inp: dict) -> str:
    exits = inp['exits']
    if not exits:
        return "<section><h2>⑤ 出场顾问（持仓逐一检查）</h2><div class='dim'>无持仓或无出场顾问产出</div></section>"
    head = '<tr><th>代码</th><th>名称</th><th>来源</th><th>入场</th><th>现价</th><th>盈亏%</th><th>持有日</th><th>止损/止盈</th><th>动作</th><th>原因</th></tr>'
    rows = ''
    for e in exits:
        pnl = e.get('pnl_pct', 0) or 0
        cls = 'up' if pnl > 0 else ('dn' if pnl < 0 else '')
        sig = (e.get('signals') or [{}])[0].get('reason', '')
        rows += (f"<tr><td>{_e(e.get('code'))}</td><td>{_e(e.get('name'))}</td><td>{_e(e.get('source'))}</td>"
                 f"<td>{_e(e.get('entry_price'))} / {_e(e.get('entry_date'))}</td><td>{_e(e.get('current_price'))}</td>"
                 f"<td class='{cls}'>{pnl:+.2f}</td><td>{_e(e.get('hold_days'))}</td><td>{_e(e.get('stop_loss'))} / {_e(e.get('take_profit'))}</td>"
                 f"<td>{_e(e.get('action_label'))}</td><td>{_e(sig)}</td></tr>")
    return f"<section><h2>⑤ 出场顾问（{len(exits)} 只持仓）</h2><table>{head}{rows}</table></section>"


def _section_analyst(inp: dict) -> str:
    an = inp.get('analyst') or {}
    vs = an.get('verdicts') or []
    if not vs:
        return ''
    cards = ''
    for v in vs:
        cards += (f"<details open><summary>{_e(v.get('code'))} {_e(v.get('name'))} → <b>{_e(v.get('verdict'))}</b>"
                  f"（置信 {_e(v.get('confidence'))}）· 模型 {_e(an.get('model'))}</summary>"
                  f"<div><span class='tag up'>多头</span>{_e(v.get('bull'))}</div>"
                  f"<div><span class='tag dn'>空头</span>{_e(v.get('bear'))}</div>"
                  f"<div><span class='tag'>裁决</span>{_e(v.get('judge'))}</div>"
                  f"<div class='warn'>关键风险：{_e(v.get('key_risk'))} · 建议：{_e(v.get('action'))}</div></details>")
    return (f"<section><h2>⑥ shadow 多空分析（不影响订单，仅供对账）</h2>"
            f"<div class='dim'>{_e(an.get('note', 'LLM 观点只能引用当日数据快照；订单仍以规则为准。'))}</div>{cards}</section>")


def render_html(inp: dict) -> str:
    d = inp['pick_date'] or inp['date']
    parts = [_section_market(inp), _section_gates(inp), _section_picks(inp),
             _section_orders(inp), _section_exits(inp), _section_analyst(inp)]
    return (f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>决策回放 {_e(d)}</title><style>{_CSS}</style></head><body>"
            f"<header><h1>🎬 决策回放 · {_e(d)}</h1><div class='meta'>市场 {_e(inp['regime'] or '未知')} · "
            f"选股 {len(inp['stocks'])} 只 · 订单 {len(inp['orders'].get('订单') or [])} 买 / {len(inp['orders'].get('今日卖出') or [])} 卖 · "
            f"持仓 {len(inp['exits'])} · 生成 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div></header>"
            f"<main>{''.join(parts)}</main>"
            f"<footer>my-quant-system-v8 决策回放 · 单文件可直接分享 · 不构成投资建议</footer></body></html>")


def write_html(inp: dict) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"replay_{inp['date']}.html")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_html(inp))
    return path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='决策回放单文件 HTML')
    p.add_argument('--date', help='YYYYMMDD，默认最近一次选股')
    p.add_argument('--open', action='store_true', help='生成后用浏览器打开')
    args = p.parse_args(argv)
    print(f"[REPLAY] v1 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    inp = collect(args.date)
    if not inp['stocks'] and not inp['orders'] and not inp['exits']:
        print('[REPLAY] 没有任何本地产出，跳过', flush=True)
        return 0
    path = write_html(inp)
    print(f"[REPLAY] saved: {path} ({os.path.getsize(path)} bytes)", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
