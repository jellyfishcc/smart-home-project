"""
环境板（UNO I）控制链路的测试：FAN / LAMP 下发与状态回读。

对应固件协议（UNOI 的手动控制区块）：
  FAN 1 / FAN 0       -> @ACK FAN <1|0>
  LAMP 1 60 / LAMP 0  -> @ACK LAMP <1|0> <亮度 0~100>
  自治或手动窗口到期  -> @EVT FAN ON|OFF、@EVT LAMP ON|OFF <亮度>

跑起来不需要硬件：python tests/test_env_control.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.serial_bridge import Message


class FakeResult:
    ok = True
    attempts = 1
    elapsed = 0.02
    error = ''
    reply = None

    def __bool__(self):
        return self.ok


class FakeEnvBridge:
    """只记录发了什么命令，不碰串口"""

    def __init__(self, protocol='1', boot_count=1):
        self.cmds = []
        self.kwargs = []
        self._protocol = protocol
        self._boot_count = boot_count

    def status(self):
        return {'protocol': self._protocol, 'boot_count': self._boot_count}

    def send(self, name, *args, **kwargs):
        self.cmds.append((name,) + args)
        self.kwargs.append(kwargs)
        return FakeResult()


class FakeHardware:
    """DeviceManager 眼里的硬件对接层：只关心被调用了什么"""

    def __init__(self):
        self.calls = []

    def open_door(self):
        self.calls.append(('door', 'open'))
        return {'ok': True}

    def close_door(self):
        self.calls.append(('door', 'close'))
        return {'ok': True}

    def set_fan(self, on):
        self.calls.append(('fan', on))
        return {'ok': True}

    def set_lamp(self, on, brightness=None):
        self.calls.append(('lamp', on, brightness))
        return {'ok': True}


class FakeDeviceManager:
    """带真实状态的简化版 DeviceManager，用来观察回读同步"""

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
            self._state['fan']['speed'] = 2 if status == 'on' else 0
        elif device == 'light':
            self._state['light']['on'] = (status == 'on')
            if status == 'off':
                self._state['light']['brightness'] = 0
            elif value is not None:
                self._state['light']['brightness'] = int(value)
        elif device == 'door':
            self._state['door']['locked'] = (status == 'locked')


def _service(bridge=None):
    from services.hardware_service import HardwareService

    service = HardwareService()
    if bridge is not None:
        service.env_bridge = bridge
    return service


class EnvCommandTest(unittest.TestCase):
    """下发：命令字、参数顺序、老固件跳过"""

    def test_set_fan_sends_one_or_zero(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        self.assertTrue(service.set_fan(True)['ok'])
        self.assertTrue(service.set_fan(False)['ok'])
        self.assertEqual(bridge.cmds, [('FAN', 1), ('FAN', 0)])

    def test_set_lamp_sends_brightness(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        self.assertTrue(service.set_lamp(True, 60)['ok'])
        self.assertEqual(bridge.cmds, [('LAMP', 1, 60)])

    def test_set_lamp_off_ignores_brightness(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        service.set_lamp(False, 80)
        self.assertEqual(bridge.cmds, [('LAMP', 0)])

    def test_brightness_is_clamped(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        service.set_lamp(True, 250)
        service.set_lamp(True, -5)
        self.assertEqual(bridge.cmds, [('LAMP', 1, 100), ('LAMP', 1, 0)])

    def test_legacy_env_firmware_is_skipped(self):
        """老固件既没有 @BOOT 1 也没有 FAN 分支，白发一条只会白等 900ms"""
        bridge = FakeEnvBridge(protocol='legacy', boot_count=1)
        service = _service(bridge)

        result = service.set_fan(True)
        self.assertFalse(result['ok'])
        self.assertTrue(result.get('skipped'))
        self.assertEqual(bridge.cmds, [])

    def test_missing_env_bridge_is_skipped(self):
        service = _service()
        self.assertTrue(service.set_lamp(True, 50).get('skipped'))


class OledMessageTest(unittest.TestCase):
    """OLED 临时消息：MSG <文本>，固件 3 秒后自动恢复常驻页"""

    def test_message_is_sent_as_one_command(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        result = service.show_message('!! ALERT !!|INTRUDER', expect_reply=False)

        self.assertTrue(result['ok'])
        self.assertEqual(bridge.cmds, [('MSG', '!! ALERT !!|INTRUDER')])

    def test_fire_and_forget_skips_ack_wait(self):
        """哨兵线程不该为一条提示等 300ms 回执"""
        bridge = FakeEnvBridge()
        service = _service(bridge)

        service.show_message('ALERT', expect_reply=False)

        self.assertFalse(bridge.kwargs[0].get('expect_reply', True))

    def test_default_waits_for_ack(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        service.show_message('ALERT')

        self.assertTrue(bridge.kwargs[0].get('expect_reply', True))

    def test_whitespace_is_collapsed_and_text_truncated(self):
        """换行会在固件里被当行尾，压成空格才不会把一条命令拆成两条"""
        bridge = FakeEnvBridge()
        service = _service(bridge)

        service.show_message('A\nB\t C')
        service.show_message('X' * 100)

        self.assertEqual(bridge.cmds[0], ('MSG', 'A B C'))
        self.assertLessEqual(len(bridge.cmds[1][1]), 60)

    def test_empty_message_is_skipped(self):
        bridge = FakeEnvBridge()
        service = _service(bridge)

        self.assertTrue(service.show_message('   ').get('skipped'))
        self.assertEqual(bridge.cmds, [])

    def test_legacy_env_firmware_is_skipped(self):
        bridge = FakeEnvBridge(protocol='legacy', boot_count=1)
        service = _service(bridge)

        self.assertTrue(service.show_message('ALERT').get('skipped'))
        self.assertEqual(bridge.cmds, [])


class EnvReadbackTest(unittest.TestCase):
    """回读：板子自治改了状态，软件要跟上，而且不能再回发命令"""

    def test_fan_event_syncs_device_state(self):
        service = _service()
        dm = FakeDeviceManager()
        service.set_device_manager(dm)

        service._on_env_event(Message('EVT', 'FAN', ['ON']))

        self.assertEqual(dm.calls, [('fan', 'on', None, 'hardware')])

    def test_lamp_event_carries_brightness(self):
        service = _service()
        dm = FakeDeviceManager()
        service.set_device_manager(dm)

        service._on_env_event(Message('EVT', 'LAMP', ['ON', '60']))

        self.assertEqual(dm.calls, [('light', 'on', 60, 'hardware')])

    def test_repeated_event_does_not_write_twice(self):
        """同一状态反复上报不该把 device_status_logs 刷满"""
        service = _service()
        dm = FakeDeviceManager()
        service.set_device_manager(dm)

        service._on_env_event(Message('EVT', 'FAN', ['ON']))
        service._on_env_event(Message('EVT', 'FAN', ['ON']))

        self.assertEqual(len(dm.calls), 1)

    def test_boot_resets_fan_and_lamp(self):
        """板子复位后风扇停、灯带灭，软件状态必须跟着回零"""
        service = _service()
        dm = FakeDeviceManager()
        dm._state['fan']['on'] = True
        dm._state['light']['on'] = True
        dm._state['light']['brightness'] = 70
        service.set_device_manager(dm)

        service._on_env_event(Message('BOOT', '', ['1']))

        self.assertFalse(dm._state['fan']['on'])
        self.assertFalse(dm._state['light']['on'])

    def test_env_events_still_never_touch_door(self):
        service = _service()
        dm = FakeDeviceManager()
        service.set_device_manager(dm)

        for msg in (Message('EVT', 'FAN', ['ON']),
                    Message('EVT', 'LAMP', ['ON', '50']),
                    Message('BOOT', '', ['1']),
                    Message('EVT', 'LINK', ['LOST'])):
            service._on_env_event(msg)

        self.assertEqual([c for c in dm.calls if c[0] == 'door'], [])

    def test_manual_window_end_is_only_logged(self):
        service = _service()
        dm = FakeDeviceManager()
        service.set_device_manager(dm)

        service._on_env_event(Message('EVT', 'CTL', ['AUTO']))

        self.assertEqual(dm.calls, [])


class DispatchTest(unittest.TestCase):
    """DeviceManager -> HardwareService 的翻译层"""

    def _dm(self, hw):
        from services.device_manager import DeviceManager

        dm = DeviceManager()
        dm.set_hardware_bridge(hw)
        return dm

    def test_light_on_carries_brightness(self):
        hw = FakeHardware()
        dm = self._dm(hw)

        dm.set_device('light', 'on', 60, source='remote')

        self.assertEqual(hw.calls, [('lamp', True, 60)])

    def test_light_on_without_value_uses_current_brightness(self):
        hw = FakeHardware()
        dm = self._dm(hw)

        dm.set_device('light', 'on', source='remote')

        # set_device 在亮度为 0 时会补成 50，下发要跟着这个值走
        self.assertEqual(hw.calls, [('lamp', True, 50)])

    def test_light_off(self):
        hw = FakeHardware()
        dm = self._dm(hw)
        dm.set_device('light', 'on', 60, source='remote')

        dm.set_device('light', 'off', source='remote')

        self.assertEqual(hw.calls[-1], ('lamp', False, None))

    def test_fan_on_off(self):
        hw = FakeHardware()
        dm = self._dm(hw)

        dm.set_device('fan', 'on', 2, source='remote')
        dm.set_device('fan', 'off', source='remote')

        self.assertEqual(hw.calls, [('fan', True), ('fan', False)])

    def test_hardware_source_does_not_echo_back(self):
        """回读同步写进来的状态不能再下发，否则是 命令->事件->命令 的死循环"""
        hw = FakeHardware()
        dm = self._dm(hw)

        dm.set_device('fan', 'on', source='hardware')
        dm.set_device('light', 'on', 40, source='hardware')

        self.assertEqual(hw.calls, [])

    def test_hardware_without_env_methods_is_ignored(self):
        """只实现了门禁的旧对接层，不能因为灯/扇就抛异常"""

        class DoorOnly:
            def open_door(self):
                return {'ok': True}

            def close_door(self):
                return {'ok': True}

        dm = self._dm(DoorOnly())
        result = dm.set_device('fan', 'on', source='remote')

        self.assertNotIn('hardware', result)


if __name__ == '__main__':
    unittest.main()
