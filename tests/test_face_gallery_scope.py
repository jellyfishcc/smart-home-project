import io
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
import numpy as np
from flask import Flask
from models import db, AuthorizedPerson
from services.face_gallery_scope import gallery_scope, person_lookup, person_token
from services.insightface_recognition_service import FaceRecognitionService
import routes.api as api


class GalleryScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.backend=Mock()
        self.vector=np.zeros(512,dtype=np.float32);self.vector[0]=1
        self.backend.extract_faces.return_value=[SimpleNamespace(embedding=self.vector)]
        self.app,self.service=self.make_app('hardware.db')
        self.client=self.app.test_client()

    def make_app(self,name):
        app=Flask(name);uri='sqlite:///'+str(self.root/name)
        app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI=uri,UPLOAD_FOLDER=str(self.root/'uploads'),ALLOWED_EXTENSIONS={'jpg'})
        db.init_app(app);app.register_blueprint(api.api_bp)
        with app.app_context():
            db.create_all()
            for i in (1,2,3,4):db.session.add(AuthorizedPerson(id=i,name='Person'+str(i),employee_id='E'+str(i)))
            db.session.commit()
        identity,path=gallery_scope(uri)
        service=FaceRecognitionService(known_faces_dir=self.root/(name+'faces'),data_dir=self.root,database_uri=uri,person_lookup=person_lookup(app,identity),backend=self.backend)
        app.config['FACE_SERVICE']=service
        def dispose():
            with app.app_context():db.session.remove();db.engine.dispose()
        self.addCleanup(dispose)
        return app,service

    def register(self,person=1,client=None):
        return (client or self.client).post('/api/persons/%s/register-face'%person,data={'file':(io.BytesIO(b'photo'), 'face.jpg')}).get_json()

    def test_registration_success_is_current_db_gallery_and_memory(self):
        self.assertEqual(self.register()['code'],0)
        self.assertTrue(self.service.recognize('probe.jpg')['recognized'])
        self.assertEqual(self.service.registration_status(1),'face_registered')
        with self.app.app_context():
            p=db.session.get(AuthorizedPerson,1)
            self.assertEqual(p.face_encoding_path,str(self.service.embeddings_path))
            self.assertTrue(Path(p.face_image_path).is_file())
        payload=pickle.loads(self.service.embeddings_path.read_bytes())
        self.assertEqual(payload['database_identity'],self.service.database_identity)
        self.assertEqual(len(payload['records']),1)

    def test_database_a_id4_cannot_be_database_b_id4(self):
        self.register(4)
        appb,serviceb=self.make_app('normal.db')
        self.assertNotEqual(self.service.embeddings_path,serviceb.embeddings_path)
        self.assertEqual(serviceb.records,[])
        serviceb.embeddings_path.write_bytes(self.service.embeddings_path.read_bytes())
        other=FaceRecognitionService(known_faces_dir=self.root/'otherfaces',database_uri=appb.config['SQLALCHEMY_DATABASE_URI'],person_lookup=serviceb.person_lookup,backend=self.backend)
        self.assertFalse(other.recognize('probe.jpg')['recognized'])
        self.assertTrue(other._gallery_rejected)

    def test_bare_legacy_gallery_is_never_loaded(self):
        (self.root/'face_embeddings.pkl').write_bytes(pickle.dumps({'records':[{'person_id':4,'embedding':self.vector}]}))
        appb,serviceb=self.make_app('new.db')
        self.assertEqual(serviceb.records,[])

    def test_stale_best_match_does_not_hide_legal_candidate(self):
        self.register()
        self.service.records.insert(0,dict(self.service.records[0],person_id=7))
        result=self.service.recognize('probe.jpg')
        self.assertTrue(result['recognized']);self.assertEqual(result['person_id'],1)

    def test_reused_id_with_new_token_excluded(self):
        self.register()
        with self.app.app_context():
            p=db.session.get(AuthorizedPerson,1);p.employee_id='DIFFERENT_IDENTITY';db.session.commit()
        self.assertFalse(self.service.recognize('probe.jpg')['recognized'])

    def test_duplicate_registration_rejected(self):
        self.register()
        self.assertEqual(self.register(2)['code'],1)
        self.assertEqual(len(self.service.records),1)
        with self.app.app_context():self.assertIsNone(db.session.get(AuthorizedPerson,2).face_encoding_path)
        self.assertEqual(self.service.registration_status(2),'face_registration_failed')

    def test_duplicate_existing_records_deny_instead_of_first_win(self):
        self.register()
        with self.app.app_context():
            one=db.session.get(AuthorizedPerson,1);two=db.session.get(AuthorizedPerson,2)
            two.face_image_path=one.face_image_path;two.face_encoding_path=one.face_encoding_path;db.session.commit()
            record=dict(self.service.records[0],person_id=2,person_token=person_token(two))
        self.service.records.append(record)
        result=self.service.recognize('probe.jpg')
        self.assertFalse(result['recognized']);self.assertIn('冲突',result['detail'])

    def test_extraction_failure_marks_status_without_fake_path(self):
        self.backend.extract_faces.return_value=[]
        self.assertEqual(self.register()['code'],1)
        p=self.client.get('/api/persons/1').get_json()['data']
        self.assertEqual(p['face_registration_status'],'face_registration_failed')
        self.assertIsNone(p['face_image_path'])
        with self.app.app_context():self.assertIsNone(db.session.get(AuthorizedPerson,1).face_encoding_path)
        self.assertFalse(self.service.recognize('probe.jpg')['recognized'])

    def test_save_failure_rolls_back_memory_and_database_paths(self):
        with patch.object(self.service,'_save_embeddings',side_effect=OSError('disk full')):
            self.assertEqual(self.register()['code'],1)
        self.assertEqual(self.service.records,[])
        with self.app.app_context():self.assertIsNone(db.session.get(AuthorizedPerson,1).face_encoding_path)

    def test_switch_config_invalidates_old_in_memory_gallery(self):
        self.register()
        self.app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///'+str(self.root/'different.db')
        self.assertFalse(self.service.recognize('probe.jpg')['recognized'])

    def test_delete_removes_embedding_but_keeps_photo(self):
        self.register();sample=Path(self.service.records[0]['sample_path'])
        self.assertEqual(self.client.delete('/api/persons/1').status_code,200)
        self.assertEqual(self.service.records,[]);self.assertTrue(sample.exists())

    def test_person_creation_is_not_face_registration(self):
        p=self.client.post('/api/persons',json={'name':'New','employee_id':'NEW'}).get_json()['data']
        self.assertEqual(p['person_status'],'person_created')
        self.assertEqual(p['face_registration_status'],'face_not_registered')

    def test_reload_loads_current_scoped_gallery(self):
        self.register()
        restored=FaceRecognitionService(known_faces_dir=self.root/'reloadfaces',database_uri=self.app.config['SQLALCHEMY_DATABASE_URI'],person_lookup=self.service.person_lookup,backend=self.backend)
        self.assertEqual(restored.registration_status(1),'face_registered')
        self.assertEqual(restored.recognize('probe.jpg')['person_id'],1)

    def test_failed_status_survives_reload(self):
        self.backend.extract_faces.return_value=[]
        self.register()
        restored=FaceRecognitionService(known_faces_dir=self.root/'reloadfaces',database_uri=self.app.config['SQLALCHEMY_DATABASE_URI'],person_lookup=self.service.person_lookup,backend=self.backend)
        self.assertEqual(restored.registration_status(1),'face_registration_failed')

    def test_pending_registration_also_blocks_duplicate_identity(self):
        photo=self.root/'pending.jpg';photo.write_bytes(b'photo')
        self.assertTrue(self.service.register_face(1,photo)['success'])
        # DB registration paths have not been committed by the caller yet.
        self.assertFalse(self.service.register_face(2,photo)['success'])
        self.assertFalse(self.service.recognize('probe.jpg')['recognized'])
