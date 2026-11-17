import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.serial_bridge import SerialBridge, parse_line


class FakeSerial:
    """模拟 UNOII：收到命令后按旧固件的实际行为回裸文本"""

    def __init__(self, silent=()):
        self.buf = []
        self.written = []
        self.silent = set(silent)   # 故意不回的命令，用于验超时
        self._lock = threading.Lock()

    def push(self, data):
        with self._lock:
            self.buf.append(data)

    def write(self, data):
        text = data.decode().strip()
        self.written.append(text)
        if text in self.silent:
            return len(data)

        def reply():
            time.sleep(0.02)
            if text == 'OPEN':
                self.push(b'OPEN OK\r\n')
                self.push('按键:1\r\n'.encode('utf-8'))
                self.push('密码正确\r\n'.encode('utf-8'))
                self.push('自动关门\r\n'.encode('utf-8'))
            elif text == 'QRAIN':
                self.push(b'NORAIN\r\n')
            elif text == 'PING':
                self.push(b'@PONG 1234\r\n')

        threading.Thread(target=reply, daemon=True).start()
        return len(data)

    def readline(self):
        for _ in range(60):
            with self._lock:
                if self.buf:
                    return self.buf.pop(0)
            time.sleep(0.005)
        return b''

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class ParseLineTest(unittest.TestCase):
    def test_new_protocol(self):
        self.assertEqual((parse_line('@ACK OPEN').kind, parse_line('@ACK OPEN').name),
                         ('ACK', 'OPEN'))
        msg = parse_line('@EVT DOOR OPEN')
        self.assertEqual((msg.kind, msg.name, msg.args), ('EVT', 'DOOR', ['OPEN']))
        msg = parse_line('@DATA ENV 253 61 1 0')
        self.assertEqual((msg.name, msg.args), ('ENV', ['253', '61', '1', '0']))
        # BOOT / PONG 没有「名字」这一层
        self.assertEqual(parse_line('@BOOT 1 3').args, ['1', '3'])
        self.assertEqual(parse_line('@PONG 1234').args, ['1234'])

    def test_legacy_protocol(self):
        msg = parse_line('OPEN OK')
        self.assertEqual((msg.kind, msg.name, msg.legacy), ('ACK', 'OPEN', True))
        self.assertEqual(parse_line('RAIN').args, ['1'])
        self.assertEqual(parse_line('NORAIN').args, ['0'])
        self.assertEqual(parse_line('SmartHome Ready').kind, 'BOOT')
        self.assertEqual(parse_line('自动关门').args, ['CLOSED'])
        self.assertEqual(parse_line('密码错误').args, ['KEYPAD_FAIL'])

    def test_noise_vs_known_log(self):
        noise = parse_line('一些认不出来的日志')
        self.assertEqual((noise.kind, noise.name), ('LOG', ''))
        key = parse_line('按键:7')
        self.assertEqual((key.kind, key.name, key.args), ('LOG', 'KEY', ['7']))
        self.assertIsNone(parse_line('   '))


class SerialBridgeTest(unittest.TestCase):
    def _bridge(self, silent=()):
        bridge = SerialBridge(port='FAKE', cmd_timeout=0.15, retries=1,
                              heartbeat_interval=0, rain_poll_interval=0)
        bridge._serial = FakeSerial(silent)
        bridge._port_actual = 'FAKE'
        bridge._connected = True
        bridge._last_rx = time.time()
        self.events = []
        self.data = []
        bridge.on_event(lambda m: self.events.append(str(m)))
        bridge.on_data(lambda m: self.data.append(str(m)))
        threading.Thread(target=bridge._reader_loop, daemon=True).start()
        time.sleep(0.05)
        self.addCleanup(bridge._stop.set)
        return bridge

    def test_open_door_gets_ack_and_events(self):
        bridge = self._bridge()
        result = bridge.open_door()

        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.reply.kind, 'ACK')
        self.assertEqual(bridge._serial.written, ['OPEN'])

        time.sleep(0.35)
        self.assertIn('@LOG KEY 1', self.events)
        self.assertIn('@EVT ACCESS KEYPAD_OK', self.events)
        # 固件关门后上报的事件必须落到上报镜像里
        self.assertIn('@EVT DOOR CLOSED', self.events)
        self.assertEqual(bridge.reported['door'], 'CLOSED')

    def test_query_rain(self):
        bridge = self._bridge()
        self.assertIs(bridge.query_rain(), False)
        self.assertIs(bridge.reported['rain'], False)

    def test_unknown_command_retries_then_times_out(self):
        bridge = self._bridge(silent=('CLOSE',))
        result = bridge.close_door()

        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 2)      # 1 次首发 + 1 次重试
        self.assertIn('超时', result.error)
        self.assertEqual(bridge._serial.written, ['CLOSE', 'CLOSE'])

    def test_disconnect_fails_fast(self):
        bridge = self._bridge()
        bridge._handle_disconnect(RuntimeError('USB 掉了'))

        result = bridge.open_door()
        self.assertFalse(result.ok)
        self.assertTrue(result.error)
        self.assertFalse(bridge.connected)
        self.assertIn('@EVT LINK LOST', self.events)


if __name__ == '__main__':
    unittest.main()
