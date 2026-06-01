@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set PYTHON=%~dp0.venv\Scripts\python.exe
set BASE=%~dp0
if not exist "%BASE%\logs" mkdir "%BASE%\logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%I
set LOGFILE=%BASE%\logs\morning_%TODAY%.log

call :main > "%LOGFILE%" 2>&1
exit /b %errorlevel%

:main
echo ==============================================
echo  量化选股系统 v8.6 - 盘前流水线
echo  %date% %time%
echo ==============================================
cd /d "%BASE%"

echo [1/3] 交易日检测...
%PYTHON% check_trading_day.py
if %errorlevel% neq 0 (
    echo [SKIP] 非交易日，跳过盘前流水线
    exit /b 0
)

echo [2/3] 盘前检查...
%PYTHON% %BASE%\core\pipeline.py --dry-run 2>nul | find "运行:" >nul
echo 盘前准备就绪

echo [3/3] 推送盘前通知...
%PYTHON% send_to_bark.py --simple --dry-run
echo 盘前检查完成

echo ==============================================
echo  盘前流水线完成
echo ==============================================
exit /b 0
