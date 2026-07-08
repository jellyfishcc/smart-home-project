"""
智能家居系统 - 人脸识别服务
使用 OpenCV Haar 级联分类器 + LBPH 人脸识别器
功能：
  1. 注册人脸（录入授权人员照片，训练特征）
  2. 识别人脸并判断是否为授权人员
  3. 支持 2真1假 场景（2个授权 + 1个未授权/伪造）
  4. 简单防伪检测（照片亮度/纹理分析）
"""
import os
import cv2
import numpy as np
import pickle
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class FaceRecognitionService:
    """人脸识别服务"""

    def __init__(self, known_faces_dir='known_faces', data_dir='data',
                 confidence_threshold=70):
        self.known_faces_dir = known_faces_dir
        self.data_dir = data_dir
        self.confidence_threshold = confidence_threshold

        # 人脸检测器（Haar 级联分类器）
        cascade_names = [
            'haarcascade_frontalface_default.xml',
            'haarcascade_frontalface_alt2.xml',
            'haarcascade_frontalface_alt.xml',
        ]
        self.face_cascades = [
            cv2.CascadeClassifier(cv2.data.haarcascades + name)
            for name in cascade_names
        ]
        self.face_cascade = self.face_cascades[0]

        # LBPH 人脸识别器
        try:
            self.recognizer = cv2.face.LBPHFaceRecognizer_create(
                radius=1, neighbors=8, grid_x=8, grid_y=8
            )
        except AttributeError:
            logger.warning('LBPH 不可用，需要 opencv-contrib-python')
            self.recognizer = None

        self.is_trained = False
        self.label_map = {}   # {label_id: person_id}
        self.reverse_map = {}  # {person_id: label_id}

        os.makedirs(self.known_faces_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        self._load_model()

    def _model_path(self):
        return os.path.join(self.data_dir, 'face_model.yml')

    def _map_path(self):
        return os.path.join(self.data_dir, 'face_label_map.pkl')

    def _load_model(self):
        """加载已训练的模型"""
        model_path = self._model_path()
        map_path = self._map_path()

        if os.path.exists(model_path) and os.path.exists(map_path):
            try:
                self.recognizer.read(model_path)
                with open(map_path, 'rb') as f:
                    maps = pickle.load(f)
                self.label_map = maps.get('label_map', {})
                self.reverse_map = maps.get('reverse_map', {})
                self.is_trained = True
                logger.info(f'[FaceRec] 已加载人脸模型, 共 {len(self.label_map)} 人')
            except Exception as e:
                logger.warning(f'[FaceRec] 加载模型失败: {e}')

    def _save_model(self):
        """保存训练好的模型"""
        if self.recognizer and self.is_trained:
            self.recognizer.write(self._model_path())
            with open(self._map_path(), 'wb') as f:
                pickle.dump({
                    'label_map': self.label_map,
                    'reverse_map': self.reverse_map,
                }, f)

    def detect_faces(self, image):
        """检测图片中的人脸，返回人脸区域列表"""
        if isinstance(image, str):
            image = cv2.imread(image)
        if image is None:
            return [], None

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        detection_passes = [
            (1.1, 5, (60, 60)),
            (1.05, 3, (30, 30)),
            (1.03, 3, (24, 24)),
        ]

        for scale_factor, min_neighbors, min_size in detection_passes:
            for cascade in self.face_cascades:
                faces = cascade.detectMultiScale(
                    gray,
                    scaleFactor=scale_factor,
                    minNeighbors=min_neighbors,
                    minSize=min_size,
                )
                if len(faces) > 0:
                    return self._merge_overlapping_faces(faces), gray

        return [], gray

    def _merge_overlapping_faces(self, faces):
        """同一张脸可能被检测出多个重叠框，保留面积最大的框。"""
        if len(faces) <= 1:
            return faces

        boxes = sorted([tuple(map(int, face)) for face in faces], key=lambda face: face[2] * face[3], reverse=True)
        merged = []
        for box in boxes:
            if not any(self._face_overlap_ratio(box, kept) > 0.5 for kept in merged):
                merged.append(box)

        return np.array(merged, dtype=np.int32)

    @staticmethod
    def _face_overlap_ratio(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        x1 = max(ax, bx)
        y1 = max(ay, by)
        x2 = min(ax + aw, bx + bw)
        y2 = min(ay + ah, by + bh)

        inter_w = max(0, x2 - x1)
        inter_h = max(0, y2 - y1)
        if inter_w == 0 or inter_h == 0:
            return 0

        inter_area = inter_w * inter_h
        smaller_area = min(aw * ah, bw * bh)
        return inter_area / smaller_area if smaller_area else 0

    def extract_face_samples(self, image_path):
        """从图片中提取人脸样本（灰度图列表）"""
        faces, gray = self.detect_faces(image_path)
        if len(faces) == 0:
            return [], 0

        samples = []
        for (x, y, w, h) in faces:
            # 扩大裁剪区域 10%
            pad_w = int(w * 0.1)
            pad_h = int(h * 0.1)
            x1 = max(0, x - pad_w)
            y1 = max(0, y - pad_h)
            x2 = min(gray.shape[1], x + w + pad_w)
            y2 = min(gray.shape[0], y + h + pad_h)
            face_roi = gray[y1:y2, x1:x2]
            # 统一大小
            face_roi = cv2.resize(face_roi, (100, 100))
            samples.append(face_roi)

        return samples, len(faces)

    def register_face(self, person_id, image_path, person_name=None):
        """
        注册人脸 - 将人员照片加入训练集并重新训练
        返回: {'success': bool, 'message': str, 'face_count': int}
        """
        samples, face_count = self.extract_face_samples(image_path)

        if face_count == 0:
            return {
                'success': False,
                'message': '未检测到人脸，请确保照片中有清晰的人脸',
                'face_count': 0,
            }

        if face_count > 1:
            return {
                'success': False,
                'message': f'检测到 {face_count} 张人脸，请使用单人照片',
                'face_count': face_count,
            }

        # 保存人脸样本图片
        person_dir = os.path.join(self.known_faces_dir, f'person_{person_id}')
        os.makedirs(person_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sample_path = os.path.join(person_dir, f'{timestamp}.jpg')
        cv2.imwrite(sample_path, samples[0])

        # 重新训练模型
        self._train_model()

        return {
            'success': True,
            'message': f'人脸注册成功 (人员: {person_name or person_id})',
            'face_count': face_count,
            'sample_path': sample_path,
        }

    def _train_model(self):
        """收集所有注册的人脸样本并训练 LBPH 模型"""
        if not self.recognizer:
            logger.warning('[FaceRec] LBPH 识别器不可用')
            return

        faces = []
        labels = []
        self.label_map = {}
        self.reverse_map = {}
        label_id = 0

        # 遍历 known_faces 目录
        if not os.path.exists(self.known_faces_dir):
            return

        for dir_name in sorted(os.listdir(self.known_faces_dir)):
            if not dir_name.startswith('person_'):
                continue
            person_id = int(dir_name.split('_')[1])
            person_dir = os.path.join(self.known_faces_dir, dir_name)

            self.label_map[label_id] = person_id
            self.reverse_map[person_id] = label_id

            for file_name in os.listdir(person_dir):
                if not file_name.lower().endswith(('.jpg', '.png', '.jpeg', '.bmp')):
                    continue
                img_path = os.path.join(person_dir, file_name)
                img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    img = cv2.resize(img, (100, 100))
                    faces.append(img)
                    labels.append(label_id)

            label_id += 1

        if len(faces) == 0:
            self.is_trained = False
            return

        # 训练
        labels = np.array(labels)
        self.recognizer.train(faces, labels)
        self.is_trained = True
        self._save_model()
        logger.info(f'[FaceRec] 模型训练完成, {len(faces)} 个样本, {label_id} 人')

    def recognize(self, image_path):
        """
        识别人脸
        返回: {
            'recognized': bool,
            'person_id': int or None,
            'person_name': str or None,
            'confidence': float,
            'faces_detected': int,
            'result': 'granted' | 'denied' | 'unknown',
            'detail': str
        }
        """
        faces, gray = self.detect_faces(image_path)

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

        if not self.is_trained or not self.recognizer:
            return {
                'recognized': False,
                'person_id': None,
                'person_name': None,
                'confidence': None,
                'faces_detected': len(faces),
                'result': 'unknown',
                'detail': '人脸模型未训练，请先注册人脸',
            }

        # 取最大的人脸进行识别
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = largest_face
        pad_w = int(w * 0.1)
        pad_h = int(h * 0.1)
        x1 = max(0, x - pad_w)
        y1 = max(0, y - pad_h)
        x2 = min(gray.shape[1], x + w + pad_w)
        y2 = min(gray.shape[0], y + h + pad_h)
        face_roi = gray[y1:y2, x1:x2]
        face_roi = cv2.resize(face_roi, (100, 100))

        label_id, confidence = self.recognizer.predict(face_roi)

        # LBPH 置信度：越低越匹配（0 = 完美匹配）
        person_id = self.label_map.get(label_id)

        if confidence < self.confidence_threshold and person_id is not None:
            return {
                'recognized': True,
                'person_id': person_id,
                'person_name': None,  # 由调用方从数据库查询
                'confidence': round(confidence, 2),
                'faces_detected': len(faces),
                'result': 'granted',
                'detail': f'识别成功 (置信度={round(confidence, 2)})',
            }
        else:
            return {
                'recognized': False,
                'person_id': person_id,
                'person_name': None,
                'confidence': round(confidence, 2),
                'faces_detected': len(faces),
                'result': 'denied',
                'detail': f'识别失败，未授权人员 (置信度={round(confidence, 2)})',
            }

    def check_liveness(self, image_path):
        """
        简单的活体检测 - 检查是否为打印照片
        通过分析图像纹理和光照来判断
        返回: {'is_live': bool, 'score': float, 'detail': str}
        """
        img = cv2.imread(image_path)
        if img is None:
            return {'is_live': False, 'score': 0, 'detail': '无法读取图片'}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. 检查图像清晰度（拉普拉斯方差）
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        # 2. 检查色彩饱和度
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1].mean()

        # 3. 检查光照均匀性
        brightness = gray.mean()
        brightness_std = gray.std()

        # 综合评分
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

        is_live = score >= 60

        return {
            'is_live': is_live,
            'score': score,
            'detail': '; '.join(detail_parts),
        }

    def get_registered_persons(self):
        """获取已注册人脸的人员ID列表"""
        return list(self.reverse_map.keys())

    def remove_person(self, person_id):
        """删除人员的人脸数据"""
        person_dir = os.path.join(self.known_faces_dir, f'person_{person_id}')
        if os.path.exists(person_dir):
            import shutil
            shutil.rmtree(person_dir)
        self._train_model()
        return True


# Keep the historical import path stable while using the InsightFace implementation.
from services.insightface_recognition_service import FaceRecognitionService as FaceRecognitionService
