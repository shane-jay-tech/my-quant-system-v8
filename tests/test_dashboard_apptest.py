"""仪表盘可用性冒烟：AppTest 全页渲染无异常（2026-08-24 round 11）。

只断言渲染成功与无异常，不断言渲染耗时（耗时证据由本会话手动实测记录，
避免 CI/机器差异导致 flaky）。
"""
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from streamlit.testing.v1 import AppTest


def test_dashboard_renders_without_exceptions():
    at = AppTest.from_file(str(BASE_DIR / 'app.py'), default_timeout=30)
    at.run(timeout=60)
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.title) >= 1


@pytest.mark.parametrize(
    ("page_id", "expected_title"),
    [
        ("picks", "今日选股"),
        ("market", "沪深300 市场状态"),
        ("simulation", "模拟交易"),
        ("trades", "我的交易"),
        ("backtest", "回测分析"),
        ("cost", "成本看板"),
        ("health", "系统健康检查"),
        ("pipeline", "流水线控制面板"),
    ],
)
def test_dashboard_all_pages_render_without_exceptions(page_id, expected_title):
    """直接设置稳定页面 ID；不点击任何会执行流水线或修改账户的按钮。"""
    at = AppTest.from_file(str(BASE_DIR / 'app.py'), default_timeout=30)
    at.session_state["nav_page"] = page_id
    at.run(timeout=60)

    assert not at.exception, [e.message for e in at.exception]
    assert any(expected_title in title.value for title in at.title)


def test_sidebar_navigation_uses_stable_page_ids():
    at = AppTest.from_file(str(BASE_DIR / 'app.py'), default_timeout=30)
    at.run(timeout=60)

    nav_button = next(button for button in at.button if button.key == "nav_market")
    nav_button.click().run(timeout=60)

    assert at.session_state["nav_page"] == "market"
    assert not at.exception, [e.message for e in at.exception]
    assert any("沪深300 市场状态" in title.value for title in at.title)


def test_full_pipeline_is_disabled_without_explicit_confirmation():
    """防止一次误点就联网执行并发送 Bark；测试本身不勾选、不执行。"""
    at = AppTest.from_file(str(BASE_DIR / 'app.py'), default_timeout=30)
    at.session_state["nav_page"] = "pipeline"
    at.run(timeout=60)

    full_run = next(
        button
        for button in at.button
        if button.label == "▶ 执行全流程（选股→回测→洞察→推送）"
    )
    assert full_run.disabled is True
