import os, glob, re, json
from html import escape
from datetime import datetime, timedelta, date
import streamlit as st
import pandas as pd
import numpy as np

# 性能：plotly（go/px）与交易分析模块改为函数内惰性导入——
# 原模块级导入让 app 每次启动都要付 ~0.6s 的绘图库加载成本，而多数页面用不到图表。
# 用到的地方：render_picks_page/render_market_status_page(px)、
# render_backtest_page/render_market_status_page/render_system_health_page(go)。
# trade_analyzer/log_real_trade 仅在「我的交易」页用到，随页导入。

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

from .loaders import (
load_latest_picks, load_index_data, load_evaluation,
load_daily_insight, run_pipeline_step, load_all_system_picks, load_current_prices
)

def render_picks_page():
    st.title("🎯 今日选股")
    st.caption("先确认数据是否新鲜，再看首选与风险；具体买卖数量请以“模拟交易”页的订单为准。")

    stocks_df, pick_date, pick_file = load_latest_picks()

    if stocks_df is None or len(stocks_df) == 0:
        st.warning("暂无选股数据。请先运行策略或等待15:30自动流水线。")
    else:
        # 顶部：日期 + 第一名醒目卡片
        date_str = f"{pick_date[:4]}/{pick_date[4:6]}/{pick_date[6:]}"
        # 数据新鲜度提醒：隔了 2 天以上就明说，别让用户拿旧榜单当今日推荐
        try:
            _pick_dt = datetime.strptime(pick_date, "%Y%m%d").date()
            _age_days = (date.today() - _pick_dt).days
        except Exception:
            _age_days = 0
        if _age_days >= 2:
            st.warning(f"⚠️ 这份选股榜单是 {_age_days} 天前（{date_str}）生成的，可能已过时。"
                       f"可到「⚙ 流水线控制」页手动运行选股，或等待交易日 15:30 自动流水线更新。")
        top = stocks_df.iloc[0]

        col_date, col_top = st.columns([1.15, 3.85])
        with col_date:
            st.markdown(
                f'<div class="metric-card blue"><div class="label">选股日期</div>'
                f'<div class="big-number compact">{escape(date_str)}</div>'
                f'<div class="card-detail">信号生成日</div></div>',
                unsafe_allow_html=True,
            )
        with col_top:
            risk_text = str(top["风险"])
            risk_class = {"低": "risk-low", "中": "risk-medium", "高": "risk-high"}.get(
                risk_text, "risk-medium"
            )
            st.markdown(
                f'<div class="metric-card featured">'
                f'<div class="label">今日首选</div>'
                f'<div class="big-number">{escape(str(top["名称"]))} ({escape(str(top["代码"]))})</div>'
                f'<div class="card-detail">现价 {top["最新价"]:.2f} · 评分 {top["评分"]}分'
                f'<span class="risk-pill {risk_class}">风险{escape(risk_text)}</span></div>'
                f'<div class="card-detail">{escape(str(top["选入理由"]))}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # 精简选股表 — 只留核心列
        st.subheader(f"全部 {len(stocks_df)} 只候选")
        display_df = stocks_df.copy()
        display_df['涨跌幅'] = display_df['涨跌幅'].apply(lambda x: f"{x:+.2f}%")
        display_df['最新价'] = display_df['最新价'].apply(lambda x: f"{x:.2f}")

        show_cols = ['排名', '代码', '名称', '最新价', '涨跌幅', '评分', '风险', '选入理由']
        available = [c for c in show_cols if c in display_df.columns]
        st.dataframe(display_df[available], width="stretch", hide_index=True)

        # 图表折叠 — 不占默认视觉空间
        with st.expander("📊 评分分布图", expanded=False):
            import plotly.express as px
            fig = px.bar(stocks_df, x='名称', y='评分', color='评分',
                         color_continuous_scale='RdYlGn', title='评分分布')
            fig.update_layout(height=300)
            st.plotly_chart(fig, width="stretch")

    # 每日洞察
    insight = load_daily_insight()
    if insight:
        st.divider()
        st.subheader("💡 今日洞察")
        lines = [l.strip() for l in insight.split('\n') if len(l.strip()) > 30 and not l.startswith('#') and not l.startswith('>')]
        for l in lines[:3]:
            st.markdown(f"- {l[:150]}")


# ============================================================
# 页面2：回测仪表盘
# ============================================================


def render_backtest_page():
    st.title("📊 回测分析")
    st.caption("先看净收益与超额收益，再结合胜率和市场分段判断策略是否值得继续验证。")

    eval_content = load_evaluation()

    if eval_content is None:
        st.warning("暂无回测数据。请先运行回测。")
    else:
        # 提取关键指标
        net10_match = re.search(r'持有10日.*?净收益.*?([+-]?\d+\.?\d*)%', eval_content)
        wr10_match = re.search(r'持有10日.*?胜率.*?(\d+\.?\d*)%', eval_content)
        excess_match = re.search(r'超额收益.*?([+-]?\d+\.?\d*)%', eval_content)
        dc_match = re.search(r'死叉出场.*?(\d+\.?\d*)%', eval_content)

        net10 = float(net10_match.group(1)) if net10_match else 0
        wr10 = float(wr10_match.group(1)) if wr10_match else 0
        excess = float(excess_match.group(1)) if excess_match else 0
        dc_rate = float(dc_match.group(1)) if dc_match else 0

        # KPI 卡片
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            net_color = "red" if net10 > 0 else ("green" if net10 < 0 else "blue")
            st.markdown(
                f'<div class="metric-card {net_color}"><div class="label">10日净收益</div><div class="big-number">{net10:+.2f}%</div></div>',
                unsafe_allow_html=True)
        with col2:
            st.markdown(
                f'<div class="metric-card blue"><div class="label">10日胜率</div><div class="big-number">{wr10:.1f}%</div></div>',
                unsafe_allow_html=True)
        with col3:
            color = "red" if excess > 0 else "green"  # A股惯例：红涨绿跌
            st.markdown(
                f'<div class="metric-card {color}"><div class="label">超额收益(vs沪深300)</div><div class="big-number">{excess:+.2f}%</div></div>',
                unsafe_allow_html=True)
        with col4:
            st.markdown(
                f'<div class="metric-card warning"><div class="label">死叉出场率</div><div class="big-number">{dc_rate:.1f}%</div></div>',
                unsafe_allow_html=True)

        # 提取持有期详细数据
        st.divider()
        st.subheader("📈 多持有期对比")

        periods = []
        for hold in ['1日', '5日', '10日']:
            net_match = re.search(f'持有{hold}.*?净收益.*?([+-]?\\d+\\.?\\d*)%', eval_content)
            wr_match = re.search(f'持有{hold}.*?胜率.*?(\\d+\\.?\\d*)%', eval_content)
            gross_match = re.search(f'持有{hold}.*?毛收益.*?([+-]?\\d+\\.?\\d*)%', eval_content)
            if net_match:
                periods.append({
                    '持有期': hold,
                    '净收益(%)': float(net_match.group(1)),
                    '胜率(%)': float(wr_match.group(1)) if wr_match else 0,
                    '毛收益(%)': float(gross_match.group(1)) if gross_match else 0,
                })
        if periods:
            import plotly.graph_objects as go
            df_periods = pd.DataFrame(periods)
            fig = go.Figure()
            fig.add_trace(go.Bar(name='净收益(%)', x=df_periods['持有期'], y=df_periods['净收益(%)'],
                                 marker_color=['#2196F3', '#FF9800', '#4CAF50'], text=df_periods['净收益(%)'].apply(lambda x: f'{x:+.2f}%'),
                                 textposition='auto'))
            fig.add_trace(go.Scatter(name='胜率(%)', x=df_periods['持有期'], y=df_periods['胜率(%)'],
                                     yaxis='y2', mode='lines+markers', line=dict(color='#e74c3c', width=3),
                                     marker=dict(size=12)))
            fig.update_layout(
                title='持有期净收益 vs 胜率',
                yaxis=dict(title='净收益(%)', side='left'),
                yaxis2=dict(title='胜率(%)', overlaying='y', side='right', range=[0, 100]),
                height=400,
                legend=dict(x=0.01, y=0.99),
            )
            st.plotly_chart(fig, width="stretch")

        # 牛熊对比
        st.divider()
        st.subheader("🐂🐻 牛熊市表现对比")
        bull_match = re.search(r'牛市.*?胜率.*?(\d+\.?\d*)%.*?净收益.*?([+-]?\d+\.?\d*)%', eval_content)
        bear_match = re.search(r'熊市.*?胜率.*?(\d+\.?\d*)%.*?净收益.*?([+-]?\d+\.?\d*)%', eval_content)

        if bull_match and bear_match:
            bull_wr, bull_net = float(bull_match.group(1)), float(bull_match.group(2))
            bear_wr, bear_net = float(bear_match.group(1)), float(bear_match.group(2))

            col_bull, col_bear = st.columns(2)
            with col_bull:
                st.markdown(
                    f'<div class="metric-card red"><div class="label">🐂 牛市 (10日持有)</div>'
                    f'<div>胜率: {bull_wr:.1f}% | 净收益: {bull_net:+.2f}%</div></div>',
                    unsafe_allow_html=True)
            with col_bear:
                st.markdown(
                    f'<div class="metric-card green"><div class="label">🐻 熊市/震荡 (10日持有)</div>'
                    f'<div>胜率: {bear_wr:.1f}% | 净收益: {bear_net:+.2f}%</div></div>',
                    unsafe_allow_html=True)

        # 显示原始报告
        with st.expander("📄 完整回测报告"):
            st.markdown(eval_content)


# ============================================================
# 页面3：市场状态
# ============================================================


def render_market_status_page():
    st.title("📉 沪深300 市场状态")
    st.caption("用趋势和波动判断风险环境；红色代表上涨，绿色代表下跌或防守。")

    idx = load_index_data()

    if idx is None:
        st.warning("暂无指数数据，请先获取沪深300数据。")
    else:
        latest = idx.iloc[-1]
        ma20 = latest.get('MA20', 0)
        close = latest['收盘']
        is_bull = close > ma20 if pd.notna(ma20) else False

        # 状态卡片（A股惯例：牛市/上涨=红，熊市/下跌=绿）
        col1, col2, col3 = st.columns(3)
        with col1:
            if is_bull:
                st.markdown(
                    f'<div class="metric-card red"><div class="label">当前市场状态</div><div class="big-number">🐂 牛市</div><div>收盘 {close:.0f} > MA20 {ma20:.0f}</div></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div class="metric-card green"><div class="label">当前市场状态</div><div class="big-number">🐻 熊市/震荡</div><div>收盘 {close:.0f} ≤ MA20 {ma20:.0f}</div></div>',
                    unsafe_allow_html=True)
        with col2:
            ret_5d = (idx['收盘'].iloc[-1] / idx['收盘'].iloc[-6] - 1) * 100 if len(idx) > 5 else 0
            st.metric("5日涨跌", f"{ret_5d:+.2f}%", delta_color="inverse")
        with col3:
            ret_20d = (idx['收盘'].iloc[-1] / idx['收盘'].iloc[-21] - 1) * 100 if len(idx) > 20 else 0
            st.metric("20日涨跌", f"{ret_20d:+.2f}%", delta_color="inverse")

        # 走势图
        st.divider()
        st.subheader("📈 沪深300 走势 (MA5/MA20)")

        import plotly.graph_objects as go
        plot_df = idx.tail(90).copy()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=plot_df['日期'], y=plot_df['收盘'], name='收盘价',
                                 line=dict(color='#2196F3', width=2)))
        fig.add_trace(go.Scatter(x=plot_df['日期'], y=plot_df['MA5'], name='MA5',
                                 line=dict(color='#FF9800', width=1, dash='dash')))
        fig.add_trace(go.Scatter(x=plot_df['日期'], y=plot_df['MA20'], name='MA20',
                                 line=dict(color='#4CAF50', width=2, dash='dot')))

        # 标记牛熊区域：按状态变化合并成色带（原来逐日 add_vrect 会生成几十个形状，拖慢渲染）
        bands = []
        prev_state = None
        band_start = None
        for i in range(len(plot_df)):
            row = plot_df.iloc[i]
            state = None
            if pd.notna(row['MA20']):
                state = 'bull' if row['收盘'] > row['MA20'] else 'bear'
            if state != prev_state:
                if prev_state is not None:
                    bands.append((prev_state, band_start, plot_df.iloc[i - 1]['日期']))
                band_start = row['日期']
                prev_state = state
        if prev_state is not None:
            bands.append((prev_state, band_start, plot_df.iloc[-1]['日期']))
        for state, x0, x1 in bands:
            color = 'rgba(231,76,60,0.08)' if state == 'bull' else 'rgba(39,174,96,0.08)'
            fig.add_vrect(x0=x0, x1=x1, fillcolor=color, layer='below', line_width=0)

        fig.update_layout(height=450, hovermode='x unified',
                          xaxis_title='', yaxis_title='指数点位')
        st.plotly_chart(fig, width="stretch")

        # 日收益率分布
        st.divider()
        col_vol1, col_vol2 = st.columns(2)
        with col_vol1:
            import plotly.express as px
            rets = idx['ret'].dropna().tail(60)
            fig = px.histogram(rets * 100, nbins=30, title='近60日日收益率分布',
                               labels={'value': '日收益率(%)', 'count': '频次'})
            fig.add_vline(x=0, line_dash='dash', line_color='red')
            fig.update_layout(height=350)
            st.plotly_chart(fig, width="stretch")
        with col_vol2:
            volatility = rets.std() * np.sqrt(252) * 100
            win_days = (rets > 0).sum()
            total_days = len(rets)
            st.markdown(f"""
            ### 📊 市场统计 (近60日)

            | 指标 | 数值 |
            |------|------|
            | 年化波动率 | {volatility:.1f}% |
            | 上涨天数 | {win_days}/{total_days} ({win_days/total_days*100:.0f}%) |
            | 日均涨跌 | {rets.mean()*100:+.2f}% |
            | 最大单日涨幅 | {rets.max()*100:+.2f}% |
            | 最大单日跌幅 | {rets.min()*100:+.2f}% |
            """)


