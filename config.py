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
YOLO_BULB_MODEL = BASE_DIR / 'models' / 'yolo' / 'light_bulb.pt'
YOLO_BULB_CONF_THRESHOLD = 0.55

# 服务器端摄像头配置。
# Linux（香橙派）默认走 /dev/video0；Windows 没有设备节点，默认直接用数字索引 0（本机摄像头）。
# 如需切换设备：
#   Linux: SMART_HOME_CAMERA_DEVICE=/dev/video1 python3 app.py
#   Windows: 用 SMART_HOME_CAMERA_INDEX 指定第几个摄像头（0=默认），或显式给 DEVICE 传设备路径
DEFAULT_CAMERA_DEVICE = '' if os.name == 'nt' else '/dev/video0'
CAMERA_DEVICE = os.environ.get('SMART_HOME_CAMERA_DEVICE', DEFAULT_CAMERA_DEVICE)
CAMERA_INDEX = int(os.environ.get('SMART_HOME_CAMERA_INDEX', '0'))
# 注意：Windows 下无法用 `set VAR=` 传空串把默认值顶掉（cmd 会直接删除该变量），
# 所以平台差异放在默认值里，而不是靠调用方传空值。
CAMERA_SOURCE = CAMERA_DEVICE or CAMERA_INDEX

# 哨兵（Sentry）模式配置
# 巡检间隔（秒）：一轮「抓帧 -> 检测 -> 核验」的周期。香橙派上 YOLOv8n 单帧 0.3~1s，
# 不建议低于 5s，否则线程会一直追不上；本地演示可临时调小。
SENTRY_PATROL_INTERVAL = max(3, int(os.environ.get('SMART_HOME_SENTRY_INTERVAL', '10')))
# 布防延时（秒）：留出关门离开的时间，延时内不告警。演示默认 0，按下即布防。
SENTRY_ARM_DELAY = max(0, int(os.environ.get('SMART_HOME_SENTRY_ARM_DELAY', '0')))
# 同类告警冷却（秒）：冷却期内重复触发只累加次数，不再刷屏
SENTRY_ALARM_COOLDOWN = max(0, int(os.environ.get('SMART_HOME_SENTRY_COOLDOWN', '60')))
# 每轮留证张数：只要本轮检测到人就连拍一组，作为「活动/告警」的现场证据。
# 前端按 2fps 轮播这组图，视觉上等于一段短录像，不需要编码视频。
SENTRY_BURST_FRAMES = max(1, int(os.environ.get('SMART_HOME_SENTRY_BURST', '10')))
# 连续多少轮出现未授权人员后升级为告警。
# 第 1 轮只记「活动」（info，不亮灯），满 3 轮才真正告警 —— 路过的人撑不到 3 轮。
SENTRY_ALARM_ROUNDS = max(1, int(os.environ.get('SMART_HOME_SENTRY_ALARM_ROUNDS', '3')))
# 未告警时的留证滚动窗口（轮）：超出后自动删除最旧一轮，避免磁盘无限增长。
# 授权人脸出现且从未告警时，这个窗口内的留证会被整批清除。
SENTRY_SNAPSHOT_WINDOW = max(1, int(os.environ.get('SMART_HOME_SENTRY_WINDOW', '12')))
# 连拍间隔（秒），仅用于留证序列，不影响巡检节奏
SENTRY_BURST_GAP = float(os.environ.get('SMART_HOME_SENTRY_BURST_GAP', '0.12'))
# 检测阈值：人形检测阈值略低于常规值，提高远处/背光目标的召回率
SENTRY_PERSON_CONF = float(os.environ.get('SMART_HOME_SENTRY_CONF', '0.35'))
# 哨兵专用的 COCO 模型：must 含 person 类，不能复用 YOLO_MODEL（best.pt 只有 drone/fire_extinguisher）
SENTRY_PERSON_MODEL = YOLO_FALLBACK_MODEL
# 快照目录（对外通过 /api/files/sentry/<name> 访问）
SENTRY_SNAPSHOT_FOLDER = UPLOAD_FOLDER / 'sentry'

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

