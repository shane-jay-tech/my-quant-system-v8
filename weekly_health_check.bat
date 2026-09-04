@echo off
REM Weekly health check: self check + auto heal + push latest report.
REM ASCII-only + CRLF: scheduled tasks fail with 9009 on UTF-8/LF bat files.
setlocal enabledelayedexpansion
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "BASE=%~dp0"
if not exist "%BASE%logs" mkdir "%BASE%logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set "LOGFILE=%BASE%logs\weekly_health_%TODAY%.log"

echo [%date% %time%] === Weekly Health Check Start === >> "%LOGFILE%" 2>&1
cd /d "%BASE%"

echo [1] Running self check >> "%LOGFILE%" 2>&1
"%PYTHON%" _self_check.py >> "%LOGFILE%" 2>&1
if %errorlevel% neq 0 echo [WARN] _self_check.py exited with code %errorlevel% >> "%LOGFILE%"

echo [2] Running auto-heal >> "%LOGFILE%" 2>&1
"%PYTHON%" auto_heal.py >> "%LOGFILE%" 2>&1
if %errorlevel% neq 0 echo [WARN] auto_heal.py had unresolved issues >> "%LOGFILE%"

echo [3] Finding latest health report >> "%LOGFILE%" 2>&1
set "LATEST="
for /f "delims=" %%f in ('dir /b /od "%BASE%reports\health_check_*.md" 2^>nul') do set "LATEST=%%f"

if not "!LATEST!"=="" (
    echo [4] Pushing health report: !LATEST! >> "%LOGFILE%" 2>&1
    "%PYTHON%" send_to_bark.py --file "%BASE%reports\!LATEST!" --no-digest >> "%LOGFILE%" 2>&1
    if !errorlevel! neq 0 echo [ERROR] push failed >> "%LOGFILE%"
)

echo [%date% %time%] === Weekly Health Check End === >> "%LOGFILE%" 2>&1
endlocal & exit /b 0
