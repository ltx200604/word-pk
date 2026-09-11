@echo off
cd /d %~dp0
if not exist ".venv" (
  py -3 -m venv .venv 2>nul
  if not exist ".venv" python -m venv .venv
)
.venv\Scripts\python.exe -m pip install -r requirements.txt -q
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
pause