# ============================================================
# 页面4：流水线控制
# ============================================================


def render_pipeline_control_page():
    st.title("⚙ 流水线控制面板")

    st.caption("手动触发量化流水线各步骤，或一键执行全流程。自动化流水线每周一至五 15:37 自动执行。")

    st.divider()

    # 一键全流程
    st.subheader("🚀 一键全流程")
    st.caption("全程约 3-10 分钟（含联网抓取与研究生成），执行期间请勿关闭页面；也可以只点下方单个步骤。")
    confirm_full_pipeline = st.checkbox(
        "我已确认：这会联网更新数据、运行分析，并在成功后发送 Bark 推送",
        key="confirm_full_pipeline",
    )
    if st.button(
        "▶ 执行全流程（选股→回测→洞察→推送）",
        type="primary",
        width="stretch",
        disabled=not confirm_full_pipeline,
    ):
        steps = [
            (['strategy.py'], '选股策略'),
            (['enhanced_backtest.py'], '回测引擎'),
            (['research_agent.py', '--daily', '今日市场复盘'], '每日洞察(研究代理--daily)'),
            (['send_to_bark.py'], 'Bark推送'),
        ]
        progress = st.progress(0)
        status = st.empty()

        results_log = []
        for i, (script, label) in enumerate(steps):
            status.info(f"[{i+1}/4] 正在运行: {label}...")
            success, output = run_pipeline_step(script, label)
            results_log.append((label, success, output))
            progress.progress((i + 1) / 4)

        progress.empty()
        for label, success, output in results_log:
            icon = "✅" if success else "❌"
            st.markdown(f"{icon} **{label}**")
            if not success:
                st.error(f"```\n{output[:300]}\n```")

        if all(s for _, s, _ in results_log):
            st.success("🎉 全流程执行成功！Bark 推送已发送。")
            st.cache_data.clear()
        else:
            st.warning("⚠️ 部分步骤失败，请检查上方日志。")

    st.divider()

    # 分步执行
    st.subheader("📋 分步执行")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("📊 运行选股", width="stretch"):
            with st.spinner("正在筛选..."):
                ok, out = run_pipeline_step('strategy.py', '选股')
                if ok:
                    st.success("选股完成")
                    st.cache_data.clear()
                else:
                    st.error(f"失败：{out[:200]}")
    with col2:
        if st.button("📈 运行回测", width="stretch"):
            with st.spinner("正在回测..."):
                ok, out = run_pipeline_step('enhanced_backtest.py', '回测')
                if ok:
                    st.success("回测完成")
                    st.cache_data.clear()
                else:
                    st.error(f"失败：{out[:200]}")
    with col3:
        if st.button("🔬 生成洞察", width="stretch"):
            with st.spinner("正在分析..."):
                ok, out = run_pipeline_step(['research_agent.py', '--daily', '市场复盘'], '洞察')
                if ok:
                    st.success("洞察已生成")
                else:
                    st.error(f"失败：{out[:200]}")
    with col4:
        if st.button("📤 发送推送", width="stretch"):
            with st.spinner("正在推送..."):
                ok, out = run_pipeline_step('send_to_bark.py', '推送')
                if ok:
                    st.success("推送已发送")
                else:
                    st.error(f"失败：{out[:200]}")

    st.divider()

    # 历史报告列表
    st.subheader("📂 历史文件")
    tab1, tab2, tab3 = st.tabs(["选股报告", "回测报告", "研究洞察"])

    with tab1:
        picks = sorted(glob.glob(os.path.join(RESULTS_DIR, 'pick_*.md')), reverse=True)
        for p in picks[:10]:
            st.markdown(f"- `{os.path.basename(p)}`")
    with tab2:
        evals = sorted(glob.glob(os.path.join(RESULTS_DIR, 'honest_evaluation.md')), reverse=True)
        for e in evals[:10]:
            st.markdown(f"- `{os.path.basename(e)}`")
        abs_ = sorted(glob.glob(os.path.join(REPORTS_DIR, 'ab_test_*.md')), reverse=True)
        for a in abs_:
            st.markdown(f"- `{os.path.basename(a)}`")
    with tab3:
        researches = sorted(glob.glob(os.path.join(REPORTS_DIR, '*.md')), reverse=True)
        for r in researches[:10]:
            st.markdown(f"- `{os.path.basename(r)}`")


