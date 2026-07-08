@echo off
chcp 65001 >nul 2>&1
title 智能家居管理系统

echo ==================================================
echo   智能家居管理系统 Smart Home System
echo ==================================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先运行:
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

echo 正在启动系统...
echo 访问地址: http://localhost:5000
echo 按 Ctrl+C 停止
echo.

venv\Scripts\python.exe app.py

pause
