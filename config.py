"""
智能家居系统 - 配置文件
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 数据库配置
SQLALCHEMY_DATABASE_URI = f"sqlite:///{(BASE_DIR / 'data' / 'smart_home.db').as_posix()}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# 文件上传路径
UPLOAD_FOLDER = BASE_DIR / 'uploads'
DETECTION_FOLDER = UPLOAD_FOLDER / 'detections'
FACE_FOLDER = UPLOAD_FOLDER / 'faces'
KNOWN_FACES_FOLDER = BASE_DIR / 'known_faces'
DATA_DIR = BASE_DIR / 'data'

# 允许的文件类型
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'}

# YOLO 模型配置
YOLO_CUSTOM_MODEL = BASE_DIR / 'models' / 'yolo' / 'best.pt'
YOLO_FALLBACK_MODEL = BASE_DIR / 'yolov8n.pt'
YOLO_MODEL = YOLO_CUSTOM_MODEL if YOLO_CUSTOM_MODEL.exists() else YOLO_FALLBACK_MODEL
YOLO_CONF_THRESHOLD = 0.4

# 服务器端摄像头配置。
# 默认明确使用香橙派/Linux 的 /dev/video0，避免在 Windows 本地误读电脑摄像头。
# 如需切换设备：
#   Linux: SMART_HOME_CAMERA_DEVICE=/dev/video1 python3 app.py
#   Fallback numeric index: SMART_HOME_CAMERA_DEVICE= SMART_HOME_CAMERA_INDEX=1 python3 app.py
CAMERA_DEVICE = os.environ.get('SMART_HOME_CAMERA_DEVICE', '/dev/video0')
CAMERA_INDEX = int(os.environ.get('SMART_HOME_CAMERA_INDEX', '0'))
CAMERA_SOURCE = CAMERA_DEVICE or CAMERA_INDEX

# 人脸识别配置
FACE_CONFIDENCE_THRESHOLD = 70
FACE_CASCADE_PATH = None
FACE_MATCH_THRESHOLD = 0.45
FACE_EMBEDDINGS_PATH = DATA_DIR / 'face_embeddings.pkl'
INSIGHTFACE_MODEL_NAME = 'buffalo_l'
INSIGHTFACE_MODEL_ROOT = BASE_DIR / 'models'
INSIGHTFACE_DET_SIZE = (320, 320)

# 温度阈值（摄氏度）
TEMPERATURE_THRESHOLD = 28.0

# SocketIO 配置
SOCKETIO_ASYNC_MODE = 'eventlet'

# 密钥
SECRET_KEY = 'smart-home-secret-key-2026'

# 模拟模式（无硬件时使用）
SIMULATION_MODE = True

# 设备初始状态
DEFAULT_DEVICE_STATES = {
    'light': {'on': False, 'brightness': 0},
    'fan': {'on': False, 'speed': 0},
    'door': {'locked': True},
    'window': {'closed': True},
    'ac': {'on': False, 'temp': 26},
}
