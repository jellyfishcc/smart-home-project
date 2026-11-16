@echo off
setlocal
cd /d "%~dp0"

rem NOTE: keep this file ASCII-only. Non-ASCII batch files break cmd parsing
rem (cmd reads the file using the active code page) and show as mojibake in
rem editors that assume UTF-8. All Chinese messages are printed by the Python
rem launcher instead: scripts\launch_win_camera.py

rem Windows has no /dev/videoN: use a numeric camera index (0 = default camera)
if not defined SMART_HOME_CAMERA_INDEX set SMART_HOME_CAMERA_INDEX=0
rem Clear any inherited Linux device path so the numeric index above takes effect
set SMART_HOME_CAMERA_DEVICE=

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found. Run this first:
    echo     venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

venv\Scripts\python.exe scripts\launch_win_camera.py
pause
