"""
串口通信层调试工具

不启动 Flask，只验证「Python 这边的串口层」是否正常工作。三种用法：

  1) 看本机有哪些串口，以及自动探测会挑哪个
       python scripts/serial_probe.py --list

  2) 监听一段时间，把收到的每一行按协议解析后打印
       python scripts/serial_probe.py --port COM3 --listen 20

  3) 发命令并打回执（会先等板子复位完）
       python scripts/serial_probe.py --port COM3 --send OPEN --send QRAIN

端口留空则自动探测。加 --raw 可以把原始字节一起打出来，排查乱码时用。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.serial_bridge import (  # noqa: E402
    PYSERIAL_AVAILABLE,
    SerialBridge,
    autodetect_port,
    list_serial_ports,
)


def cmd_list():
    if not PYSERIAL_AVAILABLE:
        print('pyserial 未安装：pip install pyserial')
        return 1
    ports = list_serial_ports()
    if not ports:
        print('没有发现任何串口。检查 USB 线是否插好、驱动是否装好。')
        return 1
    print('%-14s %-6s %s' % ('设备', '评分', '描述'))
    print('-' * 60)
    for p in ports:
        print('%-14s %-6d %s' % (p['device'], p['score'], p['description']))
    print('-' * 60)
    best = autodetect_port()
    print('自动探测结果: %s' % (best or '（没有匹配到 Arduino 类设备）'))
    return 0


def build_bridge(args):
    bridge = SerialBridge(port=args.port, baudrate=args.baud,
                          heartbeat_interval=0, rain_poll_interval=0)

    def on_event(msg):
        print('%s  [事件] %s' % (_now(), msg) + (_raw(msg, args)))

    def on_data(msg):
        print('%s  [数据] %s' % (_now(), msg) + (_raw(msg, args)))

    bridge.on_event(on_event)
    bridge.on_data(on_data)
    return bridge


def _now():
    return time.strftime('%H:%M:%S')


def _raw(msg, args):
    return '   <- %r' % msg.raw if args.raw else ''


def main():
    parser = argparse.ArgumentParser(description='串口通信层调试工具')
    parser.add_argument('--list', action='store_true', help='列出串口后退出')
    parser.add_argument('--port', default='', help='串口名，如 COM3 或 /dev/ttyUSB0；留空自动探测')
    parser.add_argument('--baud', type=int, default=9600, help='波特率，默认 9600')
    parser.add_argument('--listen', type=float, default=0, help='监听秒数')
    parser.add_argument('--send', action='append', default=[], help='发送命令，可重复')
    parser.add_argument('--raw', action='store_true', help='同时打印原始行')
    args = parser.parse_args()

    if args.list:
        return cmd_list()

    if not PYSERIAL_AVAILABLE:
        print('pyserial 未安装，先执行：pip install pyserial')
        return 1

    bridge = build_bridge(args)
    if not bridge.start():
        return 1

    try:
        # 打开串口会复位板子，先等启动横幅
        print('等待板子复位（约 2.5s）...')
        time.sleep(2.5)

        for text in args.send:
            parts = text.split()
            name, extra = parts[0], parts[1:]
            print('\n>>> %s' % ' '.join(parts))
            result = bridge.send(name, *extra)
            if result.ok:
                print('<<< 成功 (%d 次尝试, %.0fms) 回执=%s'
                      % (result.attempts, result.elapsed * 1000, result.reply))
            else:
                print('<<< 失败: %s (%d 次尝试, %.0fms)'
                      % (result.error, result.attempts, result.elapsed * 1000))

        # 额外演示两个便捷方法
        if 'QRAIN' in [s.split()[0].upper() for s in args.send if s.strip()]:
            print('query_rain() ->', bridge.query_rain())

        if 'QENV' in [s.split()[0].upper() for s in args.send if s.strip()]:
            print('query_env() ->', bridge.query_env())

        if args.listen > 0:
            print('\n监听 %.0fs，Ctrl+C 提前结束...' % args.listen)
            time.sleep(args.listen)
    except KeyboardInterrupt:
        print('\n已中断')
    finally:
        print('\n状态: %s' % bridge.status())
        bridge.stop()

    return 0


if __name__ == '__main__':
    sys.exit(main())