# ============================================================
# 页面5：模拟交易
# ============================================================


def _render_replay_block():
    """v8.6: 严格跟单回放 — 读 sim_results/replay_*.csv，由 replay_picks.py 生成。

    回答用户的问题：「如果从 5/12 起每天严格按系统推荐买卖，现在状态怎么样？」
    """
    replay_eq = os.path.join(BASE_DIR, 'sim_results', 'replay_equity.csv')
    replay_tr = os.path.join(BASE_DIR, 'sim_results', 'replay_trades.csv')

    st.subheader("📊 严格跟单回放")
    st.caption("假设从首个选股日起，每天严格按系统评分最高的股票买入、止损/止盈/到期卖出，小资金条件下的真实曲线（本金跟随系统配置）。")

    if not os.path.exists(replay_eq):
        st.info("暂无回放数据。运行 `python replay_picks.py` 生成。")
        st.divider()
        return

    try:
        eq_df = pd.read_csv(replay_eq)
    except Exception as exc:
        st.warning(f"回放数据读取失败：{exc}")
        st.divider()
        return

    if len(eq_df) == 0:
        st.info("回放文件为空。")
        st.divider()
        return

    from core.config import get as _cfg_get
    initial_capital = float(_cfg_get('sim.initial_capital', 2400))

    last = eq_df.iloc[-1]
    cur_equity = float(last.get('equity', initial_capital))
    cur_ret_pct = float(last.get('return_pct', 0.0))
    cur_holding = str(last.get('holding', '') or '空仓')
    start_date = str(eq_df.iloc[0]['date'])
    end_date = str(last['date'])
    days = len(eq_df)

    # 最大回撤
    eq_series = eq_df['equity'].astype(float)
    rolling_max = eq_series.cummax()
    drawdown = (eq_series / rolling_max - 1) * 100
    max_dd = float(drawdown.min())

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        delta_color = "inverse" if cur_ret_pct >= 0 else "normal"  # A股惯例：红涨绿跌
        st.metric("当前净值", f"{cur_equity:,.2f}元", delta=f"{cur_ret_pct:+.2f}%")
    with col2:
        st.metric("最大回撤", f"{max_dd:+.2f}%")
    with col3:
        st.metric("回放天数", f"{days}天",
                  help=f"{start_date} → {end_date}")
    with col4:
        st.metric("当前持仓", cur_holding if cur_holding != 'nan' else '空仓')

    # 净值曲线
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq_df['date'], y=eq_df['equity'],
                             mode='lines+markers', name='严格跟单净值',
                             line=dict(color='#e67e22', width=2)))
    fig.add_hline(y=initial_capital, line_dash="dash", line_color="gray",
                  annotation_text=f"初始 {initial_capital:,.0f}元")
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0),
                      hovermode='x unified', yaxis_title='元')
    st.plotly_chart(fig, width="stretch")

    # 已成交记录
    if os.path.exists(replay_tr):
        try:
            tr_df = pd.read_csv(replay_tr)
        except Exception:
            tr_df = pd.DataFrame()
        if len(tr_df) > 0:
            st.markdown(f"**已完成交易（{len(tr_df)} 笔）**")
            display_tr = tr_df.copy()
            rename_map = {'code': '代码', 'name': '名称', 'entry_date': '买入日',
                          'exit_date': '卖出日', 'entry_price': '买价',
                          'exit_price': '卖价', 'shares': '股数', 'pnl': '盈亏',
                          'pnl_pct': '盈亏%', 'reason': '出场原因',
                          'held_days': '持有天数'}
            display_tr = display_tr.rename(columns={k: v for k, v in rename_map.items()
                                                    if k in display_tr.columns})
            st.dataframe(display_tr, width="stretch", hide_index=True)
        else:
            st.caption("尚未触发任何完整买卖循环（持仓中或空仓）。")

    st.caption(f"提示：回放数据由 `replay_picks.py` 离线生成，不影响真实账户。"
               f"重新生成命令：`python replay_picks.py`")
    st.divider()


