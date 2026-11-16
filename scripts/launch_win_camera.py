"""Windows 摄像头模式启动器。

中文提示统一放在这里（Python 源文件是 UTF-8，输出到控制台由 Python 走 Unicode API，
不受 cmd 代码页影响），.bat 里只保留 ASCII，避免批处理的中文编码问题。
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://localhost:5000'
TITLE = '智能家居管理系统 - Windows 摄像头模式'


def set_console_title() -> None:
    if os.name == 'nt':
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(TITLE)
        except Exception:
            pass


def check_environment() -> bool:
    ok = True
    if not (ROOT / 'venv' / 'Scripts' / 'python.exe').exists():
        print('[错误] 未找到虚拟环境 venv，请先执行：')
        print('    venv\\Scripts\\python.exe -m pip install -r requirements.txt')
        ok = False
    if not (ROOT / 'models' / 'models' / 'buffalo_l' / 'det_10g.onnx').exists():
        print('[警告] 未找到 InsightFace buffalo_l 模型，人脸识别会在启动时失败。')
        print('        请先执行： venv\\Scripts\\python.exe scripts\\download_face_models.py')
        print()
    return ok


def open_browser_when_ready(timeout: float = 90.0) -> None:
    """轮询直到服务真正可访问，再打开浏览器（冷启动加载模型约 15~25 秒）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL + '/', timeout=2) as resp:
                if resp.status == 200:
                    webbrowser.open(URL)
                    return
        except Exception:
            pass
        time.sleep(1.5)


def main() -> int:
    set_console_title()
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        sys.stdout.reconfigure(line_buffering=True, errors='replace')
    except Exception:
        pass

    if not check_environment():
        input('按回车退出...')
        return 1

    index = os.environ.get('SMART_HOME_CAMERA_INDEX', '0')
    print('=' * 50)
    print('  智能家居管理系统 - Windows 摄像头模式')
    print(f'  摄像头索引 : {index}')
    print('  切换摄像头 : set SMART_HOME_CAMERA_INDEX=1 后再运行本脚本')
    print(f'  访问地址   : {URL}')
    print('  停止服务   : 按 Ctrl+C')
    print('=' * 50)
    print()

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    import runpy

    try:
        runpy.run_path(str(ROOT / 'app.py'), run_name='__main__')
    except KeyboardInterrupt:
        pass
    print('服务已停止。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
