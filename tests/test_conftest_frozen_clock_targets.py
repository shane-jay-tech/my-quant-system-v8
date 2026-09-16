"""FROZEN_CLOCK_TARGETS 键位可解析性哨兵（916p-a1-008）。

防的事故（conftest.py:45-50 注释原文）：「给时敏测试加了 frozen_clock，但漏登记
本表 → fixture 静默不 patch 任何东西，测试用冻结日期拼文件名、被测代码仍取真实
日期 → 跨日必挂」（2026-09-15 bark 两失败根因，修复记录
docs/insights/quant-bark-2fail-20260916.md）。本哨兵用夹具本体验证登记表三契约：
键可导入／属性存在／冻结真实生效——漏登记或写错名会在收集期红，而非跨日才炸。
不 patch 全局 datetime；不改 conftest。
可复跑：python -m pytest tests/test_conftest_frozen_clock_targets.py -q
"""
import datetime
import importlib.util
from pathlib import Path

import pytest

# conftest 不能以普通模块名导入（pytest 特殊加载），按路径载入取登记表
_spec = importlib.util.spec_from_file_location(
    "_quant_conftest", Path(__file__).resolve().parent / "conftest.py"
)
_conf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_conf)
FROZEN_CLOCK_TARGETS = _conf.FROZEN_CLOCK_TARGETS

FIXED = "2026-09-13 23:59:59"
FIXED_DT = datetime.datetime(2026, 9, 13, 23, 59, 59)


@pytest.mark.parametrize("mod_name", sorted(FROZEN_CLOCK_TARGETS))
def test_registry_key_importable(mod_name):
    """①登记表每个键必须可 importlib.import_module。"""
    importlib.import_module(mod_name)


@pytest.mark.parametrize("mod_name", sorted(FROZEN_CLOCK_TARGETS))
@pytest.mark.parametrize("attr", ["datetime", "date"])
def test_registry_attr_exists(mod_name, attr):
    """②登记的每个属性名必须在模块上存在（hasattr）。"""
    names = FROZEN_CLOCK_TARGETS[mod_name]
    if attr not in names:
        pytest.skip(f"{mod_name} 未登记 {attr}")
    assert hasattr(importlib.import_module(mod_name), attr)


@pytest.mark.parametrize("mod_name", sorted(FROZEN_CLOCK_TARGETS))
def test_freeze_datetime_takes_effect(mod_name, frozen_clock):
    """③每键冻结真实生效：模块内 datetime.now() 返回固定日。"""
    if "datetime" not in FROZEN_CLOCK_TARGETS[mod_name]:
        pytest.skip(f"{mod_name} 未登记 datetime")
    frozen_clock(FIXED)
    assert importlib.import_module(mod_name).datetime.now() == FIXED_DT


def test_position_sizer_date_today_frozen(frozen_clock):
    """③补：position_sizer 登记的 date.today() 同样被冻结。"""
    frozen_clock(FIXED)
    import position_sizer

    assert position_sizer.date.today() == FIXED_DT.date()


def test_unregistered_module_not_patched(frozen_clock):
    """④未登记模块不受影响：trade_analyzer 的 datetime 未在登记表，
    frozen_clock 后仍走真实时间（now 与冻结日不同且持续前进）。"""
    import trade_analyzer

    frozen_clock(FIXED)
    real_now = trade_analyzer.datetime.now()
    assert real_now != FIXED_DT
    assert (real_now - datetime.datetime.now()).total_seconds() < 5


def test_second_freeze_overrides_first(frozen_clock):
    """⑤固定日可被第二次调用覆盖（工厂多次 _freeze 语义）。"""
    frozen_clock("2026-01-01 00:00:01")
    frozen_clock(FIXED)
    import newbie_protection

    assert newbie_protection.datetime.now() == FIXED_DT
