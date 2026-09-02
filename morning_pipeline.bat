@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM v8.7 修复：旧版 [2]/[3] 都是 --dry-run，盘前流水线等于空转；
REM 现在真正运行 premarket_sim.py 并把生成的盘前报告真实推送。
set PYTHON=%~dp0.venv\Scripts\python.exe
set BASE=%~dp0
if not exist "%BASE%\logs" mkdir "%BASE%\logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set LOGFILE=%BASE%\logs\morning_%TODAY%.log

call :main >> "%LOGFILE%" 2>&1
exit /b %errorlevel%

:main
echo === RUN START [%date% %time%] ===
echo ==============================================
echo  量化选股系统 - 盘前流水线
echo  %date% %time%
echo ==============================================
cd /d "%BASE%"

echo [1/3] 交易日检测...
%PYTHON% check_trading_day.py
if %errorlevel% neq 0 (
    echo [SKIP] 非交易日，跳过盘前流水线
    exit /b 0
)

echo [2/3] 盘前情绪评分与仓位建议...
%PYTHON% premarket_sim.py
set PRERC=%errorlevel%
if %PRERC% neq 0 (
    echo [WARN] premarket_sim.py 失败，退出码 %PRERC%，继续尝试推送既有报告
)

echo [3/3] 推送盘前报告...
if exist "%BASE%\results\premarket_%TODAY%.md" (
    %PYTHON% send_to_bark.py --file "%BASE%\results\premarket_%TODAY%.md" --no-digest
    set PUSHRC=%errorlevel%
) else (
    echo [ERROR] 未找到 results\premarket_%TODAY%.md，不推送
    set PUSHRC=1
)

if %PRERC% neq 0 exit /b %PRERC%
if "%PUSHRC%" neq "0" exit /b %PUSHRC%
echo ==============================================
echo  盘前流水线完成
echo ==============================================
exit /b 0