def _render_today_orders_block():
    """今日订单区块 — 合并页与独立页共用，避免重复逻辑。"""
    orders_dir = os.path.join(BASE_DIR, 'orders')
    if not os.path.exists(orders_dir):
        st.info("订单目录不存在。请先运行 position_sizer.py。")
        return
    order_files = sorted(glob.glob(os.path.join(orders_dir, 'daily_orders_*.md')), reverse=True)
    json_files = sorted(glob.glob(os.path.join(orders_dir, 'daily_orders_*.json')), reverse=True)
    if not order_files:
        st.info("暂无订单。运行 position_sizer.py 生成今日订单。")
        return
    try:
        with open(order_files[0], 'r', encoding='utf-8') as f:
            st.markdown(f.read())
    except Exception as e:
        st.warning(f"读取订单文件失败：{e}")
    if json_files:
        try:
            with open(json_files[0], 'r', encoding='utf-8') as f:
                st.download_button("下载订单JSON", f.read(),
                                   file_name=os.path.basename(json_files[0]),
                                   mime='application/json')
        except Exception:
            pass


def _reset_sim_account(state_path, capital):
    """按新本金重建模拟账户（当前空仓场景：直接清零起算，基线=本金）。

    同时清空权益曲线和交易历史 —— 旧基线下的曲线/成交记录和新本金混在一起会误导
    （否则会出现 total_trades=0 却仍列出旧成交的矛盾展示）。文件由 sim 引擎下次运行重建。
    旁路文件从 state_path 所在目录推导（生产即 sim_results/），保证三者同目录、可隔离测试。
    """
    from utils.file_io import atomic_write_json
    now = datetime.now()
    state = {
        'cash': capital, 'total_invested': 0.0, 'equity': capital,
        'initial_capital': capital, 'positions': [],
        'created': now.strftime('%Y-%m-%d'),
        'total_trades': 0, 'winning_trades': 0, 'total_pnl': 0.0,
        'total_commission': 0.0, 'total_stamp_tax': 0.0, 'total_trade_volume': 0.0,
        '_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
        '_reset_reason': 'manual_capital_set',
    }
    atomic_write_json(state_path, state)
    sim_dir = os.path.dirname(state_path)
    for fname in ('equity_curve.csv', 'trade_history.csv'):
        p = os.path.join(sim_dir, fname)
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _render_capital_setting():
    """模拟本金设置入口：手填真实总资金（最高优先级）+ 没填时自动按真实订单推算。"""
    from core.config import get as _cfg_get, set_value as _cfg_set
    state_path = os.path.join(BASE_DIR, 'sim_results', 'account_state.json')
    state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            state = {}
    manual = _cfg_get('sim.manual_capital', None)
    baseline = float(state.get('initial_capital') or _cfg_get('sim.initial_capital', 2400))

    with st.expander("⚙️ 设置模拟本金（和你真实股市资金保持一致）",
                     expanded=(manual is None and not state)):
        if manual is not None:
            st.caption(f"当前：手动设定 **{float(manual):,.0f} 元**")
        else:
            st.caption(f"当前：自动按真实订单推算 **{baseline:,.0f} 元**（你没手动填，用的是真实买卖净投入）")
        new_cap = st.number_input("我的真实总资金（元）", min_value=0.0,
                                  value=float(baseline), step=100.0, format="%.2f",
                                  help="填你实际放在股市里的总钱数；填了就以这个为准，重置模拟账户重新起算。")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 保存并重置模拟账户", width="stretch"):
                if new_cap <= 0:
                    st.error("金额要大于 0")
                else:
                    val = round(float(new_cap), 2)
                    _cfg_set('sim.manual_capital', val)
                    _reset_sim_account(state_path, val)
                    st.success(f"已把模拟本金设为 {val:,.0f} 元，账户按新本金重新起算。")
                    st.rerun()
        with c2:
            if manual is not None:
                if st.button("↩️ 取消手动，改回自动推算", width="stretch"):
                    # 当场显式重置到自动推算值，避免遗留旧基线导致下次加载静默调整现金
                    _cfg_set('sim.manual_capital', None)
                    try:
                        import sim_trade as _sim
                        auto_cap = float(_sim.resolve_initial_capital())
                    except Exception:
                        auto_cap = float(_cfg_get('sim.initial_capital', 2400))
                    _reset_sim_account(state_path, auto_cap)
                    st.success(f"已改回自动推算（约 {auto_cap:,.0f} 元），账户已按此重新起算。")
                    st.rerun()


def render_sim_trading_page():
    st.title("💰 模拟交易")
    st.caption("先处理今日动作并核对账户状态；本金设置、回放与历史分析默认收起，减少误读。")

    sim_state = os.path.join(BASE_DIR, 'sim_results', 'account_state.json')
    sim_equity = os.path.join(BASE_DIR, 'sim_results', 'equity_curve.csv')
    sim_trades = os.path.join(BASE_DIR, 'sim_results', 'trade_history.csv')
    state = None
    initial_capital = None

    # 首屏先回答“账户现在怎样”，再进入订单与分析。
    if os.path.exists(sim_state):
        import json as _json
        with open(sim_state, 'r', encoding='utf-8') as f:
            state = _json.load(f)
        from core.config import get as _cfg_get
        initial_capital = float(state.get('initial_capital') or _cfg_get('sim.initial_capital', 2400))
        equity = state.get('equity', initial_capital)
        cash = state.get('cash', initial_capital)
        pnl = state.get('total_pnl', 0)
        total = state.get('total_trades', 0)
        winning = state.get('winning_trades', 0)
        ret_pct = (equity / initial_capital - 1) * 100 if initial_capital else 0
        win_rate = winning / max(1, total) * 100

        st.subheader("账户概览")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("总权益", f"{equity:,.0f}元", delta=f"{ret_pct:+.2f}%", delta_color="inverse")
        with col2:
            st.metric("可用现金", f"{cash:,.0f}元")
        with col3:
            st.metric("累计盈亏", f"{pnl:+,.0f}元", delta=f"{pnl:+.0f}元", delta_color="inverse")
        with col4:
            st.metric("交易胜率", f"{win_rate:.1f}%", help=f"已完成 {total} 笔交易")
    else:
        st.info("模拟交易尚未开始。运行 sim_trade.py 初始化账户。")

    st.divider()

    # 今日订单（v8.x：原独立「今日订单」页已并入本页顶部，前后衔接：系统让你买卖啥 → 账户照单成交后啥样）
    st.header("📋 今日动作")
    _render_today_orders_block()

    st.divider()
    st.header("账户详情")

    # 本金设置入口（手填真实总资金，没填则自动推算）
    with st.expander("⚙️ 本金设置（会重置模拟账户）", expanded=False):
        _render_capital_setting()

    # v8.6: 严格跟单回放（用户最想看的：纪律拉满每天跟系统推荐买卖，今天什么状态）
    with st.expander("📊 严格跟单回放（独立验证，不影响账户）", expanded=False):
        _render_replay_block()

    if state is None:
        pass
    else:
        # v8.x 修复：收益率分母用账户真实基线（state.initial_capital），
        # 不再写死 config 1200 —— 否则页面收益率和引擎基线不一致，显示假盈亏。
        # 权益曲线
        st.divider()
        st.subheader("权益曲线")
        if os.path.exists(sim_equity):
            eq_df = pd.read_csv(sim_equity)
            if len(eq_df) > 1:
                import plotly.graph_objects as go
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=eq_df['日期'], y=eq_df['总权益'], mode='lines+markers',
                                        name='总权益', line=dict(color='#1f77b4', width=2)))
                fig.add_hline(y=initial_capital, line_dash="dash", line_color="gray",
                             annotation_text=f"初始资金 {initial_capital:,.0f}元")
                fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                                 hovermode='x unified')
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("权益曲线需要至少2个数据点")
        else:
            st.caption("暂无权益数据")

        # 当前持仓
        st.divider()
        st.subheader(f"当前持仓 ({len(state.get('positions', []))}只)")
        positions = state.get('positions', [])
        if positions:
            pos_df = pd.DataFrame(positions)
            cols = ['code', 'name', 'entry_price', 'current_price', 'shares', 'hold_days',
                   'unrealized_pnl', 'unrealized_pnl_pct', 'stop_loss', 'take_profit']
            display_cols = [c for c in cols if c in pos_df.columns]
            pos_df = pos_df[display_cols]
            pos_df.columns = ['代码', '名称', '入场价', '现价', '股数', '持有天数',
                             '浮动盈亏', '盈亏%', '止损价', '止盈价'][:len(display_cols)]
            st.dataframe(pos_df, width="stretch", hide_index=True)
        else:
            st.caption("当前无持仓")

        # 交易历史
        st.divider()
        st.subheader("交易历史")
        if os.path.exists(sim_trades):
            trades_df = pd.read_csv(sim_trades)
            if len(trades_df) > 0:
                st.dataframe(trades_df.tail(20), width="stretch", hide_index=True)
                # 出场统计
                st.caption("出场原因分布")
                if '出场原因' in trades_df.columns:
                    reason_counts = trades_df['出场原因'].value_counts()
                    st.bar_chart(reason_counts)
            else:
                st.caption("暂无交易记录")
        else:
            st.caption("暂无交易历史")


