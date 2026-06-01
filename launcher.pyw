"""桌面应用启动器 - PyWebView 套壳 Streamlit。

启动流程：
  1. 单例锁 + 找空闲端口 + 启动 Streamlit 后台
  2. 创建窗口显示 splash（绿金渐变 + 转圈）
  3. 后台线程：Python 端轮询 /_stcore/health（不走浏览器，避开 CORS）
  4. health=200 -> window.load_url 切到主界面
  5. 关窗口 -> 优雅终止 Streamlit

注意：曾尝试用 GET / 做"预热"，但 streamlit 主页 GET / 只返 5KB SPA 壳，
不会触发后端 home 真实渲染（那要等 webview 建 WebSocket）。所以预热无效，删了。

开发模式仍然可用：run.bat（直接浏览器 :8502，热重载）。
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

import webview


HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
ICON = str(ASSETS / "app.ico")
LOG_FILE = HERE / "data" / "launcher.log"
SINGLETON_LOCK_PORT = 49285
STARTUP_TIMEOUT_SEC = 90


# ---------- 日志 ----------
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("launcher")


# ---------- 单例 ----------
_lock_socket = None


def acquire_singleton_lock() -> bool:
    global _lock_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind(("127.0.0.1", SINGLETON_LOCK_PORT))
        s.listen(1)
        _lock_socket = s
        return True
    except OSError:
        s.close()
        return False


# ---------- 端口 ----------
def find_free_port(preferred: int = 8521, max_tries: int = 20) -> int:
    for offset in range(max_tries):
        p = preferred + offset
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"找不到空闲端口（{preferred}-{preferred + max_tries}）")


# ---------- Streamlit 子进程 ----------
def start_streamlit_backend(port: int) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(HERE / "app.py"),
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--server.fileWatcherType", "none",
    ]
    logger.info("Starting streamlit: %s", " ".join(cmd))
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        cmd,
        cwd=str(HERE),
        stdout=open(str(LOG_FILE.parent / "streamlit.log"), "ab"),
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )


# ---------- 健康检查（Python 端 - 不受浏览器跨域限制）----------
def is_health_ready(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/_stcore/health", timeout=timeout
        ) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


# ---------- splash HTML ----------
def splash_html() -> str:
    # 注意：纯静态。所有进度文本由 Python 通过 evaluate_js 更新。
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>量化选股系统</title>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%;
    font-family: -apple-system, "Segoe UI", "PingFang SC",
                 "Microsoft YaHei", sans-serif;
    background: linear-gradient(135deg, #10B981 0%, #F59E0B 100%);
    color: white; overflow: hidden;
    user-select: none;
  }
  .center {
    height: 100%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 28px;
  }
  .logo {
    font-size: 84px; font-weight: 700; line-height: 1;
    background: rgba(255,255,255,0.18); border-radius: 28px;
    width: 144px; height: 144px;
    display: flex; align-items: center; justify-content: center;
    backdrop-filter: blur(8px);
    box-shadow: 0 20px 50px rgba(0,0,0,0.25);
  }
  h1 { margin: 0; font-size: 32px; font-weight: 600; }
  p#status { margin: 0; font-size: 15px; opacity: 0.9; min-height: 22px; }
  .spinner {
    width: 40px; height: 40px; border: 3px solid rgba(255,255,255,0.25);
    border-top-color: white; border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hint { position: absolute; bottom: 24px; font-size: 12px; opacity: 0.7; }
</style>
</head>
<body>
<div class="center">
  <div class="logo">📈</div>
  <h1>量化选股系统</h1>
  <div class="spinner"></div>
  <p id="status">正在启动后端…</p>
</div>
<div class="hint">© 2026 · A 股选股 · 回测 · 模拟交易 · 反馈闭环</div>
</body>
</html>
"""


# ---------- 错误对话框 ----------
def show_error_box(title: str, message: str) -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
        except Exception:
            pass
    print(f"[{title}] {message}", file=sys.stderr)


