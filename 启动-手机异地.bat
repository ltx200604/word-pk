@echo off
chcp 65001 >nul
title 单词PK - 本机服务 + 手机公网
cd /d %~dp0

set PY=D:\Xiaomi MiMo\resources\runtimes\win32-x64\python\python.exe
if not exist "%PY%" (
  if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)
if not exist "%PY%" set PY=python

if not exist "bin\cloudflared.exe" (
  echo [错误] 缺少 bin\cloudflared.exe，无法生成手机公网链接。
  pause
  exit /b 1
)

echo ============================================
echo  单词PK 启动中（本机电脑方案）
echo ============================================
echo.

echo [1/2] 检查/启动本地服务 127.0.0.1:8765 ...
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if errorlevel 1 (
  start "word-pk-server" /min cmd /c ""%PY%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8765"
  timeout /t 3 /nobreak >nul
) else (
  echo       本地服务已在运行
)

echo [2/2] 启动公网隧道（两人异地也能用）...
echo.
echo  【请保持本窗口不要关闭】
echo  关闭窗口 = 手机断线
echo.
echo  下面会出现一行 https://xxx.trycloudflare.com
echo  把这个网址发给对方，两人手机打开即可。
echo  电脑可以合盖睡眠吗？——不行，要保持开机（可最小化窗口）。
echo.
echo --------------------------------------------
bin\cloudflared.exe tunnel --url http://127.0.0.1:8765
echo.
echo 隧道已结束。
pause
