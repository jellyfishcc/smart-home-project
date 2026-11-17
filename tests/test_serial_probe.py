import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock, call
from scripts import serial_probe as probe


class SerialProbeTests(unittest.TestCase):
    def test_identity_passed_to_bridge(self):
        args = SimpleNamespace(port='/dev/ttyACM0', usb_serial='door-id', baud=9600, raw=False)
        with patch.object(probe, 'SerialBridge') as bridge:
            probe.build_bridge(args)
            self.assertEqual(bridge.call_args.kwargs['usb_serial'], 'door-id')
            self.assertEqual(bridge.call_args.kwargs['heartbeat_interval'], 0)
            bridge.return_value.start.assert_not_called()

    def test_build_without_identity_rejected_before_constructing(self):
        for identity in ('', '  '):
            args = SimpleNamespace(port='/dev/ttyACM0', usb_serial=identity, baud=9600)
            with patch.object(probe, 'SerialBridge') as bridge:
                with self.assertRaisesRegex(ValueError, 'usb_serial_mapping_required'):
                    probe.build_bridge(args)
                bridge.assert_not_called()

    def test_cli_missing_identity_does_not_open_or_send(self):
        with patch('sys.argv', ['serial_probe.py', '--port', '/dev/ttyACM0', '--send', 'QRAIN']), patch.object(probe, 'SerialBridge') as bridge:
            with self.assertRaises(SystemExit) as result:
                probe.main()
            self.assertEqual(result.exception.code, 2)
            bridge.assert_not_called()

    def test_list_without_identity_is_read_only(self):
        with patch('sys.argv', ['serial_probe.py', '--list', '--post-boot-wait', '2']), patch.object(probe, 'PYSERIAL_AVAILABLE', True), patch.object(probe, 'list_serial_ports', return_value=[{'device':'/dev/ttyACM1', 'serial_number':'env-id', 'description':'test'}]), patch.object(probe, 'SerialBridge') as bridge, patch('serial.Serial') as serial:
            self.assertEqual(probe.main(), 0)
            bridge.assert_not_called()
            serial.assert_not_called()

    def test_cli_passes_explicit_identity(self):
        with patch('sys.argv', ['serial_probe.py', '--usb-serial', 'env-id', '--send', 'QENV']), patch.object(probe, 'PYSERIAL_AVAILABLE', True), patch.object(probe, 'SerialBridge') as bridge:
            bridge.return_value.start.return_value = False
            self.assertEqual(probe.main(), 1)
            self.assertEqual(bridge.call_args.kwargs['usb_serial'], 'env-id')
            self.assertEqual(bridge.call_args.kwargs['boot_wait'], probe.config.SERIAL_ENV_BOOT_WAIT)
            bridge.return_value.send.assert_not_called()

    def run_probe(self, extra, ready=True):
        bridge = Mock()
        bridge._wait_boot.return_value = object() if ready else None
        bridge.send.return_value = SimpleNamespace(ok=True, attempts=1, elapsed=0, reply=None)
        events = Mock()
        events.attach_mock(bridge._wait_boot, 'ready')
        events.attach_mock(bridge.send, 'send')
        with patch('sys.argv', ['serial_probe.py', '--usb-serial', 'test', '--send', 'OPEN'] + extra), patch.object(probe, 'PYSERIAL_AVAILABLE', True), patch.object(probe, 'build_bridge', return_value=bridge), patch.object(probe.time, 'sleep') as sleep:
            events.attach_mock(sleep, 'sleep')
            result = probe.main()
        bridge.stop.assert_called_once()
        return result, events.mock_calls, bridge

    def test_post_boot_wait_order_and_single_open(self):
        result, calls, bridge = self.run_probe(['--post-boot-wait', '2'])
        self.assertEqual(result, 0)
        self.assertEqual(calls, [call.ready(), call.sleep(2.0), call.send('OPEN')])
        bridge.send.assert_called_once_with('OPEN')

    def test_default_adds_no_wait(self):
        result, calls, bridge = self.run_probe([])
        self.assertEqual(result, 0)
        self.assertEqual(calls, [call.send('OPEN')])

    def test_failed_ready_does_not_sleep_or_send(self):
        result, calls, bridge = self.run_probe(['--post-boot-wait', '2'], ready=False)
        self.assertEqual(result, 1)
        self.assertEqual(calls, [call.ready()])
        bridge.send.assert_not_called()

    def test_invalid_wait_rejected_before_bridge(self):
        for value in ('-1', 'nan', 'inf'):
            with patch('sys.argv', ['serial_probe.py', '--usb-serial', 'test', '--post-boot-wait', value]), patch.object(probe, 'SerialBridge') as bridge:
                with self.assertRaises(SystemExit): probe.main()
                bridge.assert_not_called()


if __name__ == '__main__':
    unittest.main()
