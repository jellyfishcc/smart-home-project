import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scripts.hardware_preflight import build_report, serial_inventory, running_status


class PreflightTests(unittest.TestCase):
    def report(self, ports=None, env=None, access=None, dependency=None, member=True, runtime=None):
        return build_report(env or {'SMART_HOME_DOOR_USB_SERIAL': 'door',
                                    'SMART_HOME_ENVIRONMENT_USB_SERIAL': 'env'},
                            dependency or {'importable': True, 'version': '3.5'},
                            ports if ports is not None else [SimpleNamespace(serial_number='door', device='/dev/ttyACM1'),
                                                           SimpleNamespace(serial_number='env', device='/dev/ttyACM0')],
                            {'member': member}, runtime or {'reachable': True, 'mode': 'mock'},
                            access or (lambda path, mode: True))

    def test_mapping_is_serial_based(self):
        r = self.report()
        self.assertTrue(r['inventory_ready'])
        self.assertEqual(r['boards']['door']['devices'], ['/dev/ttyACM1'])

    def test_unplugged_is_not_ready(self):
        r = self.report(ports=[])
        self.assertFalse(r['inventory_ready'])
        self.assertEqual(r['boards']['door']['state'], 'missing')

    def test_no_mapping_and_duplicate_mapping(self):
        self.assertEqual(self.report(env={'x': 'y'})['boards']['door']['state'], 'unconfigured')
        self.assertTrue(self.report(env={'SMART_HOME_DOOR_USB_SERIAL': 'x',
                                        'SMART_HOME_ENVIRONMENT_USB_SERIAL': 'x'})['duplicate_mapping'])

    def test_duplicate_usb_serial_is_ambiguous(self):
        r = self.report(ports=[SimpleNamespace(serial_number='door', device='a')]*2)
        self.assertEqual(r['boards']['door']['state'], 'ambiguous')
        self.assertFalse(r['inventory_ready'])

    def test_permission_and_membership_checked_separately(self):
        r = self.report(access=lambda path, mode: mode == os.R_OK)
        self.assertTrue(r['boards']['door']['readable'])
        self.assertFalse(r['boards']['door']['writable'])
        self.assertFalse(r['inventory_ready'])
        self.assertFalse(self.report(member=False)['inventory_ready'])

    def test_missing_dependency_is_reported(self):
        self.assertFalse(self.report(dependency={'importable': False})['inventory_ready'])
        with patch.dict('sys.modules', {'serial': None}):
            info, ports = serial_inventory()
        self.assertFalse(info['importable'])
        self.assertEqual(ports, [])

    def test_import_and_enumeration_never_construct_serial(self):
        serial = SimpleNamespace(__version__='3.5', Serial=Mock(side_effect=AssertionError('port open forbidden')))
        ports = SimpleNamespace(comports=Mock(return_value=[]))
        with patch.dict('sys.modules', {'serial': serial, 'serial.tools': SimpleNamespace(list_ports=ports)}):
            info, devices = serial_inventory()
        self.assertTrue(info['importable'])
        serial.Serial.assert_not_called()
        ports.comports.assert_called_once_with()

    def test_config_mode_not_confused_with_server_mode(self):
        r = self.report(runtime={'reachable': True, 'mode': 'hardware'})
        self.assertEqual(r['configured_mode'], 'mock')
        self.assertFalse(r['mode_matches'])
        r = self.report(runtime={'reachable': False, 'mode': 'unknown'})
        self.assertIsNone(r['mode_matches'])

    def test_new_flags_override_simulation_for_configured_mode(self):
        for flag in ('SMART_HOME_SERIAL_ENABLED', 'SMART_HOME_SERIAL_ENV_ENABLED'):
            r = self.report(env={flag: '1', 'SMART_HOME_SIMULATION_MODE': 'true'})
            self.assertEqual(r['configured_mode'], 'hardware')
        r = self.report(env={'SMART_HOME_SIMULATION_MODE': 'false'})
        self.assertEqual(r['configured_mode'], 'unavailable')

    def test_http_failure_is_unknown_not_mock(self):
        with patch('scripts.hardware_preflight.urlopen', side_effect=OSError('offline')):
            self.assertEqual(running_status('http://127.0.0.1:5000/api/hardware/status')['mode'], 'unknown')



if __name__ == '__main__':
    unittest.main()
