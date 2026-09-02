@echo off
REM v8.7 修复：不再写死目录；日志改追加（旧版每次覆盖）
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8502 >> logs\streamlit.log 2>&1
