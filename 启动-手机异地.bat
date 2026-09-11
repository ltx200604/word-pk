@echo off
chcp 65001 >nul
cd /d %~dp0

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" (
  where py >nul 2>nul && set "PY=py -3"
)
if "%PY%"=="" set PY=python

if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  set PY=.venv\Scripts\python.exe
)

"%PY%" -m pip install -r requirements.txt -q

echo [1/2] Starting local server on port 8765...
start "word-pk-server" /min cmd /c ""%PY%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8765"

timeout /t 2 /nobreak >nul

echo [2/2] Starting public tunnel (works without same WiFi)...
echo.
echo Keep this window open. Copy the https://xxx.trycloudflare.com link to your friend.
echo Both phones open that link. No same WiFi needed.
echo.

if exist "bin\cloudflared.exe" (
  bin\cloudflared.exe tunnel --url http://127.0.0.1:8765
) else (
  echo cloudflared not found. Local-only mode: http://127.0.0.1:8765
  echo Same WiFi phones: http://YOUR_PC_LAN_IP:8765
  pause
)
