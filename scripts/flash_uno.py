"""
把 UNOI 固件编译并烧录到环境板（Arduino UNO R3）。

用法：
    venv/Scripts/python.exe scripts/flash_uno.py                  # 自动找环境板并烧录
    venv/Scripts/python.exe scripts/flash_uno.py --port COM7       # 指定端口（仍会校验是不是环境板）
    venv/Scripts/python.exe scripts/flash_uno.py --compile-only    # 只编译，不烧录
    venv/Scripts/python.exe scripts/flash_uno.py --force           # 跳过板子身份校验（危险）

为什么不用 Arduino IDE：
    本机没装独立的 arduino-cli，但 Arduino App Lab 自带一个（arduino-cli 1.5.x）。
    这里直接调它，并把核心包/库放到项目 .cache/arduino 下，不动 App Lab 自己的配置。

为什么要关 LTO：
    AVR 核心默认 -flto，avr-gcc 7.3 链接 U8g2 这种大库要跑 8 分钟以上（实测还像卡死）。
    关掉后 1 分钟出固件，生成的机器码行为不变，只是体积略大一点。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------- 配置（改这里，不用传参） ----------------
ARDUINO_CLI = Path(os.environ.get(
    'ARDUINO_CLI',
    r'C:\Users\86189\AppData\Local\AppLab\resources\arduino\arduino-cli\arduino-cli.exe',
))
SKETCH_SRC = ROOT / '硬件代码' / 'design-and-build-project-main' / 'UNOI'
# 这两个目录只是编译缓存（.cache 已被 gitignore）；目录名沿用已经编过一轮的路径，
# 这样改完固件再烧时只重编 sketch 本身，不必再等 U8g2 的字体表
SKETCH_DIR = ROOT / '.cache' / 'build' / 'UNOI'
SKETCH_INO = SKETCH_DIR / 'UNOI.ino'
BUILD_DIR = ROOT / '.cache' / 'build-out'
ARDUINO_DATA = ROOT / '.cache' / 'arduino' / 'data'
ARDUINO_USER = ROOT / '.cache' / 'arduino' / 'user'
ARDUINO_DL = ROOT / '.cache' / 'arduino' / 'staging'

FQBN = 'arduino:avr:uno'
CORE = 'arduino:avr'
LIBS = ['U8g2', 'DHT sensor library', 'Adafruit Unified Sensor', 'Adafruit NeoPixel']

# 关掉 -flto，只影响编译速度与体积，不影响行为
BUILD_PROPS = [
    'compiler.c.flags=-c -g -Os -w -std=gnu11 '
    '-ffunction-sections -fdata-sections -MMD',
    'compiler.cpp.flags=-c -g -Os -w -std=gnu++11 -fpermissive -fno-exceptions '
    '-ffunction-sections -fdata-sections -fno-threadsafe-statics '
    '-Wno-error=narrowing -MMD',
    'compiler.c.elf.flags=-w -Os -g -Wl,--gc-sections',
]
# ----------------------------------------------------------


def _env():
    env = os.environ.copy()
    env['ARDUINO_DIRECTORIES_DATA'] = str(ARDUINO_DATA)
    env['ARDUINO_DIRECTORIES_USER'] = str(ARDUINO_USER)
    env['ARDUINO_DIRECTORIES_DOWNLOADS'] = str(ARDUINO_DL)
    return env


def cli(*args, capture=True):
    """跑一条 arduino-cli 命令，返回 (退出码, 输出)"""
    cmd = [str(ARDUINO_CLI)] + list(args)
    proc = subprocess.run(cmd, env=_env(), text=True,
                          capture_output=capture, encoding='utf-8', errors='replace')
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def ensure_toolchain():
    """首次运行时装核心和库；已有就跳过"""
    for d in (ARDUINO_DATA, ARDUINO_USER, ARDUINO_DL):
        d.mkdir(parents=True, exist_ok=True)

    code, out = cli('core', 'list')
    if CORE not in out:
        print('[工具链] 安装 %s（首次运行，需要下载几十兆）...' % CORE)
        cli('core', 'update-index')
        code, out = cli('core', 'install', CORE)
        if code != 0:
            raise SystemExit('核心安装失败:\n' + out)

    code, out = cli('lib', 'list')
    for lib in LIBS:
        if lib not in out:
            print('[工具链] 安装库 %s ...' % lib)
            code, out = cli('lib', 'install', lib)
            if code != 0:
                raise SystemExit('库 %s 安装失败:\n%s' % (lib, out))


def prepare_sketch():
    """UNOI 没有 .ino 后缀，arduino-cli 要求 目录名/同名.ino，所以复制一份去编"""
    if not SKETCH_SRC.exists():
        raise SystemExit('找不到固件: %s' % SKETCH_SRC)
    SKETCH_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKETCH_SRC, SKETCH_INO)
    print('[固件] 源文件 %s -> %s' % (SKETCH_SRC.name, SKETCH_INO.name))


def compile_sketch():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    args = ['compile', '--jobs', '2', '--build-path', str(BUILD_DIR)]
    for prop in BUILD_PROPS:
        args += ['--build-property', prop]
    args += ['--fqbn', FQBN, str(SKETCH_DIR)]

    print('[编译] 开始（首次要编 U8g2 字体表，可能要几分钟；之后增量只要几秒）...')
    started = time.time()
    code, out = cli(*args)
    if code != 0:
        raise SystemExit('编译失败:\n' + out[-3000:])

    for line in out.splitlines():
        if 'Sketch uses' in line or 'Global variables' in line:
            print('[编译]', line.strip())
    print('[编译] 完成，用时 %.0fs' % (time.time() - started))
    hex_path = BUILD_DIR / 'UNOI.ino.hex'
    if not hex_path.exists():
        raise SystemExit('没找到产物 %s' % hex_path)
    return hex_path


def probe_env_board(port, wait_boot=3.6, listen=2.0):
    """打开端口发 QENV，确认这块板子跑的是 UNOI（防止把门禁板烧了）"""
    import serial
    try:
        ser = serial.Serial(port, 9600, timeout=0.2)
    except Exception as exc:
        return False, '打不开: %s' % exc
    try:
        time.sleep(wait_boot)          # 开串口会让 UNO 复位，等 setup 跑完
        ser.reset_input_buffer()
        ser.write(b'QENV\n')
        deadline, got = time.time() + listen, []
        while time.time() < deadline:
            line = ser.readline().decode('ascii', 'replace').strip()
            if line:
                got.append(line)
                if line.startswith('@DATA ENV'):
                    return True, line
        return False, '没回 @DATA ENV（收到 %s）' % (got or '空')
    finally:
        ser.close()


def pick_port(explicit=None):
    if explicit:
        ok, detail = probe_env_board(explicit)
        if not ok:
            raise SystemExit('%s 不像环境板：%s\n（确认板子插对、没被别的程序占用；'
                             '确实要烧就加 --force）' % (explicit, detail))
        print('[端口] %s 校验通过：%s' % (explicit, detail))
        return explicit

    import serial.tools.list_ports as list_ports
    ports = [p.device for p in list_ports.comports()]
    if not ports:
        raise SystemExit('没有可用串口，先插板子')
    for port in ports:
        ok, detail = probe_env_board(port)
        if ok:
            print('[端口] 自动识别到环境板 %s：%s' % (port, detail))
            return port
    raise SystemExit('没找到环境板（试过 %s）。用 --port 指定，或加 --force 跳过校验'
                     % ', '.join(ports))


def upload(port):
    args = ['upload', '-p', port, '--fqbn', FQBN,
            '--input-dir', str(BUILD_DIR), str(SKETCH_DIR)]
    print('[烧录] %s ...' % port)
    code, out = cli(*args)
    if code != 0 or 'Error' in out:
        raise SystemExit('烧录失败:\n' + out[-2000:])
    print('[烧录] 完成')


def verify(port):
    """烧完读一次温湿度。刚复位时 DHT 还没采样，会先回 250/500/0，
    所以多问几轮，直到标志位变成 1（真有读数）为止。"""
    import serial
    ser = serial.Serial(port, 9600, timeout=0.3)
    try:
        time.sleep(3.2)
        last = ''
        for _ in range(5):
            ser.reset_input_buffer()
            ser.write(b'QENV\n')
            deadline, got = time.time() + 2.0, ''
            while time.time() < deadline:
                line = ser.readline().decode('ascii', 'replace').strip()
                if line.startswith('@DATA ENV'):
                    got = line
                    break
            if got:
                last = got
                if got.split()[-1] == '1':
                    break
            time.sleep(1.5)
        ok = last.endswith(' 1')
        print('[验收] %s' % ('通过：' + last + '（温度/湿度已按 ×10 上报）' if ok
                            else '串口通了但还没读到有效温湿度：' + (last or '无回执')))
        return ok
    finally:
        ser.close()


def main():
    ap = argparse.ArgumentParser(description='编译并烧录 UNOI 环境板固件')
    ap.add_argument('--port', help='串口，例如 COM7；不填则自动识别')
    ap.add_argument('--compile-only', action='store_true', help='只编译不烧录')
    ap.add_argument('--force', action='store_true', help='跳过“是不是环境板”的校验')
    args = ap.parse_args()

    if not ARDUINO_CLI.exists():
        raise SystemExit('找不到 arduino-cli: %s\n用环境变量 ARDUINO_CLI 指定路径' % ARDUINO_CLI)

    ensure_toolchain()
    prepare_sketch()
    compile_sketch()

    if args.compile_only:
        print('[完成] 只编译，产物在 %s' % BUILD_DIR)
        return 0

    port = args.port if args.force and args.port else pick_port(args.port)
    upload(port)
    time.sleep(0.5)
    return 0 if verify(port) else 1


if __name__ == '__main__':
    sys.exit(main())
