"""串口通信层调试工具。

只读枚举：python scripts/serial_probe.py --list
连接时必须显式传 --usb-serial；按 USB 身份解析端口，不按 tty 编号猜角色。
--listen 和 --send 都会打开串口并可能复位板卡，只在授权联调时使用。
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # read configuration only; does not start the application

from services.serial_bridge import (  # noqa: E402
    PYSERIAL_AVAILABLE,
    SerialBridge,
    list_serial_ports,
    decode_env,
)


def cmd_list():
    if not PYSERIAL_AVAILABLE:
        print('pyserial 未安装：pip install pyserial')
        return 1
    ports = list_serial_ports()
    if not ports:
        print('没有发现任何串口。检查 USB 线是否插好、驱动是否装好。')
        return 1
    print('%-14s %-26s %s' % ('设备', 'USB Serial Number', '描述'))
    print('-' * 60)
    for p in ports:
        print('%-14s %-26s %s' % (p['device'], p.get('serial_number') or 'unknown', p['description']))
    print('-' * 60)
    return 0


def build_bridge(args):
    identity = (args.usb_serial or '').strip()
    if not identity:
        raise ValueError('usb_serial_mapping_required: 请显式传 --usb-serial')
    env_query = any(s.split() and s.split()[0].upper() == 'QENV' for s in getattr(args, 'send', []))
    boot_wait = config.SERIAL_ENV_BOOT_WAIT if env_query else config.SERIAL_BOOT_WAIT
    bridge = SerialBridge(port=args.port, usb_serial=identity, baudrate=args.baud,
                          boot_wait=boot_wait,
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
    parser.add_argument('--port', default='', help='兼容端口参数；Linux 按 USB Serial Number 解析，不据此猜身份')
    parser.add_argument('--usb-serial', default='', help='目标板 USB Serial Number（连接必填）')
    parser.add_argument('--baud', type=int, default=9600, help='波特率，默认 9600')
    parser.add_argument('--post-boot-wait', type=float, default=0,
                        help='诊断用：ready 后、发送命令前额外等待秒数（默认 0）')
    parser.add_argument('--listen', type=float, default=0, help='监听秒数')
    parser.add_argument('--send', action='append', default=[], help='发送命令，可重复')
    parser.add_argument('--raw', action='store_true', help='同时打印原始行')
    args = parser.parse_args()

    if args.list:
        return cmd_list()

    if not math.isfinite(args.post_boot_wait) or args.post_boot_wait < 0:
        parser.error('--post-boot-wait 必须是有限的非负秒数')

    if not args.usb_serial.strip():
        parser.error('usb_serial_mapping_required: 请显式传 --usb-serial')

    if not PYSERIAL_AVAILABLE:
        print('pyserial 未安装，先执行：pip install pyserial')
        return 1

    bridge = build_bridge(args)
    if not bridge.start():
        return 1

    try:
        print('命令将在实际串口打开并完成 boot readiness 后发送。')

        if args.send and args.post_boot_wait > 0:
            # Diagnostic-only wait: reuse transport readiness without sending.
            if bridge._wait_boot() is None:
                print('transport/boot readiness 未完成，不发送命令。')
                return 1
            print('诊断等待 %.2fs（ready 之后）...' % args.post_boot_wait)
            time.sleep(args.post_boot_wait)

        for text in args.send:
            parts = text.split()
            name, extra = parts[0], parts[1:]
            print('\n>>> %s' % ' '.join(parts))
            result = bridge.send(name, *extra)
            if result.ok:
                print('<<< 成功 (%d 次尝试, %.0fms) 回执=%s'
                      % (result.attempts, result.elapsed * 1000, result.reply))
                if name.upper() == 'QENV' and result.reply:
                    reading = decode_env(result.reply.args)
                    print('ENV reading:', reading if reading is not None else 'invalid (DHT 未就绪)')
            else:
                print('<<< 失败: %s (%d 次尝试, %.0fms)'
                      % (result.error, result.attempts, result.elapsed * 1000))

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
