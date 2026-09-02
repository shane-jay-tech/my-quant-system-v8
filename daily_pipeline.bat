@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ========================================
REM  Quant daily pipeline v8 (DAG registry driven)
REM  Steps defined in core/pipeline.py PIPELINE_STEPS
REM  (ASCII-only to avoid codepage mojibake in logs)
REM ========================================
set PYTHON=%~dp0.venv\Scripts\python.exe
REM v8.7 修复：不再写死 D:\code\my-quant-system-v8，换目录/机器可运行
set BASE=%~dp0
if not exist "%BASE%logs" mkdir "%BASE%logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set LOGFILE=%BASE%logs\pipeline_%TODAY%.log

call :main >> "%LOGFILE%" 2>&1
exit /b %errorlevel%

:main
REM Append-only log: 每次运行都留痕，手动重跑不会覆盖定时运行记录。
echo === RUN START [%date% %time%] ===
echo ==============================================
echo  Quant System daily pipeline (DAG registry)
echo  %date% %time%
echo  Tier: QUANT_TIER env or data\system_config.json
echo ==============================================

cd /d "%BASE%"
%PYTHON% -u "%BASE%daily_pipeline.py"
exit /b %errorlevel%
