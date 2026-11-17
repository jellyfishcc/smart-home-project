"""
环境板（UNO I）QENV 回传的对接测试。

假串口按「改完的 UNOI 固件」真实行为说话：
  1. 上电打 `@BOOT 1`（协议版本 1，不是裸文本 Ready）
  2. 认 `QENV` -> `@DATA ENV 253 610 1`（温度×10 在前、湿度×10 在后）
  3. 认 `PING` -> `@PONG <millis>`
  4. 其余大写命令 -> `@NAK <cmd>`

跑起来不需要硬件：python tests/test_serial_qenv.py -v
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.serial_bridge import Message, SerialBridge, parse_line


class EnvBoard:
    """假 UNO I：supports_qenv=False 用来模拟还没烧新固件的老板子"""

    def __init__(self, supports_qenv=True, boot_banner=True):
        self.buf = []
        self.written = []
        self.supports_qenv = supports_qenv
        self._lock = threading.Lock()
        if boot_banner:
            threading.Timer(0.02, lambda: self.push(b'@BOOT 1\r\n')).start()

    def push(self, data):
        with self._lock:
            self.buf.append(data)

    def write(self, data):
        text = data.decode('ascii').strip()
        with self._lock:
            self.written.append(text)
        if text == 'QENV' and not self.supports_qenv:
            return len(data)        # 老固件：没有 Serial.read，一声不响

        def reply():
            time.sleep(0.01)
            parts = text.split()
            if text == 'QENV':
                self.push(b'@DATA ENV 253 610 1\r\n')
            elif text == 'PING':
                self.push(b'@PONG 1234\r\n')
            elif parts and parts[0] == 'FAN':
                self.push(('@ACK FAN %s\r\n' % parts[1]).encode('ascii'))
            elif parts and parts[0] == 'LAMP':
                # 固件回的是「实际生效」的开关和亮度，省略亮度就沿用上一次
                level = parts[2] if len(parts) > 2 else '30'
                self.push(('@ACK LAMP %s %s\r\n' % (parts[1], level)).encode('ascii'))
            else:
                self.push(('@NAK %s\r\n' % text).encode('ascii'))

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


class QEnvParseTest(unittest.TestCase):
    def test_env_line_keeps_temperature_before_humidity(self):
        msg = parse_line('@DATA ENV 253 610 1')
        self.assertEqual((msg.kind, msg.name), ('DATA', 'ENV'))
        self.assertEqual(msg.args, ['253', '610', '1'])


class QEnvBridgeTest(unittest.TestCase):
    def _attach(self, board, **kwargs):
        kwargs.setdefault('cmd_timeout', 0.2)
        kwargs.setdefault('retries', 1)
        kwargs.setdefault('boot_wait', 0)
        kwargs.setdefault('heartbeat_interval', 0)
        kwargs.setdefault('rain_poll_interval', 0)
        bridge = SerialBridge(port='FAKE', **kwargs)
        bridge._serial = board
        bridge._port_actual = 'FAKE'
        bridge._connected = True
        bridge._last_rx = time.time()
        bridge._opened_at = time.time()
        bridge._boot_seen = True
        self.data = []
        bridge.on_data(lambda m: self.data.append(str(m)))
        self.events = []
        bridge.on_event(lambda m: self.events.append(str(m)))
        threading.Thread(target=bridge._reader_loop, daemon=True).start()
        time.sleep(0.05)
        self.addCleanup(bridge._stop.set)
        return bridge

    def test_query_env_returns_scaled_values(self):
        board = EnvBoard()
        bridge = self._attach(board)

        self.assertEqual(bridge.query_env(), (25.3, 61.0))
        # 只有收到 @DATA ENV 才算数：少了 _fulfill 里那行映射，这里会是 3 次尝试 + 超时
        self.assertEqual(board.written, ['QENV'])
        self.assertEqual(bridge.reported['env'], ['253', '610', '1'])

    def test_query_env_raw_keeps_dht_flag(self):
        bridge = self._attach(EnvBoard())
        self.assertEqual(bridge.query_env_raw(), ['253', '610', '1'])

    def test_unsolicited_env_data_is_not_swallowed(self):
        """没有命令在等的时候，@DATA ENV 必须照样发给订阅者"""
        board = EnvBoard(boot_banner=False)
        bridge = self._attach(board)
        board.push(b'@DATA ENV 268 550 1\r\n')
        time.sleep(0.15)

        self.assertIn('@DATA ENV 268 550 1', self.data)
        self.assertEqual(bridge.reported['env'], ['268', '550', '1'])

    def test_old_firmware_still_times_out_cleanly(self):
        """老固件没有 QENV：要老实超时返回 None，而不是假装成功"""
        board = EnvBoard(supports_qenv=False, boot_banner=False)
        bridge = self._attach(board)

        self.assertIsNone(bridge.query_env())
        self.assertEqual(board.written, ['QENV', 'QENV'])   # 1 次首发 + 1 次重试
        self.assertNotIn('env', bridge.reported)

    def test_scheduler_polls_env_without_explicit_call(self):
        board = EnvBoard(boot_banner=False)
        bridge = self._attach(board, env_poll_interval=0.2)
        threading.Thread(target=bridge._scheduler_loop, daemon=True).start()

        for _ in range(40):
            if bridge.reported.get('env'):
                break
            time.sleep(0.02)

        self.assertEqual(bridge.reported.get('env'), ['253', '610', '1'])
        self.assertIn('QENV', board.written)

    def test_ping_answered_by_env_firmware(self):
        """@BOOT 1 之后上位机会用 PING 保活，环境板必须回 @PONG"""
        bridge = self._attach(EnvBoard(boot_banner=False))
        self.assertIsNotNone(bridge.ping())

    def test_fan_command_matches_its_ack(self):
        """@ACK FAN 1 的等待键是命令名 'FAN'，不能被 @EVT FAN 抢走"""
        board = EnvBoard(boot_banner=False)
        bridge = self._attach(board)

        result = bridge.send('FAN', 1)
        self.assertTrue(result, result.error)
        self.assertEqual(result.reply.args, ['1'])
        self.assertEqual(board.written, ['FAN 1'])

    def test_lamp_command_carries_brightness(self):
        board = EnvBoard(boot_banner=False)
        bridge = self._attach(board)

        result = bridge.send('LAMP', 1, 60)
        self.assertTrue(result, result.error)
        self.assertEqual(result.reply.args, ['1', '60'])
        self.assertEqual(board.written, ['LAMP 1 60'])

    def test_ack_is_not_replayed_as_event(self):
        """回执已经被等待者吃掉，不能再当事件抛给业务层，否则会二次同步"""
        board = EnvBoard(boot_banner=False)
        bridge = self._attach(board)
        bridge.send('FAN', 0)

        self.assertEqual(self.events, [])


class _RecordingDeviceManager:
    """带最小状态的假 DeviceManager：BOOT 回读会去查风扇/灯光当前状态"""

    def __init__(self):
        self.calls = []
        self._state = {
            'door': {'locked': True},
            'fan': {'on': False, 'speed': 0},
            'light': {'on': False, 'brightness': 0},
        }

    def get_device(self, name):
        return dict(self._state.get(name, {}))

    def set_device(self, device, status, value=None, source='manual', **kwargs):
        self.calls.append((device, status, value, source))
        if device == 'fan':
            self._state['fan']['on'] = (status == 'on')
        elif device == 'light':
            self._state['light']['on'] = (status == 'on')
            if status == 'off':
                self._state['light']['brightness'] = 0
            elif value is not None:
                self._state['light']['brightness'] = int(value)


class _RecordingSocketIO:
    def __init__(self):
        self.events = []

    def emit(self, name, payload=None):
        self.events.append((name, payload))


class EnvIsolationTest(unittest.TestCase):
    """环境板不能把门禁状态带偏：两块板共用一个 HardwareService"""

    def test_env_board_events_never_touch_door_state(self):
        from services.hardware_service import HardwareService

        service = HardwareService()
        dm = _RecordingDeviceManager()
        service.set_device_manager(dm)

        # 环境板复位 + 链路抖动，都不该触发 _sync_door
        service._on_env_event(Message('BOOT', '', ['1']))
        service._on_env_event(Message('EVT', 'LINK', ['LOST']))
        service._on_env_event(Message('NAK', 'QENV', ['NODATA']))

        self.assertEqual(dm.calls, [])

    def test_env_bridge_requires_explicit_port(self):
        """端口留空时绝不退回自动探测：否则会抢门禁板那条 COM"""
        from services.hardware_service import HardwareService

        service = HardwareService()
        self.assertIsNone(service._start_env_bridge(
            {'SERIAL_ENV_ENABLED': True, 'SERIAL_ENV_PORT': ''}))
        self.assertIsNone(service._start_env_bridge(
            {'SERIAL_ENV_ENABLED': False, 'SERIAL_ENV_PORT': 'COM4'}))


class EnvApplyTest(unittest.TestCase):
    """@DATA ENV 落到前端的那一段：socket 推送与标志位过滤"""

    def _service(self, sio):
        from services.hardware_service import HardwareService

        service = HardwareService()
        service.set_socketio(sio)
        # 这条分支会写全局模拟器，跑完还原，避免污染别的用例
        from services.sensor_simulator import sensor_simulator

        before = sensor_simulator.get_current_reading()
        self.addCleanup(lambda: sensor_simulator.inject_reading(
            before['temperature'], before['humidity']))
        return service

    def test_valid_reading_pushed_to_frontend(self):
        sio = _RecordingSocketIO()
        service = self._service(sio)

        service._on_data(Message('DATA', 'ENV', ['217', '210', '1']))

        self.assertEqual(len(sio.events), 1)
        name, payload = sio.events[0]
        self.assertEqual(name, 'sensor_update')
        self.assertEqual((payload['temperature'], payload['humidity']), (21.7, 21.0))
        self.assertEqual(payload['source'], 'hardware')

    def test_reading_before_dht_ready_is_not_pushed(self):
        """23:50 上电时固件先回 250/500/0，这对默认值不该刷到页面上"""
        sio = _RecordingSocketIO()
        service = self._service(sio)

        service._on_data(Message('DATA', 'ENV', ['250', '500', '0']))

        self.assertEqual(sio.events, [])
        # 但原始报文还是要留档，方便排查
        self.assertEqual(service.status()['env']['args'], ['250', '500', '0'])


if __name__ == '__main__':
    unittest.main()