def _set_splash_status(window, text: str) -> None:
    """安全地更新 splash 文字（webview 可能已经切走，evaluate_js 会抛错）。"""
    try:
        import json as _json
        window.evaluate_js(
            f"var s=document.getElementById('status');"
            f"if(s) s.textContent={_json.dumps(text)};"
        )
    except Exception:
        pass


# ---------- 主流程 ----------
def main() -> int:
    if not acquire_singleton_lock():
        logger.info("Another instance is running; exit.")
        return 0

    # 用 8521 起步,跟心理(8501)/学习(8511)/dev run.bat(8502) 全部错开
    try:
        port = find_free_port(preferred=8521)
    except Exception as e:
        logger.exception("Port scan failed")
        show_error_box("启动失败", f"找不到空闲端口：{e}\n\n详细日志：{LOG_FILE}")
        return 1

    try:
        proc = start_streamlit_backend(port)
    except Exception as e:
        logger.exception("Streamlit start failed")
        show_error_box("启动失败",
                       f"无法启动 Streamlit：{e}\n\n请确保依赖完整安装：\n"
                       f"  pip install -r requirements.txt\n\n日志：{LOG_FILE}")
        return 1

    target_url = f"http://127.0.0.1:{port}"
    logger.info("Streamlit backend launching at %s (pid=%s)", target_url, proc.pid)

    window = webview.create_window(
        "量化选股系统",
        html=splash_html(),
        width=1440,
        height=900,
        min_size=(1000, 680),
        background_color="#10B981",
        easy_drag=False,
        confirm_close=False,
    )

    def on_closed():
        logger.info("Window closed; terminating streamlit.")
        try:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            logger.exception("Failed to terminate streamlit cleanly")

    window.events.closed += on_closed

    # 后台线程:health 200 -> 切 URL
    def wait_and_switch():
        deadline = time.time() + STARTUP_TIMEOUT_SEC
        t0 = time.perf_counter()
        progress_hints = [
            (3.0, "正在启动数据看板服务…"),
            (8.0, "首次启动稍慢（载入 Python 环境），请再等几秒…"),
            (20.0, "仍在装载：可能是安全软件拖慢了 Python，马上就好…"),
        ]
        next_hint = 0
        while time.time() < deadline:
            if proc.poll() is not None:
                logger.error("Streamlit exited prematurely (rc=%s)", proc.returncode)
                show_error_box("启动失败",
                               f"Streamlit 进程意外退出(exit code {proc.returncode})。\n"
                               f"详细日志:{LOG_FILE.parent / 'streamlit.log'}")
                window.destroy()
                return
            if is_health_ready(port):
                elapsed = time.perf_counter() - t0
                logger.info("Streamlit ready in %.2fs; switching to %s", elapsed, target_url)
                _set_splash_status(window, "就绪，正在打开…")
                time.sleep(0.15)
                try:
                    window.load_url(target_url)
                except Exception:
                    logger.exception("load_url failed")
                return
            elapsed = time.perf_counter() - t0
            if next_hint < len(progress_hints) and elapsed >= progress_hints[next_hint][0]:
                _set_splash_status(window, progress_hints[next_hint][1])
                next_hint += 1
            time.sleep(0.2)

        logger.error("Startup timeout")
        show_error_box("启动超时", f"Streamlit 后端启动超过 {STARTUP_TIMEOUT_SEC} 秒。\n日志:{LOG_FILE}")
        window.destroy()

    def on_window_ready():
        threading.Thread(target=wait_and_switch, daemon=True).start()

    try:
        webview.start(
            on_window_ready,
            icon=ICON if os.path.exists(ICON) else None,
            private_mode=True,  # 每次新 profile,不串心理/学习两系统的缓存
        )
    except Exception:
        logger.exception("webview.start failed")
        show_error_box("启动失败",
                       f"GUI 初始化失败。请确保已装 WebView2（Win10/11 一般预装）。\n"
                       f"日志：{LOG_FILE}")
        on_closed()
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception("Unhandled exception in launcher")
        show_error_box("严重错误",
                       f"未预料的错误：{e}\n\n详细堆栈：\n{traceback.format_exc()}\n\n"
                       f"日志：{LOG_FILE}")
        sys.exit(1)
