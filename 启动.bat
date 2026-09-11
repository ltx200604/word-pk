@echo off
chcp 65001 >nul
title 单词PK - 仅本机
cd /d %~dp0

set PY=D:\Xiaomi MiMo\resources\runtimes\win32-x64\python\python.exe
if not exist "%PY%" (
  if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)
if not exist "%PY%" set PY=python

if not exist ".venv\Scripts\python.exe" (
  echo 创建虚拟环境...
  "%PY%" -m venv .venv
  set PY=.venv\Scripts\python.exe
  "%PY%" -m pip install -r requirements.txt -q
)

echo 启动本机服务 http://127.0.0.1:8765
echo （仅电脑浏览器试玩；手机异地请用「启动-手机异地.bat」）
start "" http://127.0.0.1:8765
"%PY%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
pause
