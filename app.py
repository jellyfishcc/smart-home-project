"""
智能家居系统 - 主应用入口
Smart Home System - Main Application Entry Point

功能模块：
  1. 授权人员管理 - 存储和管理门禁授权人员信息（支持2真1假）
  2. 物体检测 - YOLO 算法识别图片中的物体
  3. 人脸识别门禁 - 人脸识别开启门禁（含活体检测）
  4. Web GUI - 实时仪表盘、设备控制、数据分析
  5. 远程控制 - 通过 GUI 远程控制灯、空调、门等设备
  6. 自定义功能 - 摄像头检测到灯泡图片后自动控制灯光

启动方式:
  python app.py

访问地址:
  http://localhost:5000
"""
import os
import sys
import logging
from datetime import datetime

from flask import Flask
from flask_socketio import SocketIO
from models import db, DeviceStatusLog, TemperatureLog, LightingRecord
from database import init_db
from routes.api import api_bp
from routes.pages import pages_bp
from services.device_manager import device_manager
from services.sensor_simulator import sensor_simulator
from services.object_detection import ObjectDetectionService
from services.face_recognition_service import FaceRecognitionService
import config

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('SmartHome')

# 创建 Flask 应用
app = Flask(__name__)
app.config.from_object(config)

# 确保目录存在
for dir_path in [config.UPLOAD_FOLDER, config.DETECTION_FOLDER,
                 config.FACE_FOLDER, config.KNOWN_FACES_FOLDER, config.DATA_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# 初始化数据库
db.init_app(app)
init_db(app)

# 初始化 SocketIO
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')

# 初始化服务
logger.info('正在初始化物体检测服务 (YOLO)...')
detection_service = ObjectDetectionService(
    model_name=config.YOLO_MODEL,
    conf_threshold=config.YOLO_CONF_THRESHOLD,
)
app.config['DETECTION_SERVICE'] = detection_service

logger.info('正在初始化人脸识别服务...')
face_service = FaceRecognitionService(
    known_faces_dir=config.KNOWN_FACES_FOLDER,
    data_dir=config.DATA_DIR,
    confidence_threshold=config.FACE_MATCH_THRESHOLD,
    embeddings_path=config.FACE_EMBEDDINGS_PATH,
    model_name=config.INSIGHTFACE_MODEL_NAME,
    model_root=config.INSIGHTFACE_MODEL_ROOT,
    det_size=config.INSIGHTFACE_DET_SIZE,
)
app.config['FACE_SERVICE'] = face_service

# 配置设备管理器和传感器模拟器
device_manager.init_app(app)
device_manager.set_socketio(socketio)
device_manager.set_db_logger(lambda name, status, value, source: _log_device_status(name, status, value, source))
device_manager.set_lighting_logger(lambda status, brightness, source, recorded_at: _log_lighting(status, brightness, source, recorded_at))

sensor_simulator.init_app(app)
sensor_simulator.set_socketio(socketio)
sensor_simulator.set_device_manager(device_manager)
sensor_simulator.set_db_logger(lambda temp, hum, fan: _log_temperature(temp, hum, fan))


def _log_device_status(device_name, status, value, source):
    """记录设备状态到数据库"""
    try:
        log = DeviceStatusLog(
            device_name=device_name,
            status=status,
            value=value,
            source=source,
            recorded_at=datetime.utcnow(),
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logger.error(f'记录设备状态失败: {e}')
        db.session.rollback()


def _log_temperature(temp, humidity, fan_activated):
    """记录温度到数据库"""
    try:
        log = TemperatureLog(
            temperature=temp,
            humidity=humidity,
            recorded_at=datetime.utcnow(),
            fan_activated=fan_activated,
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logger.error(f'记录温度失败: {e}')
        db.session.rollback()


def _log_lighting(status, brightness, source, recorded_at):
    """记录灯光操作到 LightingRecord 表"""
    try:
        log = LightingRecord(
            status=status,
            brightness=brightness,
            source=source,
            recorded_at=recorded_at,
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logger.error(f'记录灯光失败: {e}')
        db.session.rollback()


# 注册蓝图
app.register_blueprint(api_bp)
app.register_blueprint(pages_bp)

# SocketIO 事件处理
@socketio.on('connect')
def handle_connect():
    logger.info('[SocketIO] 客户端已连接')
    socketio.emit('connected', {'message': '已连接到智能家居系统'})


@socketio.on('disconnect')
def handle_disconnect():
    logger.info('[SocketIO] 客户端已断开')


@socketio.on('request_status')
def handle_request_status():
    """客户端请求当前状态"""
    socketio.emit('status_update', {
        'sensor': sensor_simulator.get_current_reading(),
        'devices': device_manager.get_all_status(),
    })


# 启动传感器模拟器
if config.SIMULATION_MODE:
    sensor_simulator.start()
    logger.info('传感器模拟器已启动 (模拟模式)')


@app.context_processor
def inject_globals():
    """注入全局模板变量"""
    return {
        'app_title': '智能家居管理系统',
        'yolo_available': detection_service.available,
        'face_trained': face_service.is_trained,
    }


if __name__ == '__main__':
    logger.info('=' * 50)
    logger.info('  智能家居管理系统启动中...')
    logger.info(f'  YOLO 检测: {"可用" if detection_service.available else "降级模式"}')
    logger.info(f'  人脸 Embedding: 已加载 {len(face_service.records)} 条' if face_service.is_trained else '  人脸 Embedding: 未注册')
    logger.info(f'  传感器模式: {"模拟" if config.SIMULATION_MODE else "真实"}')
    logger.info('  访问地址: http://localhost:5000')
    logger.info('=' * 50)

    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
