"""
Smart home face recognition service backed by InsightFace embeddings.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import pickle
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from services.insightface_backend import InsightFaceBackend

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FaceRecognitionService:
    """Face recognition service used by the Flask API routes."""

    def __init__(
        self,
        known_faces_dir='known_faces',
        data_dir='data',
        confidence_threshold=0.45,
        backend=None,
        embeddings_path=None,
        model_name='buffalo_l',
        model_root=None,
        det_size=(320, 320),
        database_uri=None,
        person_lookup=None,
    ):
        self.known_faces_dir = Path(known_faces_dir)
        self.data_dir = Path(data_dir)
        self.confidence_threshold = float(confidence_threshold)
        self.embeddings_path = Path(embeddings_path) if embeddings_path else self.data_dir / 'face_embeddings.pkl'
        self.database_identity = None
        self.person_lookup = person_lookup
        self._gallery_lock = threading.RLock()
        self.registration_failures = {}
        self._match_error = None
        self._gallery_rejected = False
        if database_uri is not None:
            from services.face_gallery_scope import gallery_scope
            self.database_identity, self.embeddings_path = gallery_scope(database_uri)
            if person_lookup is None:
                raise ValueError('Scoped gallery requires a current-database person lookup')

        model_root = Path(model_root) if model_root is not None else PROJECT_ROOT / 'models'
        self.backend = backend or InsightFaceBackend(
            model_name=model_name,
            model_root=model_root,
            det_size=det_size,
        )

        self.known_faces_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.records = self._load_embeddings()
        self.is_trained = len(self.records) > 0

    def _embedding_path(self):
        return self.embeddings_path

    def _load_embeddings(self):
        path = self._embedding_path()
        if not path.exists():
            return []

        try:
            with path.open('rb') as f:
                payload = pickle.load(f)
        except Exception as exc:
            self._gallery_rejected = self.database_identity is not None
            logger.warning('[FaceRec] Failed to load embedding store: %s', exc)
            return []

        if self.database_identity is not None:
            if not isinstance(payload, dict) or payload.get('database_identity') != self.database_identity:
                self._gallery_rejected = True
                logger.warning('[FaceRec] gallery database identity mismatch; refusing records')
                return []
            self.registration_failures = payload.get('registration_failures', {})
        records = payload.get('records', []) if isinstance(payload, dict) else payload
        loaded = []
        for record in records:
            try:
                loaded.append({
                    'person_id': int(record['person_id']),
                    'person_token': record.get('person_token'),
                    'person_name': record.get('person_name'),
                    'embedding': self._normalize(record['embedding']),
                    'sample_path': record.get('sample_path'),
                    'created_at': record.get('created_at'),
                })
            except Exception as exc:
                logger.warning('[FaceRec] Skipped invalid embedding record: %s', exc)
        return loaded

    def _save_embeddings(self):
        self._embedding_path().parent.mkdir(parents=True, exist_ok=True)
        payload = {'records': self.records, 'database_identity': self.database_identity,
                   'registration_failures': self.registration_failures}
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self._embedding_path().parent, delete=False) as f:
                temp_path = f.name
                pickle.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self._embedding_path())
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        self.is_trained = len(self.records) > 0

    def _valid_records(self, require_registered=True):
        if self.database_identity is None:
            return list(self.records)  # Standalone/offline compatibility only.
        valid = []
        for record in self.records:
            person = self.person_lookup(record['person_id'])
            if person and person['token'] == record.get('person_token') and (person['registered'] or not require_registered):
                valid.append(record)
            else:
                logger.warning('[FaceRec] stale/orphan person binding excluded: id=%s', record['person_id'])
        return valid

    def registration_status(self, person_id):
        with self._gallery_lock:
            if any(r['person_id'] == person_id for r in self._valid_records()):
                return 'face_registered'
            if str(person_id) in self.registration_failures:
                return 'face_registration_failed'
            return 'face_not_registered'

    def _normalize(self, embedding):
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError('face embedding cannot be a zero vector')
        return vector / norm

    def _best_match(self, probe_embedding):
        with self._gallery_lock:
            self._match_error = None
            probe = self._normalize(probe_embedding)
            candidates = [(float(np.dot(probe, r['embedding'])), r) for r in self._valid_records()]
            if not candidates:
                return None, None
            candidates.sort(key=lambda item: item[0], reverse=True)
            score, best = candidates[0]
            for other_score, other in candidates[1:]:
                if other['person_id'] != best['person_id'] and (
                    float(np.dot(best['embedding'], other['embedding'])) >= 0.9999 or
                    (score >= self.confidence_threshold and abs(score - other_score) <= 1e-6)):
                    logger.warning('[FaceRec] ambiguous/duplicate identities: %s and %s', best['person_id'], other['person_id'])
                    self._match_error = '人脸库存在重复或同分身份冲突，拒绝自动确认人员'
                    return None, None
            return best, score

    def detect_faces(self, image):
        """Compatibility wrapper for older callers that expected Haar boxes."""
        if not isinstance(image, (str, Path)):
            return [], None

        try:
            faces = self.backend.extract_faces(image)
        except Exception:
            return [], None

        boxes = []
        for face in faces:
            if not face.bbox or len(face.bbox) < 4:
                continue
            x1, y1, x2, y2 = [int(round(value)) for value in face.bbox[:4]]
            boxes.append([x1, y1, max(0, x2 - x1), max(0, y2 - y1)])
        return np.asarray(boxes, dtype=np.int32), None

    def register_face(self, person_id, image_path, person_name=None):
        with self._gallery_lock:
            before = list(self.records)
            try:
                if self._gallery_rejected:
                    raise ValueError('gallery 数据库标识不匹配，必须先处理完整性问题')
                if self.database_identity is not None and self.person_lookup(person_id) is None:
                    raise ValueError('当前数据库不存在此人员，或数据库配置已切换')
                if not Path(image_path).is_file():
                    raise ValueError('注册照片不存在')
                result = self._register_face(person_id, image_path, person_name)
                if result['success']:
                    self.registration_failures.pop(str(person_id), None)
                else:
                    self.registration_failures[str(person_id)] = result['message']
                self._save_embeddings()
            except Exception as exc:
                self.records = before
                self.is_trained = bool(before)
                result = {'success': False, 'message': '人脸注册失败，需要重新录入：' + str(exc), 'face_count': 0}
                self.registration_failures[str(person_id)] = result['message']
            result['registration_status'] = 'face_registered' if result['success'] else 'face_registration_failed'
            return result

    def _register_face(self, person_id, image_path, person_name=None):
        """
        Register one face embedding for a person.
        Returns: {'success': bool, 'message': str, 'face_count': int}
        """
        try:
            faces = self.backend.extract_faces(image_path)
        except Exception as exc:
            logger.warning('[FaceRec] Face extraction failed during registration: %s', exc)
            return {
                'success': False,
                'message': '未检测到人脸，请确保照片中有清晰的人脸',
                'face_count': 0,
            }

        if len(faces) == 0:
            return {
                'success': False,
                'message': '未检测到人脸，请确保照片中有清晰的人脸',
                'face_count': 0,
            }

        if len(faces) > 1:
            return {
                'success': False,
                'message': f'检测到 {len(faces)} 张人脸，请使用单人照片',
                'face_count': len(faces),
            }

        embedding = self._normalize(faces[0].embedding)
        for record in self._valid_records(require_registered=False):
            if record['person_id'] != int(person_id) and float(np.dot(embedding, record['embedding'])) >= 0.9999:
                logger.warning('[FaceRec] duplicate registration conflicts with id=%s', record['person_id'])
                return {'success': False, 'message': '人脸与另一人员重复，请先处理身份冲突', 'face_count': 1}

        sample_path = self._copy_sample_image(person_id, image_path)
        self.records.append({
            'person_id': int(person_id),
            'person_token': self.person_lookup(person_id)['token'] if self.database_identity else None,
            'person_name': person_name,
            'embedding': embedding,
            'sample_path': sample_path,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })

        return {
            'success': True,
            'message': f'人脸注册成功 (人员: {person_name or person_id})',
            'face_count': 1,
            'sample_path': sample_path,
        }

    def _copy_sample_image(self, person_id, image_path):
        person_dir = self.known_faces_dir / f'person_{person_id}'
        person_dir.mkdir(parents=True, exist_ok=True)

        source = Path(image_path)
        suffix = source.suffix.lower() or '.jpg'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        sample_path = person_dir / f'{timestamp}{suffix}'
        shutil.copy2(source, sample_path)
        return str(sample_path)

    def recognize(self, image_path):
        """
        Recognize one face from an uploaded image.
        Keeps the legacy response keys used by the route layer.
        """
        try:
            faces = self.backend.extract_faces(image_path)
        except Exception as exc:
            logger.warning('[FaceRec] Face extraction failed during recognition: %s', exc)
            return {
                'recognized': False,
                'person_id': None,
                'person_name': None,
                'confidence': None,
                'faces_detected': 0,
                'result': 'unknown',
                'detail': '未检测到人脸',
            }

        if len(faces) == 0:
            return {
                'recognized': False,
                'person_id': None,
                'person_name': None,
                'confidence': None,
                'faces_detected': 0,
                'result': 'unknown',
                'detail': '未检测到人脸',
            }

        if len(faces) > 1:
            return {
                'recognized': False,
                'person_id': None,
                'person_name': None,
                'confidence': None,
                'faces_detected': len(faces),
                'result': 'denied',
                'detail': '检测到多张人脸，请使用单人照片',
            }

        if not self.records:
            return {
                'recognized': False,
                'person_id': None,
                'person_name': None,
                'confidence': None,
                'faces_detected': 1,
                'result': 'unknown',
                'detail': '人脸模型未训练，请先注册人脸',
            }

        best_record, similarity = self._best_match(faces[0].embedding)
        if best_record is None or similarity is None:
            return {
                'recognized': False,
                'person_id': None,
                'person_name': None,
                'confidence': None,
                'faces_detected': 1,
                'result': 'unknown',
                'detail': self._match_error or '当前数据库没有合法人脸注册记录，请完成人脸注册',
            }

        confidence = round(float(similarity), 4)
        if similarity >= self.confidence_threshold:
            return {
                'recognized': True,
                'person_id': best_record['person_id'],
                'person_name': best_record.get('person_name'),
                'confidence': confidence,
                'faces_detected': 1,
                'result': 'granted',
                'detail': f'识别成功 (相似度: {confidence})',
            }

        return {
            'recognized': False,
            'person_id': best_record['person_id'],
            'person_name': best_record.get('person_name'),
            'confidence': confidence,
            'faces_detected': 1,
            'result': 'denied',
            'detail': f'识别失败，未授权人员 (相似度: {confidence})',
        }

    def check_liveness(self, image_path):
        """
        Simple liveness heuristic based on image sharpness, color, and lighting.
        """
        img = self._read_image(image_path)
        if img is None:
            return {'is_live': False, 'score': 0, 'detail': '无法读取图片'}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1].mean()
        brightness = gray.mean()
        brightness_std = gray.std()

        score = 0
        detail_parts = []

        if laplacian_var > 30:
            score += 30
            detail_parts.append(f'清晰度良好({laplacian_var:.1f})')
        else:
            detail_parts.append(f'清晰度偏低({laplacian_var:.1f})')

        if saturation > 40:
            score += 30
            detail_parts.append(f'色彩正常({saturation:.1f})')
        else:
            detail_parts.append(f'色彩偏灰({saturation:.1f})')

        if 50 < brightness < 220:
            score += 20
            detail_parts.append(f'光照正常({brightness:.1f})')
        else:
            detail_parts.append(f'光照异常({brightness:.1f})')

        if brightness_std > 30:
            score += 20
            detail_parts.append(f'光照分布合理({brightness_std:.1f})')
        else:
            detail_parts.append(f'光照过于均匀({brightness_std:.1f})')

        return {
            'is_live': score >= 60,
            'score': score,
            'detail': '; '.join(detail_parts),
        }

    @staticmethod
    def _read_image(image_path):
        image_bytes = np.fromfile(Path(image_path), dtype=np.uint8)
        return cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)

    def get_registered_persons(self):
        """Return registered person IDs."""
        return sorted({record['person_id'] for record in self._valid_records()})

    def remove_person(self, person_id):
        """Remove current-gallery identity; preserve original photos for audit."""
        with self._gallery_lock:
            if self.database_identity and self.person_lookup(person_id) is None:
                raise ValueError('人员不属于当前数据库或数据库已切换')
            before = self.records
            self.records = [r for r in self.records if r['person_id'] != int(person_id)]
            try:
                self._save_embeddings()
            except Exception:
                self.records = before
                raise
            return True
