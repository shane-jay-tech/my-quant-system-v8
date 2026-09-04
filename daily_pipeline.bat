@echo off
REM Quant daily pipeline v8 (DAG registry driven, steps in core/pipeline.py)
REM ASCII-only + CRLF: scheduled tasks fail with 9009 on UTF-8/LF bat files.
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "BASE=%~dp0"
if not exist "%BASE%logs" mkdir "%BASE%logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set "LOGFILE=%BASE%logs\pipeline_%TODAY%.log"

echo === RUN START [%date% %time%] === >> "%LOGFILE%"
cd /d "%BASE%"
"%PYTHON%" -u "%BASE%daily_pipeline.py" >> "%LOGFILE%" 2>&1
endlocal & exit /b %errorlevel%
