import streamlit as st


def inject_global_css():
    """注入仪表盘视觉系统；不改变任何业务数据或交易逻辑。"""
    st.markdown(
        """
<style>
    :root {
        --qs-bg: #f4f7fb;
        --qs-surface: #ffffff;
        --qs-surface-soft: #f8fafc;
        --qs-border: #dbe4ef;
        --qs-text: #132238;
        --qs-muted: #64748b;
        --qs-navy: #0f1f35;
        --qs-accent: #16a3a5;
        --qs-up: #c83f49;
        --qs-up-soft: #fff0f1;
        --qs-down: #16815f;
        --qs-down-soft: #eaf8f1;
        --qs-warning: #b7791f;
        --qs-warning-soft: #fff8e8;
        --qs-shadow: 0 8px 24px rgba(15, 31, 53, 0.06);
        --qs-radius: 14px;
    }

    html { font-size: 16px; }
    .stApp {
        background: var(--qs-bg);
        color: var(--qs-text);
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
    }
    [data-testid="stAppViewContainer"] > .main {
        background: radial-gradient(circle at 92% 0%, rgba(22, 163, 165, 0.07), transparent 26rem), var(--qs-bg);
    }
    [data-testid="stMainBlockContainer"] {
        max-width: 1320px;
        padding: 2.1rem 2.2rem 3rem;
    }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbar"] { opacity: 0.62; }
    h1, h2, h3 { color: var(--qs-text); letter-spacing: -0.025em; }
    h1 {
        font-size: clamp(1.85rem, 2.7vw, 2.5rem) !important;
        line-height: 1.18 !important;
        margin-bottom: 0.35rem !important;
    }
    h2 { font-size: clamp(1.35rem, 2vw, 1.75rem) !important; }
    h3 { font-size: clamp(1.16rem, 1.6vw, 1.4rem) !important; }
    p, li, label { line-height: 1.65; }
    [data-testid="stCaptionContainer"] { color: var(--qs-muted); }
    hr { border-color: var(--qs-border) !important; margin: 1.55rem 0 !important; }

    /* 侧栏：高频任务优先、分组导航、足够大的点击区域。 */
    [data-testid="stSidebar"] {
        background: var(--qs-navy);
        border-right: 1px solid rgba(255, 255, 255, 0.08);
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.25rem; }
    [data-testid="stSidebar"] * { color: #dbe7f5; }
    [data-testid="stSidebar"] hr { border-color: rgba(255, 255, 255, 0.12) !important; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #91a4bb; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: inherit; }
    .sidebar-brand { padding: 0.25rem 0 0.9rem; }
    .sidebar-brand__eyebrow {
        color: #7dd3d4;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
    .sidebar-brand__title {
        color: #ffffff;
        font-size: 1.28rem;
        font-weight: 800;
        line-height: 1.35;
        margin-top: 0.35rem;
    }
    .sidebar-brand__meta { color: #91a4bb; font-size: 0.78rem; margin-top: 0.35rem; }
    .nav-section {
        color: #7890aa;
        font-size: 0.7rem;
        font-weight: 800;
        letter-spacing: 0.11em;
        margin: 1rem 0 0.35rem;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button {
        min-height: 42px;
        border: 1px solid transparent;
        border-radius: 10px;
        justify-content: flex-start;
        padding: 0.5rem 0.72rem;
        transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button[kind="secondary"] {
        background: transparent;
        color: #c9d7e7;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button[kind="secondary"]:hover {
        background: rgba(255, 255, 255, 0.07);
        border-color: rgba(255, 255, 255, 0.09);
        color: #ffffff;
        transform: translateX(2px);
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg, #158f92, #1cb3ad);
        border-color: rgba(255, 255, 255, 0.12);
        box-shadow: 0 8px 18px rgba(6, 148, 153, 0.22);
        color: #ffffff;
        font-weight: 750;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button:focus-visible,
    button:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 3px solid rgba(45, 212, 191, 0.45) !important;
        outline-offset: 2px;
    }

    /* 数据卡片：红涨绿跌以边框和柔和底色表达，避免大面积高饱和色。 */
    .metric-card {
        min-height: 118px;
        background: var(--qs-surface);
        border: 1px solid var(--qs-border);
        border-left: 4px solid var(--qs-accent);
        border-radius: var(--qs-radius);
        box-shadow: var(--qs-shadow);
        color: var(--qs-text);
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 0.25rem;
        padding: 1rem 1.1rem;
        margin: 0.25rem 0;
        text-align: left;
    }
    .metric-card.green {
        background: linear-gradient(145deg, var(--qs-surface) 45%, var(--qs-down-soft));
        border-left-color: var(--qs-down);
    }
    .metric-card.red {
        background: linear-gradient(145deg, var(--qs-surface) 45%, var(--qs-up-soft));
        border-left-color: var(--qs-up);
    }
    .metric-card.blue {
        background: linear-gradient(145deg, var(--qs-surface) 45%, #edf5ff);
        border-left-color: #3977c2;
    }
    .metric-card.warning {
        background: linear-gradient(145deg, var(--qs-surface) 45%, var(--qs-warning-soft));
        border-left-color: var(--qs-warning);
    }
    .metric-card.featured { min-height: 138px; }
    .big-number {
        color: var(--qs-text);
        font-size: clamp(1.55rem, 2.35vw, 2.1rem);
        font-weight: 800;
        line-height: 1.2;
        overflow-wrap: anywhere;
    }
    .big-number.compact { font-size: clamp(1.35rem, 2vw, 1.72rem); }
    .label { color: var(--qs-muted); font-size: 0.78rem; font-weight: 750; letter-spacing: 0.02em; }
    .card-detail { color: #415269; font-size: 0.88rem; }
    .risk-pill {
        border-radius: 999px;
        display: inline-block;
        font-size: 0.72rem;
        font-weight: 800;
        margin-left: 0.35rem;
        padding: 0.12rem 0.5rem;
    }
    .risk-low { background: var(--qs-down-soft); color: #0e6a4d; }
    .risk-medium { background: var(--qs-warning-soft); color: #956018; }
    .risk-high { background: var(--qs-up-soft); color: #a8323c; }
    .profit, .bull-badge { color: var(--qs-up); font-weight: 750; }
    .loss, .bear-badge { color: var(--qs-down); font-weight: 750; }

    [data-testid="stMetric"] {
        min-height: 118px;
        background: var(--qs-surface);
        border: 1px solid var(--qs-border);
        border-radius: var(--qs-radius);
        box-shadow: var(--qs-shadow);
        padding: 0.9rem 1rem;
    }
    [data-testid="stMetricLabel"] { color: var(--qs-muted); }
    [data-testid="stMetricValue"] {
        color: var(--qs-text);
        font-size: clamp(1.35rem, 2vw, 1.85rem);
        white-space: nowrap;
    }

    .stButton > button, .stDownloadButton > button {
        min-height: 44px;
        border-radius: 10px;
        font-weight: 700;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #158f92, #1cb3ad);
        border-color: #158f92;
    }
    [data-testid="stDataFrame"], [data-testid="stTable"],
    [data-testid="stPlotlyChart"], [data-testid="stVegaLiteChart"] {
        background: var(--qs-surface);
        border: 1px solid var(--qs-border);
        border-radius: var(--qs-radius);
        box-shadow: 0 4px 18px rgba(15, 31, 53, 0.04);
        overflow: hidden;
    }
    [data-testid="stExpander"] {
        background: var(--qs-surface);
        border: 1px solid var(--qs-border);
        border-radius: 12px;
    }
    [data-baseweb="tab-list"] {
        background: #eaf0f6;
        border-radius: 10px;
        gap: 0.2rem;
        padding: 0.25rem;
    }
    [data-baseweb="tab"] { border-radius: 8px; min-height: 42px; }
    [data-baseweb="tab"][aria-selected="true"] {
        background: var(--qs-surface);
        box-shadow: 0 2px 8px rgba(15, 31, 53, 0.08);
    }
    [data-testid="stAlert"], [data-testid="stNotification"] { border-radius: 12px; }

    @media (max-width: 900px) {
        [data-testid="stMainBlockContainer"] { padding: 1.2rem 1rem 2.5rem; }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.75rem; }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            flex: 1 1 min(100%, 280px) !important;
            width: auto !important;
        }
        .metric-card, [data-testid="stMetric"] { min-height: 104px; }
        [data-testid="stDataFrame"] { overflow-x: auto; }
    }
    @media (max-width: 600px) {
        html { font-size: 15px; }
        [data-testid="stMainBlockContainer"] { padding: 0.95rem 0.75rem 2rem; }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { flex-basis: 100% !important; }
        .big-number { font-size: 1.5rem; }
        [data-testid="stMetricValue"] { font-size: 1.35rem; }
        [data-baseweb="tab-list"] { overflow-x: auto; }
    }
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            scroll-behavior: auto !important;
            transition-duration: 0.01ms !important;
            animation-duration: 0.01ms !important;
        }
    }
</style>
""",
        unsafe_allow_html=True,
    )
