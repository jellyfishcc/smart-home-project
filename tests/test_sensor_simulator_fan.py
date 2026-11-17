"""
温度不再驱动风扇的回归测试。

背景：模拟器每分钟生成 20~33℃ 的温度，正好反复穿越 30℃ 阈值，
之前会把风扇开开关关；现在温度只用于显示与日志，执行器状态只由
「手动控制 / 环境板固件按真实 DHT11 自治」决定。

跑起来：python tests/test_sensor_simulator_fan.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.sensor_simulator import SensorSimulator


class FakeDeviceManager:
    """只记下有没有被要求改设备"""

    def __init__(self, fan_on=False):
        self.calls = []
        self._state = {'fan': {'on': fan_on}}

    def get_device(self, name):
        return dict(self._state.get(name, {}))

    def set_device(self, device, status, value=None, source='manual', **kwargs):
        self.calls.append((device, status, value, source))
        if device == 'fan':
            self._state['fan']['on'] = (status == 'on')

    def auto_fan_control(self, temperature, threshold=28.0):
        # 老路径若还被调用，这里会记下来，测试直接失败
        self.calls.append(('auto_fan', temperature, threshold))


class FanNotDrivenByTemperatureTest(unittest.TestCase):

    def _sim(self, dm):
        sim = SensorSimulator()
        sim.set_device_manager(dm)
        return sim

    def test_hot_reading_does_not_touch_fan(self):
        dm = FakeDeviceManager(fan_on=False)
        sim = self._sim(dm)

        sim.inject_reading(35.0, 40.0)

        self.assertEqual(dm.calls, [])
        self.assertFalse(dm.get_device('fan')['on'])

    def test_cold_reading_does_not_touch_fan(self):
        """反过来也不能因为温度低就把正在转的风扇关掉"""
        dm = FakeDeviceManager(fan_on=True)
        sim = self._sim(dm)

        sim.inject_reading(18.0, 60.0)

        self.assertEqual(dm.calls, [])
        self.assertTrue(dm.get_device('fan')['on'])

    def test_fan_flag_reports_real_state(self):
        dm = FakeDeviceManager(fan_on=True)
        sim = self._sim(dm)

        sim.inject_reading(35.0, 40.0)
        self.assertTrue(sim.get_current_reading()['fan_activated'])

        dm.set_device('fan', 'off')
        sim.inject_reading(35.0, 40.0)
        self.assertFalse(sim.get_current_reading()['fan_activated'])

    def test_logged_flag_is_actual_state_not_threshold(self):
        logged = []
        dm = FakeDeviceManager(fan_on=False)
        sim = self._sim(dm)
        sim.set_db_logger(lambda t, h, fan: logged.append((t, h, fan)))

        sim.inject_reading(31.5, 45.0)

        self.assertEqual(logged, [(31.5, 45.0, False)])

    def test_no_device_manager_is_safe(self):
        sim = SensorSimulator()
        sim.inject_reading(30.0)
        self.assertFalse(sim.get_current_reading()['fan_activated'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
