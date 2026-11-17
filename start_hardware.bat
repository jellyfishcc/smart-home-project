@echo off
setlocal
cd /d "%~dp0"

rem NOTE: keep this file ASCII-only. Non-ASCII batch files break cmd parsing
rem (cmd reads the file using the active code page) and show as mojibake in
rem editors that assume UTF-8. Chinese messages are printed by app.py instead.

rem =====================================================================
rem  Board ports. Re-plugging a board into a different USB port changes
rem  the COM number, so verify before running:
rem      venv\Scripts\python.exe scripts\serial_probe.py --list
rem
rem  How to tell the two boards apart (both report VID 2341 / PID 0043):
rem      venv\Scripts\python.exe scripts\serial_probe.py --port COMx --listen 6
rem        "@BOOT 1"           -> UNO I  environment board (DHT / fan / LED)
rem        "SmartHome Ready"   -> UNO II door board (servo / keypad / rain)
rem
rem  COM7 = UNO I  environment board
rem  COM8 = UNO II door board
rem =====================================================================
set SMART_HOME_SERIAL_ENABLED=1
set SMART_HOME_SERIAL_PORT=COM8
set SMART_HOME_SERIAL_ENV_ENABLED=1
set SMART_HOME_SERIAL_ENV_PORT=COM7

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

venv\Scripts\python.exe app.py
pause