# ============================================================

        # ── 系统跟随模拟 ──
        st.divider()
        st.subheader("📈 候选股票浮盈统计")
        st.caption("每个交易日 Top20 候选的当前浮盈分布（不是订单建议，也不是实际买入）。"
                   "想看「严格跟单后的真实曲线」请看本页顶部「严格跟单回放」。")

        picks_df = load_all_system_picks()
        current_prices = load_current_prices()

        if picks_df.empty:
            st.info("暂无系统选股记录。运行选股策略后将自动生成。")
        elif not current_prices:
            st.warning("暂无当前价格数据。请先获取股票行情。")
        else:
            # Compute P&L for each pick
            pnl_rows = []
            for _, pick in picks_df.iterrows():
                code = pick['代码']
                info = current_prices.get(code, {})
                if info:
                    cur_price = info['price']
                    pnl_pct = (cur_price / pick['入场价'] - 1) * 100
                    status = '🔴 盈利' if pnl_pct > 0 else ('🟢 亏损' if pnl_pct < 0 else '⚪ 持平')
                    pnl_rows.append({
                        '选股日期': pick['选股日期'],
                        '代码': code,
                        '名称': pick['名称'],
                        '入场价': pick['入场价'],
                        '当前价': cur_price,
                        '收益率%': round(pnl_pct, 2),
                        '状态': status,
                    })
                else:
                    pnl_rows.append({
                        '选股日期': pick['选股日期'],
                        '代码': code,
                        '名称': pick['名称'],
                        '入场价': pick['入场价'],
                        '当前价': 0,
                        '收益率%': None,
                        '状态': '⚪ 无数据',
                    })

            if pnl_rows:
                pnl_df = pd.DataFrame(pnl_rows)
                valid = pnl_df[pnl_df['收益率%'].notna()]

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    if len(valid) > 0:
                        avg_ret = valid['收益率%'].mean()
                        st.metric("平均收益率", f"{avg_ret:+.2f}%", delta=f"{len(valid)}只股票")
                    else:
                        st.metric("平均收益率", "N/A")
                with col2:
                    if len(valid) > 0:
                        wr = (valid['收益率%'] > 0).sum() / len(valid) * 100
                        st.metric("胜率", f"{wr:.1f}%")
                    else:
                        st.metric("胜率", "N/A")
                with col3:
                    num_dates_for_label = pnl_df['选股日期'].nunique()
                    avg_per_day = len(pnl_df) / max(1, num_dates_for_label)
                    st.metric("候选项总数", f"{len(pnl_df)}",
                              help=f"= {num_dates_for_label}天 × 每天约{avg_per_day:.0f}只候选；"
                                   f"非订单建议，也非实际买入")
                with col4:
                    num_dates = pnl_df['选股日期'].nunique()
                    st.metric("选股天数", f"{num_dates}天")

                # Bar chart by date
                if len(valid) > 0:
                    st.divider()
                    date_stats = valid.groupby('选股日期').agg(
                        平均收益=('收益率%', 'mean'),
                        股票数=('收益率%', 'count'),
                        胜率=('收益率%', lambda x: (x > 0).sum() / len(x) * 100)
                    ).reset_index()

                    import plotly.graph_objects as go
                    colors = ['#f44336' if v >= 0 else '#4CAF50' for v in date_stats['平均收益']]  # 红涨绿跌
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=date_stats['选股日期'], y=date_stats['平均收益'],
                                         marker_color=colors,
                                         text=[f'{v:+.1f}%' for v in date_stats['平均收益']],
                                         textposition='auto', name='平均收益'))
                    fig.update_layout(height=350, yaxis_title='平均收益率(%)',
                                     xaxis_title='选股日期')
                    st.plotly_chart(fig, width="stretch")

                # Detail table
                with st.expander("📋 单只股票明细"):
                    display = pnl_df.copy()
                    display['入场价'] = display['入场价'].apply(lambda x: f'{x:.2f}')
                    display['当前价'] = display['当前价'].apply(lambda x: f'{x:.2f}' if x > 0 else '-')
                    display['收益率%'] = display['收益率%'].apply(lambda x: f'{x:+.2f}%' if x is not None else '-')
                    st.dataframe(
                        display[['选股日期', '代码', '名称', '入场价', '当前价', '收益率%', '状态']],
                        width="stretch", hide_index=True,
                    )


# 页面6：成本看板
# ============================================================


def render_cost_dashboard_page():
    st.title("💸 成本看板")
    st.caption("区分本地计算与模型成本，优先关注异常增长，不必逐项查看正常记录。")
    st.caption("成本优先原则：数据清洗、格式转换、简单计算在本地完成，LLM仅用于决策和研究")

    try:
        from cost_tracker import get_cost_summary, load_cost_logs, PIPELINE_STEPS_LOCAL, PIPELINE_STEPS_LLM
        summary = get_cost_summary()
        logs_df = load_cost_logs(days=30)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("今日LLM成本", f"CNY {summary['today_cost']:.4f}",
                     delta=f"{summary['today_calls']}次调用")
        with col2:
            st.metric("本月LLM成本", f"CNY {summary['month_cost']:.4f}",
                     delta=f"{summary['month_calls']}次调用")
        with col3:
            st.metric("本地计算节省", f"CNY {summary['month_cost']*3:.4f}",
                     delta=f"{summary['local_steps']}步本地运行")

        st.divider()
        st.subheader("📈 本月成本曲线")

        if summary['daily_costs']:
            import plotly.graph_objects as go
            dates = list(summary['daily_costs'].keys())
            costs = list(summary['daily_costs'].values())
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dates, y=costs, mode='lines+markers',
                                     name='每日成本(CNY)', line=dict(color='#FF9800', width=2)))
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                             hovermode='x unified')
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无本月成本数据。运行 cost_tracker.py 生成。")

        st.divider()

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("🟢 纯本地步骤 (成本 ¥0)")
            for step in PIPELINE_STEPS_LOCAL:
                st.markdown(f"- `{step}.py`")
            st.caption(f"共 {len(PIPELINE_STEPS_LOCAL)} 步纯本地，每日节省约 CNY 1.20")

        with col_right:
            st.subheader("🟡 LLM步骤 (成本 > ¥0)")
            for step in PIPELINE_STEPS_LLM:
                st.markdown(f"- `{step}.py`")
            st.caption(f"共 {len(PIPELINE_STEPS_LLM)} 步使用LLM，每步约 CNY 0.02-0.10")

        st.divider()
        st.subheader("📋 成本优化建议")
        st.markdown("""
        - ✅ 所有数据清洗、格式转换在本地完成
        - ✅ 简单计算（RSI/MA/ATR）在本地完成
        - ✅ LLM仅用于：研究报告、策略进化、知识内化、心理助手
        - 💡 如 evolve_strategy 重复调用，检查参数格式是否正确
        - 💡 定期检查 cost_audit 报告了解月度趋势
        """)

        # 历史审计报告
        st.divider()
        st.subheader("📂 历史审计报告")
        import glob as _glob
        audit_files = sorted(_glob.glob(os.path.join(BASE_DIR, 'reports', 'cost_audit_*.md')), reverse=True)
        for af in audit_files[:10]:
            st.markdown(f"- `{os.path.basename(af)}`")

    except ImportError:
        st.warning("cost_tracker 模块未找到，请确认文件存在。")
    except Exception as e:
        st.error(f"加载成本数据失败: {e}")


