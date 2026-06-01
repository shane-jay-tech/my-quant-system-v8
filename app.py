import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from core.config import SYSTEM_VERSION
from app.styles import inject_global_css
from app.sidebar import render_sidebar
from app.pages import (
    render_picks_page, render_backtest_page, render_market_status_page,
    render_pipeline_control_page, render_sim_trading_page, render_cost_dashboard_page,
    render_my_trades_page, render_system_health_page,
)

st.set_page_config(
    page_title=f"量化选股系统 v{SYSTEM_VERSION}",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",
)

inject_global_css()
page_id = render_sidebar()

# 路由使用稳定 ID，避免只改显示文案就让页面失效。
PAGE_RENDERERS = {
    "picks": render_picks_page,
    "market": render_market_status_page,
    "simulation": render_sim_trading_page,
    "trades": render_my_trades_page,
    "backtest": render_backtest_page,
    "cost": render_cost_dashboard_page,
    "health": render_system_health_page,
    "pipeline": render_pipeline_control_page,
}
PAGE_RENDERERS.get(page_id, render_picks_page)()

st.divider()
st.caption(f"量化选股系统 v{SYSTEM_VERSION} | 数据仅供参考，不构成投资建议")
