@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM v8.7 修复：去掉硬编码路径；输出统一追加到 logs/weekly_health_YYYYMMDD.log
set "BASE=%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BASE%logs" mkdir "%BASE%logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set LOGFILE=%BASE%logs\weekly_health_%TODAY%.log

call :main >> "%LOGFILE%" 2>&1
exit /b %errorlevel%

:main
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
for /f "delims=" %%f in ('dir /b /od "%BASE%reports\health_check_*.md" 2^>nul') do set "LATEST=%%f"

if "!LATEST!"=="" (
    echo [ERROR] No health report found in reports\
    exit /b 1
)

echo [4] Pushing health report: !LATEST!
%PYTHON% send_to_bark.py --file "%BASE%reports\!LATEST!" --no-digest
if %errorlevel% neq 0 (
    echo [ERROR] push failed
    exit /b 1
)

echo [%date% %time%] === Weekly Health Check End ===
exit /b 0
