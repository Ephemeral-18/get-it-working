@echo off
chcp 65001 >nul
title 智能巡检机器人仿真系统 - http://127.0.0.1:8000
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.10 以上版本，安装时勾选 "Add Python to PATH"。
  echo 下载地址: https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo 首次运行：正在安装依赖，约一两分钟，请稍候...
  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

set "PYTHONPATH=%~dp0"
echo 正在启动服务，浏览器将自动打开 http://127.0.0.1:8000 （关闭本窗口即停止服务）
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
pause