# ============================================================
# 页面7：我的交易
# ============================================================


@st.cache_data(ttl=300, show_spinner=False)
def _cached_analyze_positions(base_dir):
    from trade_analyzer import analyze_current_positions
    return analyze_current_positions(base_dir)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_analyze_behavior(base_dir):
    from trade_analyzer import analyze_trade_behavior
    return analyze_trade_behavior(base_dir)


def render_my_trades_page():
    st.title("📝 我的交易")
    st.caption("先看当前持仓与系统建议，再录入成交；历史记录和情绪反馈用于复盘。")

    # ── 当前持仓分析 ──（带缓存：原来每次页面交互都重算一遍全部选股文件）
    pos_result = _cached_analyze_positions(BASE_DIR)
    positions = pos_result.get('positions', [])
    pos_recs = pos_result.get('recommendations', [])
    pos_summary = pos_result.get('summary', {})

    if positions:
        st.subheader("💼 当前持仓")

        # 第一行：持仓规模
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("持仓数", f"{pos_summary['position_count']}只")
        with col2:
            cost = pos_summary['total_cost']
            st.metric("持仓成本", f"{cost:,.0f}")
        with col3:
            mkt = pos_summary['total_market_value']
            st.metric("当前市值", f"{mkt:,.0f}")

        # 第二行：盈亏拆分（当前持仓浮动 vs 含已平仓的累计）
        col4, col5, col6 = st.columns(3)
        with col4:
            unreal_amt = pos_summary.get('unrealized_pnl', pos_summary.get('total_pnl', 0))
            unreal_pct = pos_summary.get('unrealized_pnl_pct', pos_summary.get('total_pnl_pct', 0))
            st.metric("当前持仓盈亏", f"{unreal_amt:+,.2f}", delta=f"{unreal_pct:+.2f}%",
                      delta_color="inverse",
                      help="只看当前还持有的股票：现价×股数 - 加权平均成本")
        with col5:
            realized = pos_summary.get('realized_pnl', 0)
            st.metric("已实现盈亏", f"{realized:+,.2f}",
                      help="已经卖出了结的部分（卖出回款扣手续费 - 加权成本）")
        with col6:
            total_amt = pos_summary.get('total_pnl', 0)
            total_pct = pos_summary.get('total_pnl_pct', 0)
            st.metric("累计总盈亏", f"{total_amt:+,.2f}", delta=f"{total_pct:+.2f}%",
                      delta_color="inverse",
                      help="当前持仓盈亏 + 已实现盈亏；百分比分母为累计总投入")

        # Per-position table
        pos_display = []
        for p in positions:
            cur_p_str = f"{p['当前价']:.2f}" if p['当前价'] else '-'
            pnl_str = f"{p['盈亏%']:+.2f}%"
            status = '🔴' if p['盈亏%'] > 0 else ('🟢' if p['盈亏%'] < 0 else '⚪')  # 红涨绿跌
            in_pick = '✅' if p['在今日推荐'] else '❌'
            pos_display.append({
                '代码': p['代码'], '名称': p['名称'],
                '买入日': p['买入日期'], '买入价': f"{p['买入价']:.2f}",
                '现价': cur_p_str, '盈亏': pnl_str,
                '持有': f"{p['持有天数']}天",
                '今日推荐': in_pick,
                '状态': status,
            })
        st.dataframe(pd.DataFrame(pos_display), width="stretch", hide_index=True)

        # Position-based recommendations
        if pos_recs:
            st.divider()
            st.subheader("🎯 持仓操作建议")
            for rec in pos_recs:
                text = rec['icon'] + ' **' + rec['title'] + '**  \n' + rec['message']
                t = rec['type']
                if t == 'warning':
                    st.warning(text)
                elif t == 'success':
                    st.success(text)
                else:
                    st.info(text)
    else:
        if pos_recs:
            for rec in pos_recs:
                st.info(rec['icon'] + ' ' + rec['message'])

    # 与今日推荐对比
    if positions:
        today_picks_file = sorted(glob.glob(os.path.join(RESULTS_DIR, 'pick_*.md')), reverse=True)
        if today_picks_file:
            st.divider()
            st.subheader("📊 持仓 vs 今日推荐")
            st.caption("以下今日推荐股票是你尚未持有的，可作为新增仓位的参考。")

            with open(today_picks_file[0], 'r', encoding='utf-8') as f:
                pick_content = f.read()

            held_codes = set(p['代码'] for p in positions)
            new_picks = []
            for line in pick_content.split('\n'):
                if re.match(r'\|\s*\d+\s*\|\s*\d{6}\s*\|', line):
                    parts = [p.strip() for p in line.split('|') if p.strip()]
                    if len(parts) >= 7:
                        code = parts[1]
                        if code not in held_codes:
                            name = parts[2]
                            try:
                                price = float(parts[3])
                            except ValueError:
                                price = float(parts[4]) if len(parts) > 4 else 0.0
                            new_picks.append({'代码': code, '名称': name, '推荐价': price})

            if new_picks:
                st.markdown("**建议关注（未持有 + 系统推荐）：**")
                for np_ in new_picks[:5]:
                    st.markdown(f"- {np_['名称']}({np_['代码']}) 推荐价 {np_['推荐价']:.2f}")
            else:
                st.success("你已持有今日推荐的所有股票，无需新增仓位。")

    st.divider()

    # ── 录入表单 ──
    st.subheader("📝 录入真实交易")

    col1, col2, col3 = st.columns(3)
    with col1:
        code_input = st.text_input("股票代码", max_chars=6, key="trade_code",
                                   placeholder="如 000001")
    with col2:
        name_input = st.text_input("股票名称", key="trade_name",
                                   placeholder="如 平安银行")
    with col3:
        direction_input = st.selectbox("方向", ["买入", "卖出"], key="trade_direction")

    col4, col5, col6 = st.columns(3)
    with col4:
        price_input = st.number_input("价格", min_value=0.01, step=0.01, format="%.2f",
                                      key="trade_price", value=10.00)
    with col5:
        qty_input = st.number_input("数量(股)", min_value=100, step=100,
                                    key="trade_qty", value=100)
    with col6:
        reason_input = st.text_input("下单依据", key="trade_reason",
                                     placeholder="如: 系统推荐/手动操作")

    col7, col8 = st.columns(2)
    with col7:
        date_input = st.date_input("交易日期", value=date.today(), key="trade_date")
    with col8:
        note_input = st.text_area("备注", key="trade_note", placeholder="可选",
                                  height=68)

    # Live fee calculation
    # Round-3 修复（2026-05-30）：之前显示的 commission/stamp 用 0.00025/0.0005，
    # 与 cost_model 单一真相源（0.0003 + 5 元最低）不一致 — 用户看到"佣金 0.30 元"
    # 但 calc_fee 返回的 fee 实际是 5.00 元（套用了最低佣金），数字对不上。
    if price_input > 0 and qty_input >= 100:
        from log_real_trade import calc_fee
        from cost_model import COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE
        amount = round(price_input * qty_input, 2)
        fee = calc_fee(direction_input, price_input, qty_input, amount)
        commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
        stamp = amount * STAMP_TAX_RATE if direction_input == '卖出' else 0
        st.markdown(f"成交额: **{amount:,.2f}** | 预估手续费: **{fee:.2f}** "
                    f"(佣金 {commission:.2f} + 印花税 {stamp:.2f})")

    if st.button("✅ 确认录入", type="primary", width="stretch"):
        code_clean = code_input.strip().zfill(6)
        if not code_clean.isdigit() or len(code_clean) != 6:
            st.error("股票代码必须是6位数字")
        elif not name_input.strip():
            st.error("请输入股票名称")
        elif price_input <= 0:
            st.error("价格必须大于0")
        elif qty_input < 100:
            st.error("数量至少100股")
        else:
            try:
                from log_real_trade import append_trade
                date_str = date_input.strftime('%Y-%m-%d')
                result = append_trade(date_str, code_clean, name_input.strip(),
                                     direction_input, price_input, qty_input,
                                     reason_input.strip(), note_input.strip())
                st.success(f"✅ 交易已录入！{result}")
                st.balloons()
                # Clear session state
                for k in ['trade_code', 'trade_name', 'trade_direction',
                          'trade_price', 'trade_qty', 'trade_reason',
                          'trade_date', 'trade_note']:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
            except Exception as e:
                st.error(f"录入失败: {e}")

    # ── 最近交易记录 ──
    st.divider()
    st.subheader("📋 最近交易记录")

    real_file = os.path.join(BASE_DIR, 'real_trades.csv')
    if os.path.exists(real_file):
        try:
            rt_df = pd.read_csv(real_file, dtype={'代码': str})
            if '备注' in rt_df.columns:
                rt_display = rt_df[~rt_df['备注'].str.contains('示例数据', na=False)].copy()
            else:
                rt_display = rt_df.copy()
            if len(rt_display) > 0:
                rt_display = rt_display.sort_values('日期', ascending=False).head(20)
                st.dataframe(rt_display, width="stretch", hide_index=True)
                st.caption(f"共 {len(rt_display)} 笔真实交易记录")
            else:
                st.info("暂无真实交易记录。请在上方表单中录入第一笔交易。")
        except Exception as e:
            st.warning(f"读取交易记录失败: {e}")
    else:
        st.info("交易记录文件不存在。第一笔交易录入后将自动创建。")

    # ── 智能提醒 ──
    st.divider()
    st.subheader("💡 智能交易提醒")

    try:
        insights = _cached_analyze_behavior(BASE_DIR)
        for insight in insights:
            t = insight['type']
            text = insight['icon'] + ' **' + insight['title'] + '**  \n' + insight['message']
            if t == 'warning':
                st.warning(text)
            elif t == 'success':
                st.success(text)
            elif t == 'info':
                st.info(text)
            elif t == 'tip':
                st.info(text)
    except Exception as e:
        st.warning(f"智能分析暂不可用: {e}")

    # --- v7.5 今日交易心情（轻交互反馈）---
    st.divider()
    st.subheader("今日交易心情")

    mood_file = os.path.join(DATA_DIR, 'trading_mood.csv')
    mood_options = {'开心': 'happy', '平静': 'neutral', '焦虑': 'anxious'}

    col_mood, col_save = st.columns([2, 1])
    with col_mood:
        mood_label = st.selectbox("今天交易后的心情如何？（可选，不记录也不影响任何功能）",
                                  ['（不记录）', '开心', '平静', '焦虑'],
                                  key='trade_mood')
    with col_save:
        if mood_label != '（不记录）' and st.button("记录心情", key='save_mood'):
            today_str = datetime.now().strftime('%Y-%m-%d')
            mood_val = mood_options.get(mood_label, '')
            os.makedirs(DATA_DIR, exist_ok=True)
            import csv as _csv
            file_exists = os.path.exists(mood_file)
            with open(mood_file, 'a', newline='', encoding='utf-8') as f:
                w = _csv.writer(f)
                if not file_exists:
                    w.writerow(['日期', '心情', '心情值'])
                w.writerow([today_str, mood_label, mood_val])
            st.success("心情已记录！")
            st.rerun()

    # Show recent mood
    if os.path.exists(mood_file):
        try:
            mood_df = pd.read_csv(mood_file)
            if len(mood_df) > 0:
                mood_recent = mood_df.sort_values('日期', ascending=False).head(7)
                mood_counts = mood_recent['心情'].value_counts()
                mood_display = ' '.join([f"{k}x{v}" for k, v in mood_counts.items()])
                st.caption(f"最近7天心情: {mood_display}")
        except Exception:
            pass