# ---------------- 硬件串口（Arduino 门禁板 / 环境板） ----------------
# 通信层实现在 services/serial_bridge.py，只做信息交换，不含业务判断。
# 默认关闭：不设 SMART_HOME_SERIAL_ENABLED=1 时行为与之前完全一致。
# 打开后若找不到串口，仅打警告并自动重连，不会影响其它功能。
SERIAL_ENABLED = os.environ.get('SMART_HOME_SERIAL_ENABLED', '0') in ('1', 'true', 'True')
# 端口留空 = 自动探测（按 VID / 描述匹配 CH340、Arduino、CP210x 等）
SERIAL_PORT = os.environ.get('SMART_HOME_SERIAL_PORT', '')
SERIAL_BAUD = int(os.environ.get('SMART_HOME_SERIAL_BAUD', '9600'))
# 单条命令等回执的超时（秒）。9600bps 下 20 字节约 21ms，300ms 留了 10 倍余量
SERIAL_CMD_TIMEOUT = float(os.environ.get('SMART_HOME_SERIAL_TIMEOUT', '0.3'))
# 超时重试次数。协议里的命令都是幂等的，重发安全
SERIAL_CMD_RETRIES = max(0, int(os.environ.get('SMART_HOME_SERIAL_RETRIES', '2')))
# 开串口会因 DTR 复位板子，这段是等待启动横幅的时间
SERIAL_BOOT_WAIT = float(os.environ.get('SMART_HOME_SERIAL_BOOT_WAIT', '2.5'))
# 心跳间隔（秒）；0 = 关闭。固件不会主动说话，靠它判定在线
SERIAL_HEARTBEAT_INTERVAL = float(os.environ.get('SMART_HOME_SERIAL_HEARTBEAT', '3'))
# 多久收不到任何上行就判离线（秒）
SERIAL_OFFLINE_TIMEOUT = float(os.environ.get('SMART_HOME_SERIAL_OFFLINE', '10'))
# 雨滴轮询间隔（秒）；固件没有主动上报能力，只能问。0 = 关闭
SERIAL_RAIN_POLL_INTERVAL = float(os.environ.get('SMART_HOME_SERIAL_RAIN_POLL', '30'))
# 断开后重连间隔（秒）
SERIAL_RECONNECT_DELAY = float(os.environ.get('SMART_HOME_SERIAL_RECONNECT', '2'))
# 兜底回锁：固件 OPEN_DURATION=5000ms，多给 1 秒。
# 正常情况板子会主动上报「自动关门」，这个计时器只在丢包时生效
SERIAL_DOOR_AUTO_CLOSE = float(os.environ.get('SMART_HOME_SERIAL_AUTO_CLOSE', '6'))

# ---------------- 环境板（UNO I） ----------------
# 回传契约：板子收到 `QENV\n` 后回 `@DATA ENV <温度×10> <湿度×10> <DHT有效标志>`。
# 端口必须显式指定，留空则不启动环境板实例：自动探测会优先抢到门禁板那条口，
# 两块板共用一个 COM 会互相踩（打开串口还会因 DTR 把对方复位）。
SERIAL_ENV_ENABLED = os.environ.get('SMART_HOME_SERIAL_ENV_ENABLED', '0') in ('1', 'true', 'True')
SERIAL_ENV_PORT = os.environ.get('SMART_HOME_SERIAL_ENV_PORT', '')
# 温湿度轮询间隔（秒）。DHT11 本身两次采样要隔 ≥2s，10s 足够且不会刷屏
SERIAL_ENV_POLL_INTERVAL = float(os.environ.get('SMART_HOME_SERIAL_ENV_POLL', '10'))
# 等环境板启动横幅的时间（秒）。UNOI 的 setup() 里有 OLED 初始化 + delay(1000)，
# 实测要 2.6~2.8s 才吐出 @BOOT，沿用门禁板的 2.5s 会让第一次轮询白吃一次超时
SERIAL_ENV_BOOT_WAIT = float(os.environ.get('SMART_HOME_SERIAL_ENV_BOOT_WAIT', '4'))

# 设备初始状态
DEFAULT_DEVICE_STATES = {
    'light': {'on': False, 'brightness': 0},
    'fan': {'on': False, 'speed': 0},
    'door': {'locked': True},
    'window': {'closed': True},
    'ac': {'on': False, 'temp': 26},
}
