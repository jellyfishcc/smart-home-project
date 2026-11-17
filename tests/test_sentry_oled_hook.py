"""
哨兵 -> 环境板 OLED 的联动测试（不需要硬件、不需要 Flask app）。

协议侧只关心一件事：告警时把一条固定 ASCII 提示交给 HardwareService，
并且**不**等回执——巡检线程不能被一条屏幕提示拖住。

跑起来：python tests/test_sentry_oled_hook.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.sentry_service import SentryService


class StubHardware:
    """只记录 show_message 收到什么"""

    def __init__(self, boom=False):
        self.calls = []
        self.boom = boom

    def show_message(self, text, expect_reply=True):
        self.calls.append((text, expect_reply))
        if self.boom:
            raise RuntimeError('串口已断开')
        return {'ok': True}


class SentryOledHookTest(unittest.TestCase):

    def test_alarm_pushes_message_without_waiting_for_ack(self):
        sentry = SentryService()
        hardware = StubHardware()
        sentry.set_hardware_service(hardware)

        sentry._show_alarm_message()

        self.assertEqual(hardware.calls, [('WARNING', False)])

    def test_without_hardware_is_a_noop(self):
        """纯软件模式（没插板）不能因为这条提示报错"""
        SentryService()._show_alarm_message()

    def test_hardware_failure_is_swallowed(self):
        """屏幕提示失败不该把告警主流程带崩"""
        sentry = SentryService()
        sentry.set_hardware_service(StubHardware(boom=True))

        with self.assertLogs('services.sentry_service', level='ERROR'):
            sentry._show_alarm_message()


if __name__ == '__main__':
    unittest.main(verbosity=2)
