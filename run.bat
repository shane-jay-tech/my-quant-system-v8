@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:: Kill old process on port 8502
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8502" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)
set "PYTHON=.venv\Scripts\python.exe"

echo ========================================
echo   Quant Trading System v8.6 - Launching...
echo ========================================
echo.
echo   Local: http://localhost:8502
echo   Close this window to stop
echo ========================================
echo.

start http://localhost:8502
"%PYTHON%" -m streamlit run app.py --server.headless true --server.port 8502 2>&1
pause
