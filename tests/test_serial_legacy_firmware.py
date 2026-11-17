"""
用一个「按 UNOII 现有固件真实行为说话」的假串口，验证插上板子后会发生什么。

这里刻意复刻固件的三个真实特征，而不是写个理想化的假设备：
  1. 裸文本回复，没有 @ 前缀（OPEN OK / NORAIN / SmartHome Ready）
  2. 只认 OPEN 和 QRAIN，其余命令（PING / CLOSE）一声不响
  3. 上电先打一行启动横幅，之前收到的字节全部丢弃

跑起来不需要任何硬件：python tests/test_serial_legacy_firmware.py -v
"""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.serial_bridge import SerialBridge


class LegacyBoard:
    """假串口 + 假固件：不接硬件也能验证 Python 侧的对接逻辑"""

    def __init__(self, boot_banner=True, boot_delay=0.05):
        self.out = queue.Queue()
        self.written = []
        self._lock = threading.Lock()
        if boot_banner:
            threading.Timer(
                boot_delay, lambda: self.out.put(b'SmartHome Ready\r\n')
            ).start()

    # ---- 板子收到的字节 ----
    def write(self, data):
        text = data.decode('ascii').replace('\r', '').replace('\n', '')
        with self._lock:
            self.written.append(text)

        def respond():
            time.sleep(0.01)
            if text == 'OPEN':
                # 固件先把回执打出来，再动舵机（所以 ACK 只代表「受理」）
                self.out.put(b'OPEN OK\r\n')
            elif text == 'QRAIN':
                self.out.put(b'NORAIN\r\n')
            # PING / CLOSE 这类它不认识的命令：不回复，完全静默

        threading.Thread(target=respond, daemon=True).start()
        return len(data)

    def readline(self):
        try:
            return self.out.get(timeout=0.2)
        except queue.Empty:
            return b''

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class LegacyFirmwareTest(unittest.TestCase):
    def _attach(self, board, **kwargs):
        bridge = SerialBridge(port='FAKE', **kwargs)
        bridge._serial = board
        bridge._port_actual = 'FAKE'
        bridge._connected = True
        bridge._last_rx = time.time()
        bridge._opened_at = time.time()
        bridge._boot_seen = False
        self.addCleanup(bridge._stop.set)
        return bridge

    def test_boot_banner_identifies_legacy_firmware(self):
        board = LegacyBoard()
        bridge = self._attach(board, heartbeat_interval=0, rain_poll_interval=0)
        threading.Thread(target=bridge._reader_loop, daemon=True).start()

        for _ in range(40):
            if bridge._boot_seen:
                break
            time.sleep(0.02)

        self.assertTrue(bridge._boot_seen)
        self.assertEqual(bridge.status()['protocol'], 'legacy')
        self.assertEqual(bridge.reported['physical_position'], 'unknown')   # 复位即关门

    def test_open_and_rain_work_over_plain_text(self):
        board = LegacyBoard()
        bridge = self._attach(board, cmd_timeout=0.3, retries=1,
                              heartbeat_interval=0, rain_poll_interval=0)
        threading.Thread(target=bridge._reader_loop, daemon=True).start()
        time.sleep(0.1)

        result = bridge.open_door()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.reply.kind, 'ACK')
        self.assertEqual(board.written, ['OPEN'])   # 5 字节 + \n，没有多余字符

        self.assertIs(bridge.query_rain(), False)
        self.assertIs(bridge.reported['rain'], False)

    def test_keepalive_uses_qrain_because_firmware_ignores_ping(self):
        board = LegacyBoard()
        bridge = self._attach(board, heartbeat_interval=0.2, rain_poll_interval=30,
                              offline_timeout=0.5)
        bridge._proto_version = 'legacy'
        bridge._boot_seen = True
        threading.Thread(target=bridge._scheduler_loop, daemon=True).start()
        time.sleep(0.75)

        with bridge._lock:
            sent = list(board.written)
        self.assertIn('QRAIN', sent)
        self.assertNotIn('PING', sent)      # 发 PING 只会换来静默，进而被误判离线

    def test_new_firmware_uses_ping(self):
        board = LegacyBoard(boot_banner=False)
        bridge = self._attach(board, heartbeat_interval=0.2, rain_poll_interval=30)
        bridge._proto_version = '1'
        bridge._boot_seen = True
        threading.Thread(target=bridge._scheduler_loop, daemon=True).start()
        time.sleep(0.5)

        with bridge._lock:
            sent = list(board.written)
        self.assertIn('PING', sent)

    def test_link_does_not_flap_with_legacy_firmware(self):
        """旧固件只在被问到时才说话，链路不能被反复判成离线"""
        board = LegacyBoard()
        bridge = self._attach(board, heartbeat_interval=0.2, rain_poll_interval=0,
                              offline_timeout=0.5)
        bridge._boot_seen = True
        threading.Thread(target=bridge._reader_loop, daemon=True).start()
        threading.Thread(target=bridge._scheduler_loop, daemon=True).start()

        samples = []
        for _ in range(12):
            time.sleep(0.15)
            samples.append(bridge.connected)

        self.assertTrue(all(samples), '链路在 1.8 秒内出现了离线抖动: %s' % samples)
        # 抖动消失的原因是保活真的换来了回执，而不是「碰巧没触发判定」
        self.assertIsNotNone(bridge.reported.get('rain'))

    def test_keepalive_starts_even_without_boot_banner(self):
        """有些 CH340 板子打开串口不复位，横幅早就被清掉，不能因此永不保活"""
        board = LegacyBoard(boot_banner=False)
        bridge = self._attach(board, heartbeat_interval=0.15, rain_poll_interval=0,
                              offline_timeout=0.5, boot_wait=0.2)
        threading.Thread(target=bridge._reader_loop, daemon=True).start()
        threading.Thread(target=bridge._scheduler_loop, daemon=True).start()
        time.sleep(0.8)

        with bridge._lock:
            sent = list(board.written)
        self.assertIn('QRAIN', sent)
        self.assertTrue(bridge.connected)

    def test_command_waits_for_boot_banner(self):
        """端口一打开板子就复位，这期间写进去的命令会被 bootloader 吞掉"""
        board = LegacyBoard(boot_banner=False)
        bridge = self._attach(board, boot_wait=0.25, cmd_timeout=0.2, retries=0,
                              heartbeat_interval=0, rain_poll_interval=0)

        started = time.time()
        bridge.send('OPEN', expect_reply=False)
        elapsed = time.time() - started

        self.assertGreaterEqual(elapsed, 0.2)
        self.assertEqual(board.written, ['OPEN'])   # 等完照样要发出去，不能静默丢弃

    def test_banner_releases_wait_early(self):
        board = LegacyBoard(boot_banner=False)
        bridge = self._attach(board, boot_wait=1.0, cmd_timeout=0.2, retries=0,
                              heartbeat_interval=0, rain_poll_interval=0)
        threading.Timer(0.08, lambda: setattr(bridge, '_boot_seen', True)).start()

        started = time.time()
        bridge.send('OPEN', expect_reply=False)
        elapsed = time.time() - started

        self.assertLess(elapsed, 0.5, '收到横幅后不该继续等到 boot_wait 结束')


