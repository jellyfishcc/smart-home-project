"""
智能家居系统 - YOLO 物体检测服务
使用 ultralytics YOLOv8 进行物体检测
功能：
  1. 上传图片 -> 检测物体 -> 返回标注结果
  2. 检测特定物体（如人、车、灯泡等）并触发相应动作
  3. 支持摄像头实时检测
"""
import os
import cv2
from datetime import datetime
from pathlib import Path

from services.image_io import read_image, write_image

# COCO 数据集的 80 个类别（YOLOv8 默认）
COCO_CLASSES = [
    'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
    'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench',
    'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra',
    'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
    'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove',
    'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
    'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
    'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
    'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse',
    'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink',
    'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier',
    'toothbrush'
]

# 特殊触发规则：检测到特定物体后执行的动作
TRIGGER_RULES = {
    'person': {'action': 'log', 'description': '检测到人员，记录日志'},
    'car': {'action': 'log', 'description': '检测到车辆'},
    'truck': {'action': 'log', 'description': '检测到卡车'},
    'cat': {'action': 'log', 'description': '检测到猫'},
    'dog': {'action': 'log', 'description': '检测到狗'},
    'bottle': {'action': 'log', 'description': '检测到瓶子'},
}


class ObjectDetectionService:
    """YOLO 物体检测服务"""

    def __init__(self, model_name='yolov8n.pt', conf_threshold=0.4, fallback_model=None,
                 bulb_model=None, bulb_conf_threshold=0.5):
        self.model_name = model_name
        self.fallback_model = fallback_model
        self.conf_threshold = conf_threshold
        self._model = None
        self._available = False
        self._init_model()
        self.bulb_conf_threshold = bulb_conf_threshold
        self._bulb_model = None
        if bulb_model:
            try:
                from ultralytics import YOLO

                model = YOLO(str(bulb_model))
                if set(model.names.values()) != {'light_bulb'}:
                    raise ValueError('灯泡模型必须仅包含 light_bulb 类别')
                self._bulb_model = model
                print(f'[YOLO] 灯泡模型加载成功: {bulb_model}')
            except Exception as exc:
                print(f'[YOLO] 灯泡模型加载失败 {bulb_model}: {exc}')

    def _init_model(self):
        """初始化 YOLO 模型"""
        candidates = [self.model_name]
        if self.fallback_model and Path(self.fallback_model) != Path(self.model_name):
            candidates.append(self.fallback_model)

        try:
            from ultralytics import YOLO
        except Exception as e:
            print(f'[YOLO] ultralytics 加载失败，将使用降级模式: {e}')
            self._available = False
            return

        last_error = None
        for candidate in candidates:
            try:
                candidate_path = Path(candidate)
                if not candidate_path.exists():
                    print(f'[YOLO] 模型文件不存在: {candidate_path}')
                    continue
                self._model = YOLO(str(candidate_path))
                self.model_name = candidate_path
                self._available = True
                print('[YOLO] 模型加载成功:', candidate_path)
                return
            except Exception as e:
                last_error = e
                print(f'[YOLO] 模型加载失败 {candidate}: {e}')

        print(f'[YOLO] 所有模型加载失败，将使用降级模式: {last_error}')
        self._available = False

    @property
    def available(self):
        return self._available

    def detect(self, image_path, save_path=None):
        """
        检测图片中的物体
        返回: {
            'objects': [{'class': 'person', 'confidence': 0.95, 'bbox': [x1,y1,x2,y2]}, ...],
            'image_path': 原图路径,
            'result_image_path': 标注后图片路径,
            'count': 检测到的物体数量
        }
        """
        if not os.path.exists(image_path):
            return {'error': f'图片不存在: {image_path}'}

        if self._available:
            result = self._detect_with_yolo(image_path, save_path)
        else:
            result = self._detect_fallback(image_path, save_path)

        if 'error' in result or self._bulb_model is None:
            return result

        bulb_result = self._bulb_model(
            str(image_path), conf=self.bulb_conf_threshold, imgsz=416, verbose=False,
        )[0]
        bulb_objects = self._detected_objects(bulb_result)
        if not bulb_objects:
            return result

        result_path = str(result['result_image_path'])
        annotated = read_image(result_path)
        if annotated is None:
            return {'error': '无法读取检测结果图'}
        if not write_image(result_path, bulb_result.plot(img=annotated)):
            return {'error': '无法保存灯泡检测结果图'}

        result['objects'].extend(bulb_objects)
        result['count'] = len(result['objects'])
        return result

    @staticmethod
    def _detected_objects(result):
        objects = []
        for box in result.boxes:
            cls_id = int(box.cls[0])
            cls_name = result.names[cls_id]
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [round(float(v), 1) for v in box.xyxy[0]]
            objects.append({
                'class': cls_name,
                'class_id': cls_id,
                'confidence': round(conf, 3),
                'bbox': [x1, y1, x2, y2],
            })
        return objects

    def _detect_with_yolo(self, image_path, save_path):
        """使用 YOLO 模型检测"""
        result = self._model(image_path, conf=self.conf_threshold, verbose=False)[0]
        objects = self._detected_objects(result)

        # 保存标注后的图片
        if save_path is None:
            save_path = image_path.replace('.', '_detected.')

        annotated = result.plot()
        if not write_image(save_path, annotated):
            return {'error': '无法保存检测结果图'}

        return {
            'objects': objects,
            'image_path': image_path,
            'result_image_path': save_path,
            'count': len(objects),
        }

    def _detect_fallback(self, image_path, save_path):
        """降级模式：使用 OpenCV 检测人脸"""
        img = read_image(image_path)
        if img is None:
            return {'error': '无法读取图片'}

        if save_path is None:
            save_path = image_path.replace('.', '_detected.')

        objects = []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 人脸检测
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        annotated = img.copy()
        for (x, y, w, h) in faces:
            objects.append({
                'class': 'person',
                'class_id': 0,
                'confidence': 0.85,
                'bbox': [float(x), float(y), float(x + w), float(y + h)],
            })
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(annotated, 'person 0.85', (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        if not write_image(save_path, annotated):
            return {'error': '无法保存检测结果图'}

        return {
            'objects': objects,
            'image_path': image_path,
            'result_image_path': save_path,
            'count': len(objects),
        }

    def check_trigger(self, objects):
        """
        检查检测结果是否触发动作
        返回: 触发的动作描述，无触发返回 None
        """
        actions = []
        for obj in objects:
            cls = obj.get('class', '')
            if cls in TRIGGER_RULES:
                rule = TRIGGER_RULES[cls]
                actions.append({
                    'object': cls,
                    'action': rule['action'],
                    'description': rule['description'],
                })
            # 自定义功能：检测到灯泡 -> 开灯
            if cls in ('light_bulb', 'lamp', 'bulb'):
                actions.append({
                    'object': cls,
                    'action': 'turn_on_light',
                    'description': f'检测到灯泡图片，自动开启灯光',
                })
        return actions if actions else None

    def detect_from_camera(self, camera_index=0):
        """从摄像头捕获一帧并检测"""
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return {'error': '无法打开摄像头'}

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return {'error': '摄像头读取失败'}

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        detection_dir = Path(__file__).resolve().parents[1] / 'uploads' / 'detections'
        detection_dir.mkdir(parents=True, exist_ok=True)
        temp_path = detection_dir / f'camera_{timestamp}.jpg'
        if not write_image(temp_path, frame):
            return {'error': '无法保存摄像头画面'}

        return self.detect(str(temp_path))
