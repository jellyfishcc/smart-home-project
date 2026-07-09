"""
智能家居系统 - 配置文件
"""
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
YOLO_MODEL = 'yolov8n.pt'  # nano 模型，速度快
YOLO_CONF_THRESHOLD = 0.4   # 置信度阈值

# 人脸识别配置
FACE_CONFIDENCE_THRESHOLD = 70  # LBPH 置信度阈值（越低越匹配）
FACE_CASCADE_PATH = None  # 自动查找 OpenCV 自带的级联分类器
FACE_MATCH_THRESHOLD = 0.45
FACE_EMBEDDINGS_PATH = DATA_DIR / 'face_embeddings.pkl'
INSIGHTFACE_MODEL_NAME = 'buffalo_l'
INSIGHTFACE_MODEL_ROOT = BASE_DIR / 'models'
INSIGHTFACE_DET_SIZE = (320, 320)

# 温度阈值（摄氏度）
TEMPERATURE_THRESHOLD = 28.0  # 超过此温度自动开启风扇

# SocketIO 配置
SOCKETIO_ASYNC_MODE = 'eventlet'

# 密钥
SECRET_KEY = 'smart-home-secret-key-2026'

# 模拟模式（无硬件时使用）
SIMULATION_MODE = True

# 设备初始状态
DEFAULT_DEVICE_STATES = {
    'light': {'on': False, 'brightness': 0},    # 灯光
    'fan': {'on': False, 'speed': 0},            # 风扇/空调
    'door': {'locked': True},                     # 入口门
    'window': {'closed': True},                   # 窗户
    'ac': {'on': False, 'temp': 26},             # 空调
}
