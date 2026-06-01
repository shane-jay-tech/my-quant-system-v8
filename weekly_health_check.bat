@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "BASE=D:\code\my-quant-system-v8"
set "PYTHON=%~dp0.venv\Scripts\python.exe"

echo [%date% %time%] === Weekly Health Check Start ===

cd /d "%BASE%"

echo [1] Running self check...
%PYTHON% _self_check.py
if %errorlevel% neq 0 (
    echo [WARN] _self_check.py exited with code %errorlevel%
)

echo [2] Running auto-heal...
%PYTHON% auto_heal.py
if %errorlevel% neq 0 (
    echo [WARN] auto_heal.py had unresolved issues
)

echo [3] Finding latest health report...
for /f "delims=" %%f in ('dir /b /od "%BASE%\reports\health_check_*.md" 2^>nul') do set "LATEST=%%f"

if "!LATEST!"=="" (
    echo [ERROR] No health report found in reports\
    exit /b 1
)

echo [4] Pushing health report: !LATEST!
%PYTHON% send_to_bark.py --file "reports\!LATEST!"
if %errorlevel% neq 0 (
    echo [WARN] Bark push failed
)

echo [%date% %time%] === Weekly Health Check End ===
