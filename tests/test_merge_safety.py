import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from services.serial_bridge import SerialBridge, resolve_usb_serial, Message
from services.hardware_service import HardwareService
from services.device_manager import DeviceManager
from services.sensor_simulator import SensorSimulator


class MergeSafetyTests(unittest.TestCase):
    def test_open_forces_no_retry_even_explicit_override(self):
        for kwargs in ({}, {'retries': 7}):
            bridge = SerialBridge(retries=2, boot_wait=0, cmd_timeout=0.001)
            port = Mock()
            bridge._serial = port
            result = bridge.send('OPEN', **kwargs)
            self.assertFalse(result.ok)
            self.assertEqual(result.attempts, 1)
            port.write.assert_called_once_with(b'OPEN\n')

    def test_queries_keep_configured_retries(self):
        for command in ('QRAIN', 'QENV'):
            bridge = SerialBridge(retries=2, boot_wait=0, cmd_timeout=0.001)
            port = Mock(); bridge._serial = port
            self.assertEqual(bridge.send(command).attempts, 3)
            self.assertEqual(port.write.call_count, 3)

    def test_serial_identity_survives_node_swap(self):
        for node in ('/dev/ttyACM0', '/dev/ttyACM1'):
            with patch('services.serial_bridge.list_serial_ports', return_value=[{'serial_number': 'door', 'device': node}]):
                self.assertEqual(resolve_usb_serial('door'), node)

    def test_identity_missing_ambiguous_never_guessed(self):
        for number, ports in [('', []), ('door', []), ('door', [{'serial_number': 'door', 'device': 'x'}]*2)]:
            with patch('services.serial_bridge.list_serial_ports', return_value=ports):
                with self.assertRaises(ValueError): resolve_usb_serial(number)

    def test_identity_failure_never_constructs_serial(self):
        bridge = SerialBridge(port='/dev/ttyACM0', usb_serial='missing')
        with patch('services.serial_bridge.resolve_usb_serial', side_effect=ValueError('board_missing')), patch('services.serial_bridge.serial.Serial') as constructor:
            self.assertFalse(bridge._try_open())
            constructor.assert_not_called()

    def test_duplicate_roles_rejected_before_start(self):
        app = Flask(__name__); app.config.update(SERIAL_ENABLED=True, SERIAL_ENV_ENABLED=True, DOOR_USB_SERIAL='x', ENVIRONMENT_USB_SERIAL='x')
        service = HardwareService(); service.init_app(app)
        with patch('services.hardware_service.SerialBridge') as bridge:
            self.assertFalse(service.start()); bridge.assert_not_called()

    def sensor(self, real=True, simulation=True):
        app = Flask(__name__); app.config.update(SERIAL_ENV_ENABLED=real, SIMULATION_MODE=simulation)
        sensor = SensorSimulator(app); sensor.set_db_logger(Mock()); sensor.set_device_manager(Mock())
        return sensor

    def test_real_source_blocks_simulator_even_when_simulation_true(self):
        sensor = self.sensor(); sensor.start()
        self.assertFalse(sensor._running)
        self.assertIsNone(sensor.get_current_reading()['temperature'])
        self.assertIn('error', sensor.inject_reading(99, 50))
        self.assertIn('error', sensor.set_temperature(99))
        sensor._db_logger.assert_not_called()

    def test_real_telemetry_does_not_run_software_fan_control(self):
        sensor = self.sensor(); sensor._device_manager.get_device.return_value = {'on': True}
        result = sensor.inject_reading(31, 50, source='hardware')
        self.assertEqual(result['source'], 'hardware')
        self.assertEqual(result['temperature'], 31)
        sensor._device_manager.auto_fan_control.assert_not_called()
        sensor._db_logger.assert_called_once()

    def test_simulation_rejects_real_telemetry(self):
        sensor = self.sensor(real=False)
        self.assertIn('error', sensor.inject_reading(31, 50, source='hardware'))
        sensor._db_logger.assert_not_called()

    def test_hardware_failure_cannot_mutate_state_to_success(self):
        dm = DeviceManager(); hw = Mock()
        hw.open_door.return_value = {'ok': False, 'error': 'timeout'}
        hw.set_fan.return_value = {'ok': False, 'error': 'missing'}
        dm.set_hardware_bridge(hw)
        self.assertIn('error', dm.set_device('door', 'unlocked'))
        self.assertIsNone(dm.get_device('door')['locked'])
        self.assertIn('error', dm.set_device('fan', 'on'))
        self.assertFalse(dm.get_device('fan')['on'])

    def test_ack_boot_timer_are_not_position_evidence(self):
        dm = DeviceManager(); service = HardwareService(); service.set_device_manager(dm)
        for message in (Message('BOOT'), Message('EVT', 'DOOR', ['OPEN']), Message('EVT', 'DOOR', ['CLOSED'])):
            service._on_event(message)
            self.assertIsNone(dm.get_device('door')['locked'])
        service._auto_close_fire()
        self.assertIsNone(dm.get_device('door')['locked'])

    def test_mode_config_selects_separate_databases(self):
        import runpy
        path = str(Path(__file__).resolve().parents[1]/'config.py')
        with patch.dict(os.environ, {'SMART_HOME_SERIAL_ENV_ENABLED': '0', 'SMART_HOME_SIMULATION_MODE': 'true'}):
            mock = runpy.run_path(path)
        with patch.dict(os.environ, {'SMART_HOME_SERIAL_ENV_ENABLED': '1', 'SMART_HOME_SIMULATION_MODE': 'true'}):
            real = runpy.run_path(path)
        self.assertEqual(real['SENSOR_SOURCE'], 'hardware')
        self.assertNotEqual(mock['SQLALCHEMY_DATABASE_URI'], real['SQLALCHEMY_DATABASE_URI'])


if __name__ == '__main__': unittest.main()