# 页面7：系统健康
# ============================================================


def _render_system_capability_section():
    """v8 系统能力图：当前 tier、运行模块、休眠模块（升级解锁条件）。"""
    try:
        from core.config import SYSTEM_TIER, SystemTier, get as _cfg_get
        from core.pipeline import list_steps
    except Exception as e:
        st.warning(f"Tier 系统不可用：{e}")
        return

    beginner_cap = float(_cfg_get('sim.initial_capital', 2400))
    tier_label = {
        "beginner": f"Beginner（{beginner_cap:,.0f} 元 / 手动 / 极简）",
        "advanced": "Advanced（3-10 万 / 多策略细化）",
        "pro": "Pro（20 万+ / 组合风控）",
        "auto": "Auto（50 万+ / API 自动交易）",
    }
    tier_next = {
        "beginner": ("→ Advanced", "本金达到 3 万元；解锁基本面/回测/walk-forward/蒙特卡洛/策略竞技/进化"),
        "advanced": ("→ Pro", "本金达到 20 万元；解锁组合风控 CVaR/VaR/相关性"),
        "pro": ("→ Auto", "本金达到 50 万元 + 开通量化 API；解锁券商自动下单"),
        "auto": ("已是顶级", "无需升级"),
    }

    st.subheader("🪜 系统能力图（分级解锁）")
    cur_tier = SYSTEM_TIER.value
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"**当前等级**\n\n`{cur_tier}`\n\n{tier_label.get(cur_tier, cur_tier)}")
    with col2:
        nxt_label, nxt_hint = tier_next.get(cur_tier, ("", ""))
        st.markdown(f"**升级路径**\n\n{nxt_label}\n\n_{nxt_hint}_")

    steps = list_steps()
    active = [s for s in steps if s["active"]]
    dormant_tier = [s for s in steps if not s["active"] and s["reason"] == "tier-skip"]
    sched_skip = [s for s in steps if not s["active"] and s["reason"] != "tier-skip"]

    col3, col4 = st.columns(2)
    with col3:
        st.markdown(f"**✅ 运行中（{len(active)} 项）**")
        for s in active:
            tag = " 🔒" if s.get("always_on") else ""
            st.markdown(f"- {s['label']}{tag}")
    with col4:
        if dormant_tier:
            st.markdown(f"**💤 休眠中（{len(dormant_tier)} 项，升级后解锁）**")
            for s in dormant_tier:
                st.markdown(f"- {s['label']} —— _{s['unlock_hint']}_")
        else:
            st.markdown("**💤 休眠中**\n\n_无 —— 当前 tier 已激活全部模块_")
        if sched_skip:
            st.caption(f"调度跳过 {len(sched_skip)} 项（按周/月触发，今天不运行）")

    st.caption("升级方式：修改 `data/system_config.json` 中 `tier.level`，或设置环境变量 `QUANT_TIER=advanced/pro/auto`")
    st.divider()


