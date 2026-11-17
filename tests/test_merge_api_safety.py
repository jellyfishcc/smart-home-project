import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from models import db, AuthorizedPerson
from services.hardware_service import HardwareService
from services.device_manager import DeviceManager
from services.sensor_simulator import SensorSimulator
import routes.api as api


class MergeAPISafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://',
                               SERIAL_ENV_ENABLED=True, SERIAL_ENABLED=True,
                               SIMULATION_MODE=True, UPLOAD_FOLDER=self.tmp.name,
                               ALLOWED_EXTENSIONS={'jpg'})
        db.init_app(self.app); self.app.register_blueprint(api.api_bp)
        self.dm = DeviceManager(self.app)
        self.hw = HardwareService(); self.hw.init_app(self.app); self.hw.set_device_manager(self.dm)
        self.dm.set_hardware_bridge(self.hw)  # intentionally offline
        self.sensor = SensorSimulator(self.app)
        for key, value in [('device_manager', self.dm), ('hardware_service', self.hw), ('sensor_simulator', self.sensor)]:
            p = patch.object(api, key, value); p.start(); self.addCleanup(p.stop)
        self.face = Mock()
        self.face.check_liveness.return_value = {'is_live': True, 'detail': 'test'}
        self.face.recognize.return_value = {'recognized': True, 'person_id': 1, 'person_name': 'test', 'detail': 'matched', 'faces_detected': 1, 'confidence': 0.9}
        self.app.config['FACE_SERVICE'] = self.face
        with self.app.app_context():
            db.create_all(); db.session.add(AuthorizedPerson(name='test', employee_id='T', is_authorized=True, is_fake=False)); db.session.commit()
        self.client = self.app.test_client()

    def upload(self):
        return self.client.post('/api/access/recognize', data={'file': (io.BytesIO(b'fake'), 'face.jpg')}).get_json()

    def test_offline_commands_return_error_not_success(self):
        for device, status in [('door','unlocked'),('fan','on'),('light','on')]:
            r = self.client.post('/api/devices/'+device+'/control', json={'status':status})
            self.assertEqual(r.status_code,503); self.assertEqual(r.get_json()['code'],1)

    def test_client_cannot_claim_hardware_source_to_bypass_dispatch(self):
        r = self.client.post('/api/devices/door/control', json={'status':'unlocked','source':'hardware'})
        self.assertEqual(r.status_code,503)
        self.assertIsNone(self.dm.get_device('door')['locked'])

    def test_fake_injection_cannot_mix_with_hardware(self):
        r = self.client.post('/api/sensor/inject', json={'temperature':40,'humidity':50,'source':'hardware'})
        self.assertEqual(r.status_code,503)
        self.assertIsNone(self.sensor.get_current_reading()['temperature'])

    def test_face_match_with_offline_board_not_granted(self):
        self.assertEqual(self.upload()['data']['access_result'],'denied')

    def test_upload_liveness_rejection_never_opens(self):
        self.face.check_liveness.return_value['is_live'] = False
        self.hw.open_door = Mock()
        self.assertEqual(self.upload()['data']['access_result'],'denied')
        self.hw.open_door.assert_not_called()

    def test_camera_liveness_rejection_never_opens(self):
        self.face.check_liveness.return_value['is_live'] = False
        self.hw.open_door = Mock()
        with patch.object(api,'capture_camera_frame',return_value={'success':True}):
            r=self.client.post('/api/access/camera').get_json()
        self.assertEqual(r['data']['access_result'],'denied'); self.hw.open_door.assert_not_called()

    def test_face_ack_text_does_not_claim_position(self):
        self.hw.open_door = Mock(return_value={'ok':True,'command':'OPEN'})
        r=self.upload()['data']; self.assertEqual(r['access_result'],'granted')
        self.assertIn('位置未确认',r['detail']); self.assertIsNone(self.dm.get_device('door')['locked'])

    def test_no_demo_temperature_rows_seeded_in_real_mode(self):
        from database import init_db
        from models import TemperatureLog
        init_db(self.app)
        with self.app.app_context(): self.assertEqual(TemperatureLog.query.count(),0)


if __name__ == '__main__': unittest.main()
