@echo off
cd /d D:\code\my-quant-system-v8
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8502 > logs\streamlit.log 2>&1