def render_system_health_page():
    st.title("🩺 系统健康检查")
    st.caption("先看是否存在失败或告警，再按需展开系统能力与完整报告。")

    import json as _json
    health_files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'health_check_*.md')), reverse=True)
    # 自检 JSON 文件名跟随 SYSTEM_VERSION（如 system_self_check_v86.json），
    # 旧代码写死 v75 导致永远读到 2026-05 的陈旧报告
    from core.config import SYSTEM_VERSION as _SV
    _ver_tag = _SV.replace('.', '')
    json_files = sorted(glob.glob(os.path.join(REPORTS_DIR, f'system_self_check_v{_ver_tag}.json')), reverse=True)
    if not json_files:
        json_files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'system_self_check_*.json')), reverse=True)

    if not health_files and not json_files:
        st.info("暂无健康检查数据。运行 _self_check.py 生成。")
    else:
        if json_files:
            with open(json_files[0], 'r', encoding='utf-8') as f:
                health_data = _json.load(f)
            total = health_data.get('score', {}).get('total', 0)
            passed = health_data.get('score', {}).get('passed', 0)
            warn_n = health_data.get('score', {}).get('warn', 0)
            fail_n = health_data.get('score', {}).get('fail', 0)
            overall_pct = passed / total * 100 if total > 0 else 0

            if fail_n == 0 and overall_pct >= 95:
                status_text, status_icon = '正常', '✅'
            elif fail_n <= 2 and overall_pct >= 85:
                status_text, status_icon = '警告', '⚠️'
            else:
                status_text, status_icon = '异常', '🚨'

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f'<div class="metric-card green"><div class="label">整体状态</div><div class="big-number">{status_icon} {status_text}</div></div>', unsafe_allow_html=True)
            with col2:
                st.metric("通过率", f"{overall_pct:.0f}%", delta=f"{passed}/{total}")
            with col3:
                st.metric("告警", warn_n, delta=f"{fail_n} 失败" if fail_n > 0 else "0 失败")
            with col4:
                check_time = health_data.get('timestamp', 'Unknown')
                st.metric("检查时间", check_time[:10])

            st.divider()
            st.subheader("📊 各维度得分")

            cats = {}
            for c in health_data.get('checks', []):
                cat = c['category']
                if cat not in cats:
                    cats[cat] = {'total': 0, 'passed': 0, 'fails': []}
                cats[cat]['total'] += 1
                if c['status'] == 'PASS':
                    cats[cat]['passed'] += 1
                elif c['status'] == 'FAIL':
                    cats[cat]['fails'].append(c['name'])

            cat_names = []
            cat_pcts = []
            for cat in ['file', 'data', 'import', 'metric', 'external', 'config']:
                if cat in cats:
                    cs = cats[cat]
                    pct = cs['passed'] / cs['total'] * 100 if cs['total'] > 0 else 0
                    cat_names.append(cat)
                    cat_pcts.append(pct)

            if cat_names:
                import plotly.graph_objects as go
                colors = ['#4CAF50' if p >= 90 else ('#FF9800' if p >= 70 else '#f44336') for p in cat_pcts]
                fig = go.Figure()
                fig.add_trace(go.Bar(x=cat_names, y=cat_pcts, marker_color=colors,
                                     text=[f'{p:.0f}%' for p in cat_pcts], textposition='auto'))
                fig.add_hline(y=90, line_dash='dash', line_color='green', annotation_text='健康线 90%')
                fig.add_hline(y=70, line_dash='dash', line_color='orange', annotation_text='警告线 70%')
                fig.update_layout(height=350, yaxis=dict(range=[0, 105], title='通过率(%)'),
                                 xaxis_title='检查维度')
                st.plotly_chart(fig, width="stretch")

            alerts = [c for c in health_data.get('checks', []) if c['status'] in ('FAIL', 'WARN')]
            if alerts:
                st.divider()
                st.subheader(f"🚨 告警项 ({len(alerts)})")
                for a in alerts:
                    flag = '🚨' if a['status'] == 'FAIL' else '⚠️'
                    st.markdown(f"- {flag} **{a['name']}** — {a['detail']}")
            else:
                st.success("🎉 所有检查项通过！")

        if len(health_files) >= 2:
            st.divider()
            st.subheader("📈 历史趋势")

            trend_data = []
            import re as _re
            for hf in health_files[:8][::-1]:
                hdate = os.path.basename(hf).replace('health_check_', '').replace('.md', '')
                with open(hf, 'r', encoding='utf-8') as f:
                    hcontent = f.read()
                scores = {}
                for m in _re.finditer(r'\|\s*(\w+)\s+[█░]+\s+(\d+)/(\d+)\s+\(([\d.]+)%\)', hcontent):
                    scores[m.group(1)] = float(m.group(4))
                if scores:
                    trend_data.append({'date': hdate, **scores})

            if trend_data:
                import plotly.graph_objects as go
                fig2 = go.Figure()
                for cat in ['file', 'data', 'import', 'metric', 'external', 'config']:
                    vals = [d.get(cat) for d in trend_data if cat in d]
                    dts = [d['date'] for d in trend_data if cat in d]
                    if vals:
                        fig2.add_trace(go.Scatter(x=dts, y=vals, mode='lines+markers', name=cat))
                fig2.update_layout(height=350, yaxis=dict(range=[0, 105], title='通过率(%)'),
                                 xaxis_title='日期', hovermode='x unified')
                fig2.add_hline(y=90, line_dash='dash', line_color='gray')
                st.plotly_chart(fig2, width="stretch")

        if health_files:
            with st.expander("📄 完整健康报告"):
                with open(health_files[0], 'r', encoding='utf-8') as f:
                    st.markdown(f.read())

        st.divider()
        col_action1, col_action2 = st.columns(2)
        with col_action1:
            if st.button("🔍 立即运行健康检查", width="stretch"):
                with st.spinner("正在检查系统健康..."):
                    ok, out = run_pipeline_step('_self_check.py', 'health check')
                    if ok:
                        st.success("健康检查完成！刷新页面查看结果。")
                        st.cache_data.clear()
                    else:
                        st.error(f"检查失败：{out[:200]}")
        with col_action2:
            if st.button("📤 推送健康报告", width="stretch"):
                latest_health = sorted(glob.glob(os.path.join(REPORTS_DIR, 'health_check_*.md')), reverse=True)
                if latest_health:
                    ok, out = run_pipeline_step(['send_to_bark.py', '--file', latest_health[0]], 'push health')
                    if ok:
                        st.success("健康报告已推送到Bark！")
                    else:
                        st.error(f"推送失败：{out[:200]}")
                else:
                    st.warning("暂无健康报告可推送")

    st.divider()
    with st.expander("🪜 系统能力与等级（按需查看）", expanded=False):
        _render_system_capability_section()

# ============================================================
# 页面7：今日订单
# ============================================================


def render_today_orders_page():
    # 保留函数供兼容/直链；菜单入口已并入「模拟交易」页。
    st.title("📋 今日交易订单")
    _render_today_orders_block()


# ============================================================
# 页脚
# ============================================================