class EndToEndTest(unittest.TestCase):
    """网页开门 → DeviceManager → HardwareService → 真实 SerialBridge → 假板子"""

    def setUp(self):
        from flask import Flask

        from services.device_manager import DeviceManager
        from services.hardware_service import HardwareService

        self.board = LegacyBoard()
        self.bridge = SerialBridge(port='FAKE', cmd_timeout=0.4, retries=1,
                                   heartbeat_interval=0, rain_poll_interval=0)
        self.bridge._serial = self.board
        self.bridge._port_actual = 'FAKE'
        self.bridge._connected = True
        self.bridge._last_rx = time.time()
        self.bridge._opened_at = time.time()
        self.bridge._boot_seen = False
        threading.Thread(target=self.bridge._reader_loop, daemon=True).start()
        self.addCleanup(self.bridge._stop.set)

        self.service = HardwareService()
        self.service.init_app(Flask(__name__))
        self.service.door_bridge = self.bridge
        # 生产代码在 HardwareService.start() 里做这两步，这里绕过了 start() 就要自己接
        self.bridge.on_event(self.service._on_event)
        self.bridge.on_data(self.service._on_data)
        self.addCleanup(self.service._cancel_auto_close)

        self.dm = DeviceManager()
        self.service.set_device_manager(self.dm)
        self.dm.set_hardware_bridge(self.service)

    def _wait_boot(self):
        for _ in range(50):
            if self.bridge._boot_seen:
                return True
            time.sleep(0.02)
        return False

    def test_unlock_from_web_really_writes_to_serial(self):
        self.assertTrue(self._wait_boot())

        result = self.dm.set_device('door', 'unlocked', source='manual')

        self.assertEqual(self.board.written, ['OPEN'])   # 真的发到串口了
        self.assertTrue(result['hardware']['ok'], result['hardware'])
        self.assertIsNone(self.dm.get_device('door')['locked'])

    def test_keypad_unlock_syncs_back_without_echo(self):
        self.assertTrue(self._wait_boot())

        # 板子上用键盘开门，软件只该「跟上状态」，不能反过来再发一条 OPEN
        self.board.out.put('密码正确\r\n'.encode('utf-8'))
        time.sleep(0.35)

        self.assertIsNone(self.dm.get_device('door')['locked'])
        self.assertEqual(self.board.written, [])

    def test_heartbeat_does_not_break_open(self):
        """保活和开门共用一条串口，绝不能互相踩"""
        self.assertTrue(self._wait_boot())
        for _ in range(3):
            self.board.out.put(b'NORAIN\r\n')
        time.sleep(0.1)

        result = self.dm.set_device('door', 'unlocked', source='manual')
        self.assertTrue(result['hardware']['ok'], result['hardware'])
        self.assertIn('OPEN', self.board.written)


if __name__ == '__main__':
    unittest.main()
