import os
import sys
from datetime import datetime
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
try:
    from core.config import SYSTEM_VERSION
except Exception:
    SYSTEM_VERSION = "8.5"


NAV_GROUPS = (
    ("每日决策", (
        ("picks", "🎯 今日选股"),
        ("market", "📉 市场状态"),
        ("simulation", "💰 模拟交易"),
        ("trades", "📝 我的交易"),
    )),
    ("分析复盘", (
        ("backtest", "📊 回测分析"),
        ("cost", "💸 成本看板"),
    )),
    ("系统管理", (
        ("health", "🩺 系统健康"),
        ("pipeline", "⚙️ 流水线控制"),
    )),
)

VALID_PAGE_IDS = {
    page_id
    for _, pages in NAV_GROUPS
    for page_id, _ in pages
}


def _select_page(page_id):
    """导航只写 session state，不触碰业务文件。"""
    st.session_state["nav_page"] = page_id


def render_sidebar():
    with st.sidebar:
        st.markdown(
            f"""
            <div class="sidebar-brand">
                <div class="sidebar-brand__eyebrow">Quant Workspace · v{SYSTEM_VERSION}</div>
                <div class="sidebar-brand__title">量化决策工作台</div>
                <div class="sidebar-brand__meta">MA(5,30) · 大盘择时 · 动量排序</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        current_page = st.session_state.get("nav_page", "picks")
        if current_page not in VALID_PAGE_IDS:
            current_page = "picks"
            st.session_state["nav_page"] = current_page

        for group_label, pages in NAV_GROUPS:
            st.markdown(f'<div class="nav-section">{group_label}</div>', unsafe_allow_html=True)
            for page_id, label in pages:
                st.button(
                    label,
                    key=f"nav_{page_id}",
                    type="primary" if current_page == page_id else "secondary",
                    width="stretch",
                    on_click=_select_page,
                    args=(page_id,),
                )

        st.divider()

        # 新手模式切换（状态持久化：从 .newbie_mode 文件恢复，
        # 修复旧版重启 app 后开关复位并悄悄删掉模式标记的问题）
        mode_file = os.path.join(BASE_DIR, '.newbie_mode')
        existed_before = os.path.exists(mode_file)
        newbie_mode = st.toggle("🆕 新手模式", value=existed_before,
                               help="开启后：推送使用简单模式，不显示复杂术语，增加操作指引。状态会保存，重启后依然生效。")
        if newbie_mode:
            if not existed_before:
                with open(mode_file, 'w', encoding='utf-8') as f:
                    f.write('1')
                st.success("新手模式已开启 — 推送和订单将使用简化说明")
        else:
            if existed_before:
                os.remove(mode_file)

        st.divider()
        st.caption(f"🕐 数据更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        st.caption("本地数据 · 自动进化 · 行为追踪")

        st.divider()
        if st.button("♻️ 重载数据", width="stretch",
                     help="清除页面缓存并重新读取本地数据文件（不会重新联网抓取；联网抓取请到「⚙ 流水线控制」页运行）"):
            st.cache_data.clear()
            st.rerun()

    return st.session_state.get("nav_page", "picks")
