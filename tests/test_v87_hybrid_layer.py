"""v8.7 预备：LLM 融合层（交付层 P0 + shadow 分析师 P1）回归测试。

全部离线：不调 LLM、不发推送。锁定：
- core.llm：无 key 优雅降级、环境变量优先、JSON 抠取
- digest：规则兜底四段齐全且长度受控、落盘格式、bark 标题含多空判断
- decision_replay：HTML 含六个区块要素、转义、落盘
- bark_sender.channels：注册表 / 多实例别名 / 逐渠道失败隔离 / 环境变量渠道
- bark_sender.config：源码零硬编码 token；send_bark 无 token 返回 False
- llm_analyst：verdict 归一化、事实清单只含快照数字、无 key 跳过 rc=0
- pipeline：llm_analyst < digest < decision_replay < bark_push
- send_to_bark.load_digest：能读 digest 文件并前置
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core import llm as core_llm  # noqa: E402
import digest  # noqa: E402
import decision_replay  # noqa: E402
import llm_analyst  # noqa: E402
import send_to_bark  # noqa: E402
from bark_sender import channels as ch  # noqa: E402
from bark_sender import push as bark_push  # noqa: E402


# ------------------------------------------------------------
# fixtures
# ------------------------------------------------------------
@pytest.fixture
def no_llm(monkeypatch, tmp_path):
    for k in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(core_llm, '_SECRETS_PATH', str(tmp_path / 'nope.json'))
    return tmp_path


@pytest.fixture
def sample_inputs():
    stocks = [
        {'code': '605018', 'name': '长华集团', 'price': '12.86', 'change': '+5.32', 'ma5': '12.61',
         'ma20': '12.39', 'rsi': '52.78', 'vol_ratio': '2.60', 'mcap': '60.45', 'score': '100',
         'risk': '中', 'reason': '显著放量 + MACD正向'},
        {'code': '002272', 'name': '川润股份', 'price': '15.59', 'change': '+7.96', 'ma5': '15.36',
         'ma20': '14.62', 'rsi': '47.91', 'vol_ratio': '1.60', 'mcap': '63.63', 'score': '97',
         'risk': '低', 'reason': '强趋势'},
    ]
    orders = {
        '市场状态': {'档位': '弱熊', '沪深300': 4618.9, 'MA20': 4640.6, 'MA60': 4764.19},
        '资金分配': {'总资金': 2423.9, '仓位比例': '100%', '已用资金': 467.0, '剩余现金': 1956.9},
        '订单': [{'代码': '601006', '名称': '大秦铁路', '价格': 4.67, '股数': 100, '金额': 467.0,
                '仓位占比': '19.3%', '板块': '有色资源', '止损价': 4.52, '止损方式': 'ATR', '止损幅度': '-3.1%'}],
        '今日卖出': [{'code': '159325', 'name': '半导体ETF南方', 'shares': 700, 'action_label': '立即止损',
                  'signals': [{'level': 'urgent', 'reason': '止损触发：现价2.147≤止损2.17'}]}],
        '风控提示': ['弱熊市：仓位控制在20%以内'],
    }
    exits = [
        {'code': '600266', 'name': '城建发展', 'entry_price': 4.18, 'entry_date': '2026-08-10', 'shares': 100,
         'stop_loss': 3.9, 'take_profit': 5.02, 'source': 'sim', 'action': 'hold', 'action_label': '持有',
         'signals': [{'level': 'ok', 'reason': '正常'}], 'current_price': 4.19, 'pnl_pct': 0.24, 'hold_days': 9},
        {'code': '159325', 'name': '半导体ETF南方', 'entry_price': 2.356, 'entry_date': '2026-05-25', 'shares': 700,
         'stop_loss': 2.17, 'take_profit': 3.06, 'source': 'real', 'action': 'sell_stop', 'action_label': '立即止损',
         'signals': [{'level': 'urgent', 'reason': '止损触发'}], 'current_price': 2.147, 'pnl_pct': -8.9, 'hold_days': 60},
    ]
    return {
        'date': '20260821', 'pick_date': '2026-08-21', 'pick_path': None, 'stocks': stocks, 'regime': '弱熊',
        'orders': orders, 'exits': exits,
        'alpha': {'consecutive_severe_days': 2, 'history': [{'paused': False, 'excess_pct': -6.02}]},
        'insight': '', 'analyst': {}, 'weights': {}, 'regime_state': {},
    }


# ------------------------------------------------------------
# core.llm
# ------------------------------------------------------------
def test_llm_unavailable_without_key(no_llm):
    assert core_llm.llm_available() is False
    with pytest.raises(core_llm.LLMError):
        core_llm.chat([{'role': 'user', 'content': 'x'}])


def test_llm_env_overrides_defaults(no_llm, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'k')
    monkeypatch.setenv('DEEPSEEK_MODEL', 'deepseek-v4-pro')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://x/v1/')
    cfg = core_llm.load_llm_config()
    assert cfg['api_key'] == 'k' and cfg['model'] == 'deepseek-v4-pro'
    assert cfg['base_url'] == 'https://x/v1'  # 去尾斜杠
    assert core_llm.llm_available() is True


def test_llm_secrets_fallback(no_llm, monkeypatch, tmp_path):
    p = tmp_path / 'secrets.json'
    p.write_text(json.dumps({'deepseek_api_key': 'from-file'}), encoding='utf-8')
    monkeypatch.setattr(core_llm, '_SECRETS_PATH', str(p))
    assert core_llm.load_llm_config()['api_key'] == 'from-file'


def test_parse_json_object_tolerates_fences_and_noise():
    assert core_llm.parse_json_object('```json\n{"verdict":"看多","confidence":0.7}\n```') == {'verdict': '看多', 'confidence': 0.7}
    assert core_llm.parse_json_object('废话 {"a": 1} 废话') == {'a': 1}
    assert core_llm.parse_json_object('not json') == {}
    assert core_llm.parse_json_object('[1,2]') == {}


def test_llm_cost_estimate_uses_model_price():
    assert core_llm._estimate_cost_cny('deepseek-v4-flash', 1_000_000, 0) == 1.0
    assert core_llm._estimate_cost_cny('deepseek-v4-pro', 0, 1_000_000) == 9.0


# ------------------------------------------------------------
# digest
# ------------------------------------------------------------
def test_rule_digest_has_four_tags_and_facts(sample_inputs):
    text = digest.rule_based_digest(sample_inputs)
    assert digest.validate_digest(text)
    lines = text.splitlines()
    assert [l[:4] for l in lines] == list(digest.TAGS)
    assert '弱熊' in lines[0]
    assert '605018' in lines[1] and '评分100' in lines[1]
    assert '159325' in lines[2]
    assert '601006' in lines[3] and '止损4.52' in lines[3]
    assert '先卖159325' in lines[3]


def test_rule_digest_alpha_paused_means_flat(sample_inputs):
    sample_inputs['alpha'] = {'paused': True, 'consecutive_severe_days': 5, 'history': []}
    text = digest.rule_based_digest(sample_inputs)
    assert text.splitlines()[0].startswith('【结论】空仓观望')


def test_rule_digest_no_orders_no_action(sample_inputs):
    sample_inputs['orders'] = {}
    sample_inputs['exits'] = []
    text = digest.rule_based_digest(sample_inputs)
    assert '今日不操作' in text
    assert digest.validate_digest(text)


def test_validate_digest_rejects_missing_tag_or_overlong():
    assert not digest.validate_digest('【结论】a\n【信号】b\n【风险】c')
    assert not digest.validate_digest('【结论】' + 'x' * 500 + '【信号】【风险】【动作】')
    assert not digest.validate_digest('')


def test_make_digest_falls_back_to_rule_without_llm(sample_inputs, no_llm):
    text, mode = digest.make_digest(sample_inputs)  # use_llm=None → llm_available()=False
    assert mode == 'rule' and digest.validate_digest(text)


def test_make_digest_llm_failure_falls_back(sample_inputs, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('network down')
    monkeypatch.setattr(digest, 'llm_digest', boom)
    text, mode = digest.make_digest(sample_inputs, use_llm=True)
    assert mode == 'rule' and digest.validate_digest(text)


def test_clip_keeps_head_and_tail():
    s = 'H' * 9000 + 'T' * 9000
    out = digest._clip(s, 3000)
    assert out.startswith('H' * 100) and out.endswith('T' * 100) and '省略' in out and len(out) < 3200


def test_bark_title_includes_verdict():
    assert digest.bark_title('【结论】看多：xxx\n...', '20260821') == '开盘前简报 08-21（看多）'
    assert digest.bark_title('【结论】空仓观望', '20260821') == '开盘前简报 08-21（空仓）'


def test_write_outputs_and_send_to_bark_roundtrip(sample_inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(digest, 'RESULTS_DIR', str(tmp_path / 'results'))
    monkeypatch.setattr(digest, 'ORDERS_DIR', str(tmp_path / 'orders'))
    text = digest.rule_based_digest(sample_inputs)
    out = digest.write_outputs(text, 'rule', sample_inputs, digest.build_source_text(sample_inputs))
    md = Path(out['md']).read_text(encoding='utf-8')
    assert '规则兜底' in md and '事实来源' in md and text in md
    bark = Path(out['bark']).read_text(encoding='utf-8')
    assert bark.startswith('TITLE: 开盘前简报 08-21')

    monkeypatch.setattr(send_to_bark, 'ORDERS_DIR', str(tmp_path / 'orders'))
    loaded = send_to_bark.load_digest('2026-08-21')
    assert loaded is not None
    title, body = loaded
    assert title.startswith('开盘前简报') and body == text
    assert send_to_bark.load_digest('2026-01-01') is None
    assert send_to_bark.load_digest('bad') is None


def test_gather_inputs_handles_empty_dirs(tmp_path, monkeypatch):
    for attr in ('RESULTS_DIR', 'ORDERS_DIR', 'DATA_DIR', 'REPORTS_DIR'):
        monkeypatch.setattr(digest, attr, str(tmp_path / attr))
    inp = digest.gather_inputs()
    assert inp['stocks'] == [] and inp['orders'] == {} and inp['exits'] == []
    assert len(inp['date']) == 8


# ------------------------------------------------------------
# decision_replay
# ------------------------------------------------------------
def test_replay_html_contains_all_sections(sample_inputs):
    h = decision_replay.render_html(sample_inputs)
    for marker in ('① 市场与风控门', '② 选股漏斗', '③ 选股结果（2 只）', '④ 仓位计划与订单', '⑤ 出场顾问（2 只持仓）'):
        assert marker in h
    assert '⑥ shadow' not in h  # 无 analyst 产出时不渲染
    assert '605018' in h and '大秦铁路' in h and '159325' in h and 'Alpha Gate' in h
    assert '选中但未下单 2 只' in h  # 两只选中都没下单（订单是 601006）
    assert h.count('<section>') == 5


def test_replay_html_escapes_and_renders_analyst(sample_inputs):
    sample_inputs['stocks'][0]['name'] = '<script>alert(1)</script>'
    sample_inputs['analyst'] = {'model': 'm', 'verdicts': [
        {'code': '605018', 'name': 'x', 'verdict': '看多', 'confidence': 0.7, 'bull': 'b', 'bear': 'r',
         'judge': 'j', 'key_risk': 'k', 'action': 'a'}]}
    h = decision_replay.render_html(sample_inputs)
    assert '<script>alert(1)</script>' not in h and '&lt;script&gt;' in h
    assert '⑥ shadow 多空分析' in h and h.count('<section>') == 6


def test_replay_write_html(sample_inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(decision_replay, 'RESULTS_DIR', str(tmp_path))
    p = decision_replay.write_html(sample_inputs)
    assert p.endswith('replay_20260821.html') and os.path.getsize(p) > 2000


# ------------------------------------------------------------
# channels
# ------------------------------------------------------------
class _Boom(ch.Channel):
    name = 'boom'

    def __init__(self, options):
        pass

    def send(self, title, body):
        raise RuntimeError('down')


class _Ok(ch.Channel):
    name = 'ok'
    sent = []

    def __init__(self, options):
        pass

    def send(self, title, body):
        _Ok.sent.append((title, body))


def test_registry_has_builtin_channels():
    assert {'bark', 'feishu', 'webhook'} <= set(ch.registry.names())
    with pytest.raises(KeyError):
        ch.registry.build('nope', {})


def test_push_all_isolates_failures():
    _Ok.sent.clear()
    chans = [_Boom({}), _Ok({})]
    chans[0].alias, chans[1].alias = '坏的', '好的'
    res = ch.push_all('t', 'b', channels=chans)
    assert res[0] == 'FAIL 坏的: RuntimeError' and res[1] == 'OK 好的'
    assert _Ok.sent == [('t', 'b')]


def test_push_all_no_channels_reports_fail():
    assert ch.push_all('t', 'b', channels=[])[0].startswith('FAIL')


def test_build_channels_alias_and_skip_incomplete(capsys):
    cfg = {'webhook#群A': {'url': 'http://a'}, 'webhook#群B': {'url': 'http://b'}, 'feishu': {}}  # feishu 缺 webhook
    chans = ch.build_channels(cfg, include_bark=False)
    assert [c.alias for c in chans] == ['群A', '群B']
    assert '跳过渠道 feishu' in capsys.readouterr().out


def test_load_channel_config_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, '_SECRETS_PATH', str(tmp_path / 'none.json'))
    monkeypatch.setenv('QUANT_NOTIFY_WEBHOOK_URL', 'http://hook')
    monkeypatch.setenv('QUANT_FEISHU_WEBHOOK', 'http://fs')
    monkeypatch.setenv('QUANT_FEISHU_SECRET', 's')
    cfg = ch.load_channel_config()
    assert cfg['webhook#env'] == {'url': 'http://hook'}
    assert cfg['feishu#env'] == {'webhook': 'http://fs', 'secret': 's'}


def test_webhook_and_feishu_send_payloads(monkeypatch):
    calls = []

    class R:
        status_code = 200
        content = b'{"code":0}'

        def raise_for_status(self):
            pass

        def json(self):
            return {'code': 0}

    monkeypatch.setattr(ch.requests, 'post', lambda url, json=None, timeout=15: calls.append((url, json)) or R())
    ch.WebhookChannel({'url': 'http://w'}).send('T', 'B')
    ch.FeishuChannel({'webhook': 'http://f', 'secret': 'sec'}).send('T', 'B')
    assert calls[0][0] == 'http://w' and calls[0][1]['title'] == 'T'
    assert calls[1][1]['msg_type'] == 'interactive' and 'sign' in calls[1][1]


def test_feishu_error_code_raises(monkeypatch):
    class R:
        content = b'x'

        def raise_for_status(self):
            pass

        def json(self):
            return {'code': 19001, 'msg': 'bad'}

    monkeypatch.setattr(ch.requests, 'post', lambda *a, **k: R())
    with pytest.raises(RuntimeError):
        ch.FeishuChannel({'webhook': 'http://f'}).send('T', 'B')


def test_send_bark_without_tokens_returns_false(capsys):
    assert bark_push.send_bark('t', 'b', tokens=[]) is False
    assert '没有配置 token' in capsys.readouterr().out


def test_no_hardcoded_bark_token_in_sources():
    """凭据零硬编码：扫描全部推送/自检源码，禁止任何 32 位十六进制 token 字面量。"""
    import re
    pat = re.compile(r'["\'][0-9A-Fa-f]{32}["\']')
    for rel in ('bark_sender/config.py', 'bark_sender/push.py', 'bark_sender/channels.py',
                'send_to_bark.py', '_self_check.py'):
        src = (BASE_DIR / rel).read_text(encoding='utf-8')
        assert not pat.search(src), f'{rel} 仍含 32 位硬编码 token 字面量'


# ------------------------------------------------------------
# llm_analyst
# ------------------------------------------------------------
def test_normalize_verdict():
    assert llm_analyst.normalize_verdict('看多') == '看多'
    assert llm_analyst.normalize_verdict('偏看空一点') == '看空'
    assert llm_analyst.normalize_verdict('', '综合判断建议卖出') == '看空'
    assert llm_analyst.normalize_verdict('', '建议买入') == '看多'
    assert llm_analyst.normalize_verdict('', '不知道') == '中性'


def test_fact_sheet_only_uses_snapshot_numbers(sample_inputs):
    hist = pd.DataFrame({
        '代码': ['605018'] * 10, '日期': pd.date_range('2026-08-01', periods=10).strftime('%Y-%m-%d'),
        '收盘': [10, 10.5, 11, 10.8, 11.2, 11.5, 11.3, 12, 12.5, 12.86],
    })
    facts = llm_analyst.build_fact_sheet(sample_inputs['stocks'][0], '弱熊', hist)
    assert '605018 长华集团' in facts and 'RSI14 52.78' in facts and '弱熊' in facts
    assert '10日涨幅% 28.6' in facts and '区间最高 12.86' in facts
    assert '本金 <3000' in facts
    assert llm_analyst._history_stats('000000', hist) == {}


def test_llm_analyst_skips_without_key(no_llm, capsys):
    assert llm_analyst.main([]) == 0
    assert '跳过 shadow 分析' in capsys.readouterr().out


def test_llm_analyst_evaluate_without_log(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_analyst, 'VERDICT_LOG', str(tmp_path / 'v.jsonl'))
    assert llm_analyst.evaluate()['n'] == 0


def test_llm_analyst_evaluate_hit_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_analyst, 'VERDICT_LOG', str(tmp_path / 'v.jsonl'))
    monkeypatch.setattr(llm_analyst, 'DATA_DIR', str(tmp_path))
    days = pd.date_range('2026-08-01', periods=8)
    hist = pd.DataFrame({'代码': ['600000'] * 8 + ['600001'] * 8,
                         '日期': list(days.strftime('%Y-%m-%d')) * 2,
                         '收盘': [10, 10, 11, 11, 11, 12, 12, 12] + [10, 10, 9, 9, 9, 8, 8, 8]})
    hist.to_csv(tmp_path / 'history.csv', index=False, encoding='utf-8-sig')
    with open(tmp_path / 'v.jsonl', 'w', encoding='utf-8') as f:
        f.write(json.dumps({'date': '2026-08-02', 'model': 'm', 'code': '600000', 'name': 'a', 'verdict': '看多', 'confidence': 0.7}) + '\n')
        f.write(json.dumps({'date': '2026-08-02', 'model': 'm', 'code': '600001', 'name': 'b', 'verdict': '看多', 'confidence': 0.6}) + '\n')
    res = llm_analyst.evaluate(5)
    assert res['n'] == 2 and res['看多']['n'] == 2 and res['看多']['hit_rate'] == 0.5


def test_write_outputs_shadow_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_analyst, 'RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(llm_analyst, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(llm_analyst, 'VERDICT_LOG', str(tmp_path / 'v.jsonl'))
    v = [{'code': '605018', 'name': 'x', 'verdict': '看多', 'confidence': 0.7, 'key_risk': 'k', 'action': 'a',
          'judge': 'j', 'bull': 'b', 'bear': 'r', 'rule_score': '100', 'price': '12.86'}]
    out = llm_analyst.write_outputs('20260821', 'm', v, '弱熊')
    data = json.loads(Path(out['json']).read_text(encoding='utf-8'))
    assert data['mode'] == 'shadow' and data['verdicts'][0]['verdict'] == '看多'
    assert '不影响订单' in Path(out['md']).read_text(encoding='utf-8')
    assert (tmp_path / 'v.jsonl').read_text(encoding='utf-8').count('\n') == 1


# ------------------------------------------------------------
# pipeline / self_check
# ------------------------------------------------------------
def test_pipeline_hybrid_layer_order():
    from core.pipeline import PIPELINE_STEPS
    k = list(PIPELINE_STEPS)
    assert k.index('strategy_feedback') < k.index('llm_analyst') < k.index('digest') < k.index('decision_replay') < k.index('bark_push')
    assert k.index('exit_advisor') < k.index('position_sizing')
    assert k.index('self_check') < k.index('goal_metrics') < k.index('auto_heal')  # v8.7：goal_metrics 读当日自检
    for name in ('llm_analyst', 'digest', 'decision_replay'):
        assert k.count(name) == 1
        assert os.path.exists(BASE_DIR / PIPELINE_STEPS[name]['script'])


def test_self_check_lists_v87_files():
    src = (BASE_DIR / 'ops' / 'health.py').read_text(encoding='utf-8')  # S2 迁移：_self_check.py → ops/health.py
    assert 'v87_new' in src and 'core/llm.py' in src and 'bark_sender/channels.py' in src
    assert 'v86_new + v87_new' in src
