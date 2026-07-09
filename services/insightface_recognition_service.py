"""
Smart home face recognition service backed by InsightFace embeddings.
"""
from __future__ import annotations

import logging
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
    ):
        self.known_faces_dir = Path(known_faces_dir)
        self.data_dir = Path(data_dir)
        self.confidence_threshold = float(confidence_threshold)
        self.embeddings_path = Path(embeddings_path) if embeddings_path else self.data_dir / 'face_embeddings.pkl'
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
            logger.warning('[FaceRec] Failed to load embedding store: %s', exc)
            return []

        records = payload.get('records', []) if isinstance(payload, dict) else payload
        loaded = []
        for record in records:
            try:
                loaded.append({
                    'person_id': int(record['person_id']),
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
        with self._embedding_path().open('wb') as f:
            pickle.dump({'records': self.records}, f)
        self.is_trained = len(self.records) > 0

    def _normalize(self, embedding):
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError('face embedding cannot be a zero vector')
        return vector / norm

    def _best_match(self, probe_embedding):
        if not self.records:
            return None, None

        probe = self._normalize(probe_embedding)
        best_record = None
        best_similarity = None
        for record in self.records:
            similarity = float(np.dot(probe, record['embedding']))
            if best_similarity is None or similarity > best_similarity:
                best_record = record
                best_similarity = similarity
        return best_record, best_similarity

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
        sample_path = self._copy_sample_image(person_id, image_path)
        self.records.append({
            'person_id': int(person_id),
            'person_name': person_name,
            'embedding': embedding,
            'sample_path': sample_path,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        self._save_embeddings()

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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
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
                'detail': '人脸模型未训练，请先注册人脸',
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
        return sorted({record['person_id'] for record in self.records})

    def remove_person(self, person_id):
        """Delete one person's face samples and embeddings."""
        person_id = int(person_id)
        person_dir = self.known_faces_dir / f'person_{person_id}'
        if person_dir.exists():
            shutil.rmtree(person_dir)
        self.records = [record for record in self.records if record['person_id'] != person_id]
        self._save_embeddings()
        return True
