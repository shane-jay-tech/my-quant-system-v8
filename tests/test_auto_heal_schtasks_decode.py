# -*- coding: utf-8 -*-
"""auto_heal 三处 subprocess 的解码防御锁定用例（q918-18，镜像 cb62427 的 health 修法）。

病灶：`text=True` 而不给 `errors` ⇒ 严格解码；GBK 输出在 UTF-8 模式下抛 UnicodeDecodeError，
而 auto_heal 是自愈链——读线程崩＝自愈失效。
零真实子进程：`subprocess.run` 全程 monkeypatch，只验"调用参数"与"用这组参数能否解真字节"。
"""
import locale
import sys
from pathlib import Path

import pytest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_heal  # noqa: E402


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture()
def spy(monkeypatch):
    """记录每次 subprocess.run 的 kwargs；os.path.exists 一律 True（不碰真实盘）。"""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return _FakeCompleted(stdout="")            # query 里 "task_name in stdout" 为假 ⇒ 继续走 create 分支

    monkeypatch.setattr(auto_heal.subprocess, "run", fake_run)
    monkeypatch.setattr(auto_heal.os.path, "exists", lambda p: True)
    return calls


def test_all_three_subprocess_sites_pin_errors_replace(spy, tmp_path):
    """三个调用点（子进程脚本 / schtasks query / schtasks create）都必须带 errors='replace'。"""
    auto_heal.run_script("some_script.py")
    auto_heal.fix_scheduled_task("QuantMorningPipeline", str(tmp_path / "run.bat"), "desc")

    assert len(spy) == 3, f"应命中三处 subprocess.run，实得 {len(spy)}"
    for kw in spy:
        assert kw.get("errors") == "replace", f"缺 errors='replace'：{kw}"
        assert kw.get("text") is True


def test_spy_records_timeout_on_every_site(spy, tmp_path):
    """超时守卫不能被解码改动带掉（自愈链卡死比乱码更糟）。"""
    auto_heal.run_script("some_script.py")
    auto_heal.fix_scheduled_task("QuantDaily", str(tmp_path / "run.bat"), "desc")

    assert all(isinstance(kw.get("timeout"), int) for kw in spy), spy


def test_recorded_kwargs_decode_real_cp936_bytes_without_mangling(spy, tmp_path):
    """用**记录到的那组参数**解真实 cp936 字节：不抛，且中文逐字还原。

    这一条同时解释"为什么不照抄 encoding='utf-8'"：同样的字节用 utf-8+replace 会变成 U+FFFD，
    中文日志（heal_log 是人唯一看得懂的那份）就废了。
    """
    auto_heal.run_script("some_script.py")
    kw = spy[0]
    assert kw.get("errors") == "replace", "防御被摘掉，后面的解码对比就没有意义了"
    gbk_bytes = "中文标记OK".encode("gbk")

    # subprocess text=True 的真实语义：encoding=None ⇒ locale 首选编码（bytes.decode 本身不收 None）。
    # 本修复锁的契约是「不抛」＋errors=replace（读线程崩＝自愈失效）；逐字还原则取决于机器
    # locale：中文 ANSI（cp936）下完整还原；PYTHONUTF8=1 时 preferred=utf-8，gbk 字节会被
    # replace 成 U+FFFD（乱码但不崩，与生产行为同源）——两种模式都必须绿，故按编码分档断言。
    enc = kw.get("encoding") or locale.getpreferredencoding(False)
    decoded = gbk_bytes.decode(enc, kw.get("errors") or "strict")   # 契约核心：不抛
    assert "OK" in decoded                                          # ASCII 在任何 sane 编码下存活
    if enc.replace("-", "").lower() in ("cp936", "gbk", "gb2312"):
        assert "中文标记OK" in decoded                               # 与子进程同源时中文逐字还原
    with pytest.raises(UnicodeDecodeError):
        gbk_bytes.decode("utf-8")                                     # 病灶：严格 UTF-8 必炸
    assert "中文" not in gbk_bytes.decode("utf-8", "replace")           # 反证：utf-8+replace 把中文换没了


def test_create_failure_logs_stderr_and_does_not_raise(spy, tmp_path, monkeypatch):
    """schtasks create 失败路径：中文 stderr（GBK）经解码后进日志，不抛异常。"""
    def fake_run(*args, **kwargs):
        kwargs.setdefault("encoding", None)
        return _FakeCompleted(stdout="", stderr="无法访问此系统。\r\n", returncode=1)

    monkeypatch.setattr(auto_heal.subprocess, "run", fake_run)
    auto_heal.HEAL_LOG.clear()

    assert auto_heal.fix_scheduled_task("QuantDaily", str(tmp_path / "run.bat"), "d") is False
    assert any("schtasks create failed" in e for e in auto_heal.HEAL_LOG)
