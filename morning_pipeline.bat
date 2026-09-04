@echo off
REM Morning (premarket) pipeline: trading-day check, premarket sim, push report.
REM ASCII-only + CRLF: scheduled tasks fail with 9009 on UTF-8/LF bat files.
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "BASE=%~dp0"
if not exist "%BASE%logs" mkdir "%BASE%logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set "LOGFILE=%BASE%logs\morning_%TODAY%.log"

echo === RUN START [%date% %time%] === >> "%LOGFILE%"
cd /d "%BASE%"

echo [1/3] Trading day check >> "%LOGFILE%" 2>&1
"%PYTHON%" check_trading_day.py >> "%LOGFILE%" 2>&1
if %errorlevel% neq 0 (
    echo [SKIP] Non-trading day, skip morning pipeline >> "%LOGFILE%"
    endlocal & exit /b 0
)

echo [2/3] Premarket sim >> "%LOGFILE%" 2>&1
"%PYTHON%" premarket_sim.py >> "%LOGFILE%" 2>&1
set PRERC=%errorlevel%
if %PRERC% neq 0 echo [WARN] premarket_sim.py failed rc=%PRERC%, try push existing report >> "%LOGFILE%"

echo [3/3] Push premarket report >> "%LOGFILE%" 2>&1
if exist "%BASE%results\premarket_%TODAY%.md" (
    "%PYTHON%" send_to_bark.py --file "%BASE%results\premarket_%TODAY%.md" --no-digest >> "%LOGFILE%" 2>&1
) else (
    echo [ERROR] results\premarket_%TODAY%.md not found, no push >> "%LOGFILE%"
)

echo === RUN END [%date% %time%] rc=%PRERC% === >> "%LOGFILE%"
endlocal & exit /b %PRERC%
