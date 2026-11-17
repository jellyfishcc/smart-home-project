import sys
import unittest
from pathlib import Path

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.device_manager import DeviceManager
from services.hardware_service import HardwareService
from services.serial_bridge import CommandResult, Message


class StubHardware:
    """假硬件层，只记录被调用了什么"""

    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def open_door(self):
        self.calls.append('open')
        return {'command': 'OPEN', 'ok': self.ok, 'via': 'serial'}

    def close_door(self):
        self.calls.append('close')
        return {'command': 'CLOSE', 'ok': self.ok, 'via': 'serial'}


class StubBridge:
    """假串口桥，用于 HardwareService 的出站测试"""

    def __init__(self, ok=True, protocol='legacy'):
        self.ok = ok
        self.protocol = protocol
        self.opened = 0
        self.closed = 0

    def open_door(self):
        self.opened += 1
        return CommandResult(self.ok, 'OPEN', attempts=1, elapsed=0.02,
                             error='' if self.ok else '超时 300ms 未收到回执')

    def close_door(self):
        self.closed += 1
        return CommandResult(self.ok, 'CLOSE', attempts=1, elapsed=0.02)

    def status(self):
        return {'connected': True, 'port': 'FAKE', 'protocol': self.protocol}

    def stop(self):
        pass


def make_service(dm, bridge=None):
    service = HardwareService()
    service.init_app(Flask(__name__))
    service.set_device_manager(dm)
    service.door_bridge = bridge if bridge is not None else StubBridge()
    return service


class DeviceManagerHookTest(unittest.TestCase):
    def setUp(self):
        self.dm = DeviceManager()
        self.hw = StubHardware()
        self.dm.set_hardware_bridge(self.hw)

    def test_unlock_dispatches_open(self):
        result = self.dm.set_device('door', 'unlocked')
        self.assertEqual(self.hw.calls, ['open'])
        self.assertEqual(result['hardware']['command'], 'OPEN')

    def test_hardware_source_does_not_echo(self):
        # 板子键盘开门的回传，不能再回发一条 OPEN
        self.dm.set_device('door', 'unlocked', source='hardware')
        self.assertEqual(self.hw.calls, [])
        self.assertFalse(self.dm.get_device('door')['locked'])

    def test_non_door_device_not_dispatched(self):
        self.dm.set_device('fan', 'on')
        self.dm.set_device('light', 'on', value=40)
        self.assertEqual(self.hw.calls, [])

    def test_no_bridge_is_safe(self):
        dm = DeviceManager()
        result = dm.set_device('door', 'unlocked')
        self.assertNotIn('hardware', result)
        self.assertFalse(result['state']['locked'])


class HardwareServiceInboundTest(unittest.TestCase):
    def setUp(self):
        self.dm = DeviceManager()
        self.service = make_service(self.dm)

    def tearDown(self):
        self.service._cancel_auto_close()

    def test_keypad_open_syncs_state_without_echo(self):
        self.service._on_event(Message('EVT', 'ACCESS', ['KEYPAD_OK']))
        self.assertFalse(self.dm.get_device('door')['locked'])
        self.assertEqual(self.service.door_bridge.opened, 0)   # 不回发

    def test_auto_close_event_locks_door(self):
        self.dm.set_device('door', 'unlocked', source='hardware')
        self.service._on_event(Message('EVT', 'DOOR', ['CLOSED']))
        self.assertTrue(self.dm.get_device('door')['locked'])

    def test_boot_forces_locked(self):
        self.dm.set_device('door', 'unlocked', source='hardware')
        # 板子复位 = 舵机回 0°，软件必须跟着认为门是关的
        self.service._on_event(Message('BOOT', '', ['legacy']))
        self.assertTrue(self.dm.get_device('door')['locked'])

    def test_duplicate_event_does_not_rewrite(self):
        self.dm.set_device('door', 'unlocked', source='hardware')
        before = self.dm.get_device('door')
        self.service._on_event(Message('EVT', 'DOOR', ['OPEN']))
        self.assertEqual(self.dm.get_device('door'), before)

    def test_rain_data_cached(self):
        self.service._on_data(Message('DATA', 'RAIN', ['1']))
        self.assertIs(self.service.status()['rain'], True)


class HardwareServiceOutboundTest(unittest.TestCase):
    def setUp(self):
        self.dm = DeviceManager()
        self.bridge = StubBridge()
        self.service = make_service(self.dm, self.bridge)

    def tearDown(self):
        self.service._cancel_auto_close()

    def test_open_door_sends_and_arms_timer(self):
        info = self.service.open_door()
        self.assertTrue(info['ok'])
        self.assertEqual(self.bridge.opened, 1)
        self.assertIsNotNone(self.service._auto_close_timer)

    def test_close_skipped_on_legacy_firmware(self):
        info = self.service.close_door()
        self.assertTrue(info['skipped'])
        self.assertEqual(self.bridge.closed, 0)   # 不去白等 900ms

    def test_close_sent_on_new_firmware(self):
        self.service.door_bridge = StubBridge(protocol='1')
        self.service.close_door()
        self.assertEqual(self.service.door_bridge.closed, 1)

    def test_failed_open_rolls_back_state(self):
        self.dm.set_device('door', 'unlocked', source='hardware')
        self.service.door_bridge = StubBridge(ok=False)
        info = self.service.open_door()
        self.assertFalse(info['ok'])
        self.assertTrue(self.dm.get_device('door')['locked'])

    def test_no_bridge_returns_skipped(self):
        self.service.door_bridge = None
        self.assertTrue(self.service.open_door()['skipped'])


if __name__ == '__main__':
    unittest.main()
