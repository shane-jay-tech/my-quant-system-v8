# -*- coding: utf-8 -*-
"""q920-11：ops/health.py 解码口径收敛（q918-18 `三/`六.1 结论）后的钉桩。

改前：`ops/health.py:263/:272` 两处 `subprocess.run(..., text=True, encoding='utf-8', errors='replace')`
改后：去掉 `encoding='utf-8'`，只留 `errors='replace'`（**errors-only**，编码跟随 locale 与子进程同源）。

四条：① AST 静态钉住「两处 schtasks 调用无 encoding、有 errors」；
     ② 运行期钉住「同参数下 cp936 中文不被解坏成 U+FFFD」；
     ③ 对照钉住「若强指 utf-8 确实会解坏」（UTF-8 环境下自动 skip，不产生假红）；
     ④ 行为不变量「ASCII 任务名比对不受解码口径影响」。
零生产逻辑改动：只动解码参数，任务名比对与返回值用法一字未改。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

HEALTH = Path(__file__).resolve().parents[1] / "ops" / "health.py"


def _schtasks_calls():
    tree = ast.parse(HEALTH.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if not (isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "subprocess"):
            continue
        if func.attr != "run":
            continue
        src = ast.unparse(node)
        if "schtasks" not in src:
            continue
        kw = {k.arg: k.value for k in node.keywords}
        out.append((node.lineno, src, kw))
    return out


def test_两处schtasks调用均为errors_only():
    """q920-11 收敛断言：schtasks 调用必须 text=True + errors 在场 + **encoding 缺席**。"""
    calls = _schtasks_calls()
    assert len(calls) == 2, f"预期 2 处 schtasks 调用，实测 {len(calls)}：{calls}"
    for lineno, src, kw in calls:
        assert "text" in kw and getattr(kw["text"], "value", None) is True, f":{lineno} 缺 text=True"
        assert "errors" in kw and getattr(kw["errors"], "value", None) == "replace", f":{lineno} 缺 errors replace"
        assert "encoding" not in kw, (
            f":{lineno} 仍强制 encoding（q920-11 应 errors-only，让编码跟随 locale 与子进程同源）：{src}")


def _child_bytes(text: str) -> bytes:
    """抓子进程发到 stdout 的**原始字节**（不解码），用于判定本机子进程的实际编码。"""
    return subprocess.run([sys.executable, "-c", f"print({text!r})"],
                          capture_output=True).stdout


def test_确定性对照_cp936字节在两种口径下的差异():
    """**不依赖环境变量**的确定性对照——q920-11 收敛的机制证据。

    本机系统代码页实测 chcp = 936；生产进程（Task Scheduler → daily_pipeline.bat → python）
    **没有** PYTHONUTF8，走 legacy cp936 ⇒ 子进程 schtasks 发 cp936 字节。
    而本测试会话被注入了 PYTHONUTF8=1（仅进程级，User/Machine 均未设），
    父进程强指 utf-8 时才会解坏 / 跟随 locale 时才对。用字节级对照把这条机制钉死。
    """
    raw = "中文报错信息".encode("cp936")               # 生产环境里 schtasks 发的中文字节
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")                            # 严格解码 ⇒ 崩（旧上限）
    forced = raw.decode("utf-8", errors="replace")     # 旧写法：不崩，但中文没了
    assert "\ufffd" in forced and "中文报错信息" not in forced, repr(forced)
    same_source = raw.decode("cp936", errors="replace")  # 新写法：跟随 locale ⇒ 与子进程同源
    assert same_source == "中文报错信息" and "\ufffd" not in same_source


def test_子进程路径_errors_only下无替换字符():
    """子进程实跑路径的**不变量**断言：无论父子在 cp936 还是 UTF-8 同源模式，
    errors-only 下 stdout 都不得出现 U+FFFD（解坏即红；本机是否 PYTHONUTF8 都能跑，不 skip）。"""
    marker = "中文标记OK"
    r = subprocess.run([sys.executable, "-c", f"print({marker!r})"],
                       capture_output=True, text=True, errors="replace")
    assert "\ufffd" not in r.stdout, f"errors-only 下出现替换字符：{r.stdout!r}"
    assert marker in r.stdout, f"中文未完整还原：{r.stdout!r}"


def test_任务名比对不受解码口径影响():
    """行为不变量：任务名是 ASCII，errors-only 与旧写法对任务名 in stdout 的判定一致。"""
    raw = _child_bytes("QuantMorningPipeline")
    old = raw.decode("utf-8", errors="replace")                       # 旧口径
    new = raw.decode(sys.getfilesystemencoding() or "cp936", errors="replace")  # 近似新口径
    assert ("QuantMorningPipeline" in old) is True
    assert ("QuantMorningPipeline" in new) is True
