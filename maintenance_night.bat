@echo off
REM Nightly maintenance: stall watchdog + state backup (when available).
REM ASCII-only + CRLF: scheduled tasks fail with 9009 on UTF-8/LF bat files.
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "BASE=%~dp0"
if not exist "%BASE%logs" mkdir "%BASE%logs"
set "MLOG=%BASE%logs\maintenance_night.log"

echo === MAINT START [%date% %time%] === >> "%MLOG%"
cd /d "%BASE%"
"%PYTHON%" "%BASE%stall_watchdog.py" >> "%MLOG%" 2>&1
if %errorlevel% neq 0 echo [WARN] stall_watchdog.py rc=%errorlevel% >> "%MLOG%"

if exist "%BASE%backup_state.py" (
    "%PYTHON%" "%BASE%backup_state.py" >> "%MLOG%" 2>&1
    if %errorlevel% neq 0 echo [WARN] backup_state.py rc=%errorlevel% >> "%MLOG%"
) else (
    echo [INFO] backup_state.py not present, skip >> "%MLOG%"
)
echo === MAINT END [%date% %time%] === >> "%MLOG%"
endlocal & exit /b 0
