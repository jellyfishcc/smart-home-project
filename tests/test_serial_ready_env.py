import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch
from services.serial_bridge import SerialBridge, parse_line


class FakePort:
    def __init__(self):
        self.lines = queue.Queue()
        self.writes = []
        self.response = b'@DATA ENV 253 612 1\n'

    def readline(self):
        try: return self.lines.get(timeout=0.01)
        except queue.Empty: return b''

    def write(self, data):
        self.writes.append(data)
        if self.response: self.lines.put(self.response)

    def flush(self): pass
    def close(self): pass
    def reset_input_buffer(self): pass


class ReadyTests(unittest.TestCase):
    def start_fake(self, boot_wait=0.3):
        port = FakePort()
        gate = threading.Event()
        entered = threading.Event()
        def construct(**kwargs):
            entered.set()
            gate.wait(1)
            return port
        bridge = SerialBridge(usb_serial='fake', boot_wait=boot_wait, cmd_timeout=0.04,
                              reconnect_delay=0, heartbeat_interval=0, rain_poll_interval=0)
        patches = [patch('services.serial_bridge.resolve_usb_serial', return_value='FAKE'),
                   patch('services.serial_bridge.serial.Serial', side_effect=construct)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(bridge.stop)
        self.addCleanup(gate.set)
        bridge.start()
        self.assertTrue(entered.wait(1))
        return bridge, port, gate

    def send_thread(self, bridge, name):
        results = []
        thread = threading.Thread(target=lambda: results.append(bridge.send(name)))
        thread.start()
        self.addCleanup(lambda: thread.join(2))
        return thread, results

    def test_delayed_open_then_banner_precedes_first_qenv(self):
        bridge, port, gate = self.start_fake()
        thread, results = self.send_thread(bridge, 'QENV')
        time.sleep(0.03)
        self.assertTrue(thread.is_alive()); self.assertEqual(port.writes, [])
        gate.set()
        time.sleep(0.03)
        self.assertEqual(port.writes, [])
        port.lines.put(b'@BOOT 1\n')
        thread.join(1)
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(results[0].attempts, 1)
        self.assertEqual(port.writes, [b'QENV\n'])

    def test_open_ready_wait_never_retries_lost_ack(self):
        bridge, port, gate = self.start_fake()
        port.response = None
        thread, results = self.send_thread(bridge, 'OPEN')
        time.sleep(0.02); self.assertEqual(port.writes, [])
        gate.set(); port.lines.put(b'Ready\n')
        thread.join(1)
        self.assertFalse(results[0].ok)
        self.assertEqual(port.writes, [b'OPEN\n'])
        self.assertEqual(results[0].attempts, 1)

    def test_no_banner_falls_back_from_actual_open_time(self):
        bridge, port, gate = self.start_fake(boot_wait=0.12)
        thread, results = self.send_thread(bridge, 'QENV')
        time.sleep(0.15); self.assertEqual(port.writes, [])
        gate.set(); time.sleep(0.04); self.assertEqual(port.writes, [])
        thread.join(1)
        self.assertTrue(results[0].ok)

    def test_reset_during_written_command_is_explicit_failure(self):
        bridge, port, gate = self.start_fake()
        port.response = b'@BOOT 1\n'
        gate.set(); port.lines.put(b'@BOOT 1\n')
        result = bridge.send('QENV')
        self.assertFalse(result.ok)
        self.assertEqual(result.error, 'board_reset_command_interrupted')
        self.assertEqual(port.writes, [b'QENV\n'])

    def test_transport_ready_timeout_writes_nothing(self):
        bridge = SerialBridge(boot_wait=0, reconnect_delay=0)
        bridge._running = True
        result = bridge.send('OPEN')
        self.assertFalse(result.ok); self.assertEqual(result.attempts, 0)
        self.assertEqual(bridge.status()['counters']['tx_cmds'], 0)

    def test_invalid_and_valid_query_and_cache(self):
        bridge = SerialBridge(boot_wait=0)
        port = Mock(); bridge._serial = port
        for line, expected in [('@DATA ENV 250 500 0', None), ('@DATA ENV 253 612 1', (25.3, 61.2))]:
            port.write.side_effect = lambda data: bridge._handle_raw(line.encode())
            self.assertEqual(bridge.query_env(), expected)
            self.assertEqual(bridge.reported['env_valid'], expected is not None)
            self.assertEqual(bridge.reported['env_raw'], line.split()[2:])
            if expected is None: self.assertIsNone(bridge.reported['env'])

    def test_invalid_env_clears_ui_and_api_reading_without_database_insert(self):
        from flask import Flask
        from models import db, TemperatureLog
        from services.hardware_service import HardwareService
        from services.sensor_simulator import SensorSimulator
        app = Flask(__name__)
        app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SERIAL_ENV_ENABLED=True, SIMULATION_MODE=True)
        db.init_app(app)
        import routes.api as api
        app.register_blueprint(api.api_bp)
        sensor = SensorSimulator(app)
        def log(t, h, fan):
            db.session.add(TemperatureLog(temperature=t, humidity=h, fan_activated=False))
            db.session.commit()
        sensor.set_db_logger(log)
        service = HardwareService(); service.init_app(app)
        socket = Mock(); service.set_socketio(socket)
        with app.app_context(), patch('services.sensor_simulator.sensor_simulator', sensor):
            db.create_all()
            service._on_data(parse_line('@DATA ENV 253 612 1'))
            self.assertEqual(TemperatureLog.query.count(), 1)
            service._on_data(parse_line('@DATA ENV 250 500 0'))
            self.assertEqual(TemperatureLog.query.count(), 1)
            self.assertIsNone(sensor.get_current_reading()['temperature'])
            self.assertFalse(sensor.get_current_reading()['available'])
            self.assertEqual(sensor.get_current_reading()['source'], 'hardware')
            self.assertIsNone(socket.emit.call_args.args[1]['temperature'])
            self.assertFalse(service.status()['env']['valid'])
            with patch.object(api, 'sensor_simulator', sensor):
                response = app.test_client().get('/api/sensor/current')
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.get_json()['data']['temperature'])
                self.assertFalse(response.get_json()['data']['available'])
            db.session.remove(); db.engine.dispose()
