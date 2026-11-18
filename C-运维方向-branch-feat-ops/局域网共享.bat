@echo off
chcp 65001 >nul
title 智能巡检机器人仿真系统 - 局域网共享模式
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.10 以上版本并勾选 "Add Python to PATH"。
  pause
  exit /b 1
)

python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo 首次运行：正在安装依赖，约一两分钟，请稍候...
  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

set "PYTHONPATH=%~dp0"
echo.
echo ===== 局域网共享模式 =====
echo 请把下面显示的 IPv4 地址发给同一 WiFi/校园网下的同学，
echo 对方在浏览器打开  http://该IP地址:8000  即可看到页面。
echo 例如: http://192.168.1.100:8000
echo 首次运行如 Windows 防火墙弹窗，请选择"允许访问"。
echo ==========================
echo.
ipconfig | findstr IPv4
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
pause
