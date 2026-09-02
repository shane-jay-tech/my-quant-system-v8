"""
shadow 多空分析师 llm_analyst v1（v8.7 预备：LLM 融合层 · P1）

借鉴 TradingAgents-CN 的多智能体辩论思路，但做成"被规则管住的一路投票"：
- 只对规则筛出的 top N（默认 3）候选跑：多头分析师 → 空头分析师 → 研究经理裁决
- 事实锚定：三个角色只能引用本地数据快照（选股行 + 近 20 日 K 线派生指标），禁止编数字
- shadow 模式：只落盘 verdict，不改任何订单 / 仓位 / 止损；后续用 --evaluate 与前瞻收益对账
- 无 LLM key → 直接跳过（rc=0），流水线不受影响；成本上限由 llm_analyst.max_stocks 控制

产出：
- results/llm_analyst_YYYYMMDD.md      三角色全文（供 decision_replay 展示）
- results/llm_analyst_YYYYMMDD.json    {date, model, verdicts:[{code,name,verdict,confidence,key_risk,action,bull,bear,judge}]}
- data/llm_verdicts.jsonl              逐日追加，评估用

用法：
    python llm_analyst.py                 # 今日 shadow 分析（无 key 自动跳过）
    python llm_analyst.py --top 2         # 只分析前 2 只
    python llm_analyst.py --evaluate      # 用 history.csv 计算历史 verdict 的 5 日前瞻命中率
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.config import get as cfg_get  # noqa: E402
from utils.file_io import atomic_write_json  # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
DATA_DIR = os.path.join(BASE_DIR, 'data')
VERDICT_LOG = os.path.join(DATA_DIR, 'llm_verdicts.jsonl')

VERDICTS = ('看多', '看空', '中性')

BULL_PROMPT = """你是多头分析师。只能引用下面事实清单里的数字，禁止编造任何未给出的数据（如财报、新闻）。
用 3 条要点（每条≤40字）说明为什么这只股票值得买，最后给出多头视角的关键价位。只输出要点。"""
BEAR_PROMPT = """你是空头分析师。只能引用下面事实清单里的数字，禁止编造任何未给出的数据。
用 3 条要点（每条≤40字）指出这只股票最可能失败的原因（趋势透支/量能/大盘/摩擦成本），最后给出止损位建议。只输出要点。"""
JUDGE_PROMPT = """你是研究经理，面对小资金（<3000元）A股个人投资者。综合多头与空头发言和事实清单裁决。
只输出一个 JSON 对象，字段：
{"verdict": "看多|看空|中性", "confidence": 0~1 的小数, "key_risk": "≤30字", "action": "≤40字可执行建议", "judge": "≤80字裁决理由"}
不许输出 JSON 以外的任何文字。"""


# ============================================================
# 事实清单
# ============================================================
def load_top_picks(n: int, date_str: str | None = None) -> tuple[str, list[dict]]:
    from bark_sender.parsers import parse_report_full
    if date_str:
        path = os.path.join(RESULTS_DIR, f'pick_{date_str}.md')
        if not os.path.exists(path):
            return date_str, []
    else:
        files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'pick_*.md')), reverse=True)
        if not files:
            return datetime.now().strftime('%Y%m%d'), []
        path = files[0]
        m = re.search(r'pick_(\d{8})\.md', path)
        date_str = m.group(1) if m else datetime.now().strftime('%Y%m%d')
    _, stocks = parse_report_full(path)
    return date_str, stocks[:n]


def _history_stats(code: str, history: pd.DataFrame | None, days: int = 20) -> dict:
    if history is None or history.empty:
        return {}
    df = history[history['代码'].astype(str).str.zfill(6) == str(code).zfill(6)].sort_values('日期').tail(days)
    if len(df) < 5:
        return {}
    close = df['收盘'].astype(float)
    ret = (close.iloc[-1] / close.iloc[0] - 1) * 100
    peak = close.cummax()
    dd = ((close / peak - 1) * 100).min()
    vol = close.pct_change().std() * 100
    return {
        f'{len(df)}日涨幅%': round(float(ret), 2),
        '区间最大回撤%': round(float(dd), 2),
        '日波动率%': round(float(vol), 2),
        '区间最高': round(float(close.max()), 2),
        '区间最低': round(float(close.min()), 2),
    }


def build_fact_sheet(stock: dict, regime: str, history: pd.DataFrame | None) -> str:
    lines = [
        f"股票：{stock.get('code')} {stock.get('name')}（板块 {stock.get('sector', '未知')}）",
        f"市场状态：{regime or '未知'}",
        f"最新价 {stock.get('price')}，当日涨跌 {stock.get('change')}%",
        f"MA5 {stock.get('ma5')} / MA20 {stock.get('ma20')}，RSI14 {stock.get('rsi')}，量比 {stock.get('vol_ratio')}",
        f"流通市值 {stock.get('mcap')} 亿，规则评分 {stock.get('score')}/100，风险标注 {stock.get('risk')}",
        f"规则选入理由：{stock.get('reason')}",
    ]
    hs = _history_stats(stock.get('code', ''), history)
    if hs:
        lines.append('近 20 日 K 线派生：' + '，'.join(f"{k} {v}" for k, v in hs.items()))
    lines.append('交易约束：A股最小 100 股；单笔佣金不足 5 元按 5 元；卖出印花税 0.05%；本金 <3000 元')
    return '\n'.join(lines)


# ============================================================
# 三角色
# ============================================================
def analyze_one(stock: dict, facts: str) -> dict:
    from core.llm import chat, parse_json_object
    code, name = stock.get('code'), stock.get('name')
    bull, _ = chat([{'role': 'system', 'content': BULL_PROMPT},
                    {'role': 'user', 'content': facts}],
                   max_tokens=300, temperature=0.4, operation='llm_analyst_bull', detail=str(code))
    bear, _ = chat([{'role': 'system', 'content': BEAR_PROMPT},
                    {'role': 'user', 'content': facts}],
                   max_tokens=300, temperature=0.4, operation='llm_analyst_bear', detail=str(code))
    judge_raw, _ = chat([{'role': 'system', 'content': JUDGE_PROMPT},
                         {'role': 'user', 'content': f"【事实清单】\n{facts}\n\n【多头】\n{bull}\n\n【空头】\n{bear}"}],
                        max_tokens=400, temperature=0.2, operation='llm_analyst_judge', detail=str(code))
    j = parse_json_object(judge_raw)
    verdict = normalize_verdict(j.get('verdict', ''), fallback_text=judge_raw)
    try:
        conf = max(0.0, min(1.0, float(j.get('confidence', 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        'code': code, 'name': name, 'verdict': verdict, 'confidence': round(conf, 2),
        'key_risk': str(j.get('key_risk', ''))[:60], 'action': str(j.get('action', ''))[:80],
        'judge': str(j.get('judge') or judge_raw)[:300], 'bull': bull.strip()[:600], 'bear': bear.strip()[:600],
        'rule_score': stock.get('score'), 'price': stock.get('price'),
    }


def normalize_verdict(v: str, fallback_text: str = '') -> str:
    v = (v or '').strip()
    for k in VERDICTS:
        if k in v:
            return k
    tail = (fallback_text or '')[-400:]
    if re.search(r'买入|看多|增持|加仓', tail):
        return '看多'
    if re.search(r'卖出|看空|减持|规避', tail):
        return '看空'
    return '中性'


# ============================================================
# 产出
# ============================================================
def write_outputs(date_str: str, model: str, verdicts: list[dict], regime: str) -> dict:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        'date': date_str, 'model': model, 'regime': regime, 'mode': 'shadow',
        'note': 'shadow 模式：观点只能引用当日数据快照，不改变任何订单；用 --evaluate 与前瞻收益对账。',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'verdicts': verdicts,
    }
    json_path = os.path.join(RESULTS_DIR, f'llm_analyst_{date_str}.json')
    atomic_write_json(json_path, payload)

    md_path = os.path.join(RESULTS_DIR, f'llm_analyst_{date_str}.md')
    lines = [f"# shadow 多空分析 — {date_str}", '',
             f"> 模型 {model} | 市场 {regime or '未知'} | {len(verdicts)} 只 | 不影响订单", '',
             '| 代码 | 名称 | 规则评分 | LLM 裁决 | 置信 | 关键风险 | 建议 |', '|---|---|---|---|---|---|---|']
    for v in verdicts:
        lines.append(f"| {v['code']} | {v['name']} | {v.get('rule_score')} | {v['verdict']} | {v['confidence']} | {v['key_risk']} | {v['action']} |")
    for v in verdicts:
        lines += ['', f"## {v['code']} {v['name']} → {v['verdict']}", '', '**多头**', '', v['bull'], '',
                  '**空头**', '', v['bear'], '', '**裁决**', '', v['judge']]
    lines += ['', '---', '*LLM 观点仅供对账，订单以 position_sizer / exit_advisor 为准。不构成投资建议。*']
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    with open(VERDICT_LOG, 'a', encoding='utf-8') as f:
        for v in verdicts:
            f.write(json.dumps({'date': date_str, 'model': model, 'code': v['code'], 'name': v['name'],
                                'verdict': v['verdict'], 'confidence': v['confidence'],
                                'price': v.get('price'), 'rule_score': v.get('rule_score')},
                               ensure_ascii=False) + '\n')
    return {'json': json_path, 'md': md_path}


# ============================================================
# 评估：verdict vs 5 日前瞻收益
# ============================================================
def evaluate(horizon: int = 5) -> dict:
    if not os.path.exists(VERDICT_LOG):
        return {'n': 0, 'note': '暂无 verdict 记录'}
    rows = []
    with open(VERDICT_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    hist_path = os.path.join(DATA_DIR, 'history.csv')
    if not rows or not os.path.exists(hist_path):
        return {'n': 0, 'note': '无 verdict 或无 history.csv'}
    hist = pd.read_csv(hist_path, dtype={'代码': str}, encoding='utf-8-sig')
    hist['日期'] = pd.to_datetime(hist['日期'])
    out = []
    for r in rows:
        df = hist[hist['代码'].str.zfill(6) == str(r['code']).zfill(6)].sort_values('日期')
        d0 = pd.to_datetime(r['date'])
        fut = df[df['日期'] > d0].head(horizon)
        base = df[df['日期'] <= d0].tail(1)
        if len(fut) < horizon or base.empty:
            continue
        fwd = (float(fut['收盘'].iloc[-1]) / float(base['收盘'].iloc[0]) - 1) * 100
        out.append({**r, 'fwd_ret': round(fwd, 2)})
    if not out:
        return {'n': 0, 'note': f'尚无满 {horizon} 日前瞻数据的 verdict'}
    df = pd.DataFrame(out)
    summary = {'n': int(len(df)), 'horizon': horizon}
    for v in VERDICTS:
        sub = df[df['verdict'] == v]
        if len(sub):
            hit = (sub['fwd_ret'] > 0).mean() if v == '看多' else ((sub['fwd_ret'] < 0).mean() if v == '看空' else float('nan'))
            summary[v] = {'n': int(len(sub)), 'avg_fwd_ret': round(float(sub['fwd_ret'].mean()), 2),
                          'hit_rate': (round(float(hit), 3) if hit == hit else None)}
    summary['baseline_avg_fwd_ret'] = round(float(df['fwd_ret'].mean()), 2)
    return summary


# ============================================================
# 入口
# ============================================================
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='shadow 多空分析师')
    p.add_argument('--top', type=int, default=None, help='分析前 N 只（默认配置 llm_analyst.max_stocks=3）')
    p.add_argument('--date', help='YYYYMMDD，默认最近一次选股')
    p.add_argument('--evaluate', action='store_true', help='评估历史 verdict 的前瞻命中率')
    args = p.parse_args(argv)

    print(f"[LLM-ANALYST] v1 shadow @ {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    if args.evaluate:
        res = evaluate(int(cfg_get('llm_analyst.eval_horizon', 5)))
        print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(os.path.join(RESULTS_DIR, 'llm_analyst_eval.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        return 0

    if not cfg_get('llm_analyst.enabled', True):
        print('[LLM-ANALYST] 配置关闭（llm_analyst.enabled=false），跳过', flush=True)
        return 0
    from core.llm import llm_available, load_llm_config
    if not llm_available():
        print('[LLM-ANALYST] 未配置 LLM key（DEEPSEEK_API_KEY / secrets.json:deepseek_api_key），跳过 shadow 分析', flush=True)
        return 0

    top_n = args.top or int(cfg_get('llm_analyst.max_stocks', 3))
    date_str, picks = load_top_picks(top_n, args.date)
    if not picks:
        print('[LLM-ANALYST] 无选股产出，跳过', flush=True)
        return 0

    regime = ''
    try:
        with open(os.path.join(DATA_DIR, 'regime_state.json'), 'r', encoding='utf-8') as f:
            regime = json.load(f).get('last_regime', '')
    except Exception:
        pass
    history = None
    hist_path = os.path.join(DATA_DIR, 'history.csv')
    if os.path.exists(hist_path):
        try:
            history = pd.read_csv(hist_path, dtype={'代码': str}, encoding='utf-8-sig')
        except Exception as exc:
            print(f"[LLM-ANALYST] history.csv 读取失败，跳过 K 线派生: {exc}", flush=True)

    model = load_llm_config()['model']
    verdicts = []
    for s in picks:
        try:
            v = analyze_one(s, build_fact_sheet(s, regime, history))
            verdicts.append(v)
            print(f"  {v['code']} {v['name']} -> {v['verdict']} (conf {v['confidence']})", flush=True)
        except Exception as exc:
            print(f"  {s.get('code')} 分析失败，跳过: {exc}", flush=True)
    if not verdicts:
        print('[LLM-ANALYST] 全部失败，无产出', flush=True)
        return 0
    out = write_outputs(date_str, model, verdicts, regime)
    print(f"[LLM-ANALYST] saved: {out['json']} | {out['md']}", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
