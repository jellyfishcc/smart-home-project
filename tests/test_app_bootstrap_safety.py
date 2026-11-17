"""Fresh-process Flask smoke tests with temporary data and forbidden real I/O."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = r'''
import os, sys, tempfile, threading, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen
from werkzeug.serving import make_server
sys.path.insert(0, sys.argv[1])
import config
with tempfile.TemporaryDirectory(prefix='merged-app-smoke-') as tmp:
    root = Path(tmp)
    config.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str(root / 'test.db')
    for key in ('UPLOAD_FOLDER', 'DETECTION_FOLDER', 'FACE_FOLDER', 'KNOWN_FACES_FOLDER', 'DATA_DIR', 'INSIGHTFACE_MODEL_ROOT', 'SENTRY_SNAPSHOT_FOLDER'):
        setattr(config, key, root / key.lower())
    config.FACE_EMBEDDINGS_PATH = root / 'unused.pkl'
    with patch('serial.Serial', side_effect=AssertionError('Real serial forbidden')), \
         patch('cv2.VideoCapture', side_effect=AssertionError('Camera forbidden')), \
         patch('services.object_detection.ObjectDetectionService', return_value=SimpleNamespace(available=False)), \
         patch('services.face_recognition_service.FaceRecognitionService', return_value=SimpleNamespace(is_trained=False)), \
         patch('services.hardware_service.HardwareService.start', return_value=False) as start:
        import app as module
        server = make_server('127.0.0.1', 0, module.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            for path in ('/', '/devices', '/access', '/detection', '/sentry', '/persons', '/analysis'):
                with urlopen(base + path) as r:
                    assert r.status == 200, path
                    assert len(r.read()) > 100, path
            with urlopen(base + '/api/hardware/status') as r:
                status = json.load(r)['data']
            if config.SERIAL_ENV_ENABLED:
                start.assert_called_once()
                assert status['mode'] == 'hardware', status
                assert module.device_manager._hardware is module.hardware_service
                assert not module.sensor_simulator._running
                assert module.sensor_simulator.get_current_reading()['temperature'] is None
                result = module.app.test_client().post('/api/devices/door/control', json={'status':'unlocked'})
                assert result.status_code == 503, result.get_json()
            else:
                start.assert_not_called()
                assert status['mode'] == 'mock', status
                assert module.sensor_simulator._running
            print('HTTP_SMOKE_OK mode=' + status['mode'] + ' pages=7')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
            module.sensor_simulator.stop()
            module.hardware_service.shutdown()
            with module.app.app_context():
                module.db.session.remove(); module.db.engine.dispose()
'''


class AppBootstrapSafetyTests(unittest.TestCase):
    def smoke(self, hardware):
        env = dict(os.environ, SMART_HOME_SIMULATION_MODE='true',
                   SMART_HOME_SERIAL_ENABLED='1' if hardware else '0',
                   SMART_HOME_SERIAL_ENV_ENABLED='1' if hardware else '0',
                   PYTHONDONTWRITEBYTECODE='1')
        root = str(Path(__file__).resolve().parents[1])
        result = subprocess.run([sys.executable, '-c', SCRIPT, root], env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('HTTP_SMOKE_OK', result.stdout)

    def test_mock_application_http_pages(self):
        self.smoke(False)

    def test_failed_hardware_bootstrap_keeps_error_hook_and_disables_simulator(self):
        self.smoke(True)
