"""
智能家居系统 - REST API 路由
提供所有后端 API 接口：
  - 授权人员管理
  - 人脸识别门禁
  - 物体检测 (YOLO)
  - 设备远程控制
  - 传感器数据
  - 历史数据查询与统计
"""
import os
import json
import time
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename

from models import db, AuthorizedPerson, AccessLog, TemperatureLog, DeviceStatusLog, DetectionRecord, LightingRecord
from services.device_manager import device_manager
from services.sensor_simulator import sensor_simulator
from services.camera_capture import capture_camera_frame

api_bp = Blueprint('api', __name__, url_prefix='/api')


def allowed_file(filename):
    """检查文件类型是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def _timestamped_upload_filename(prefix, original_filename, forced_stem=None, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    safe_name = secure_filename(original_filename or '')
    ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'jpg'
    stem = forced_stem or (safe_name.rsplit('.', 1)[0] if '.' in safe_name else 'image')
    stem = secure_filename(stem) or 'image'
    if prefix.startswith('person_') or prefix == 'access':
        return secure_filename(f'{prefix}_{timestamp}.{ext}')
    return secure_filename(f'{prefix}_{timestamp}_{stem}.{ext}')


# ============================================================
# 1. 授权人员管理 API
# ============================================================

@api_bp.route('/persons', methods=['GET'])
def get_persons():
    """获取所有授权人员列表"""
    persons = AuthorizedPerson.query.order_by(AuthorizedPerson.id).all()
    return jsonify({
        'code': 0,
        'message': 'success',
        'data': [p.to_dict() for p in persons],
        'total': len(persons),
    })


@api_bp.route('/persons/<int:person_id>', methods=['GET'])
def get_person(person_id):
    """获取单个授权人员详情"""
    person = AuthorizedPerson.query.get_or_404(person_id)
    return jsonify({'code': 0, 'message': 'success', 'data': person.to_dict()})


@api_bp.route('/persons', methods=['POST'])
def add_person():
    """添加授权人员"""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'code': 1, 'message': '姓名不能为空'}), 400

    person = AuthorizedPerson(
        name=data['name'],
        employee_id=data.get('employee_id', f'EMP{int(time.time())}'),
        role=data.get('role', '成员'),
        is_authorized=data.get('is_authorized', True),
        is_fake=data.get('is_fake', False),
        phone=data.get('phone', ''),
        department=data.get('department', ''),
    )
    db.session.add(person)
    db.session.commit()
    return jsonify({'code': 0, 'message': '添加成功', 'data': person.to_dict()}), 201


@api_bp.route('/persons/<int:person_id>', methods=['PUT'])
def update_person(person_id):
    """更新授权人员信息"""
    person = AuthorizedPerson.query.get_or_404(person_id)
    data = request.get_json()

    for field in ['name', 'employee_id', 'role', 'is_authorized', 'is_fake', 'phone', 'department']:
        if field in data:
            setattr(person, field, data[field])

    db.session.commit()
    return jsonify({'code': 0, 'message': '更新成功', 'data': person.to_dict()})


@api_bp.route('/persons/<int:person_id>', methods=['DELETE'])
def delete_person(person_id):
    """删除授权人员"""
    person = AuthorizedPerson.query.get_or_404(person_id)

    # 删除人脸数据
    face_service = current_app.config.get('FACE_SERVICE')
    if face_service:
        face_service.remove_person(person_id)

    db.session.delete(person)
    db.session.commit()
    return jsonify({'code': 0, 'message': '删除成功'})


@api_bp.route('/persons/<int:person_id>/register-face', methods=['POST'])
def register_face(person_id):
    """为授权人员注册人脸（上传照片）"""
    person = AuthorizedPerson.query.get_or_404(person_id)

    if 'file' not in request.files:
        return jsonify({'code': 1, 'message': '请上传人脸照片'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'code': 1, 'message': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'code': 1, 'message': '不支持的文件格式'}), 400

    # 保存上传的图片
    filename = _timestamped_upload_filename(f'person_{person_id}', file.filename)
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'faces')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    file.save(file_path)

    # 调用人脸识别服务注册
    face_service = current_app.config.get('FACE_SERVICE')
    if not face_service:
        return jsonify({'code': 1, 'message': '人脸识别服务不可用'}), 500

    result = face_service.register_face(person_id, file_path, person.name)

    if result['success']:
        person.face_image_path = file_path
        person.face_encoding_path = os.path.join('data', 'face_embeddings.pkl')
        db.session.commit()

    return jsonify({
        'code': 0 if result['success'] else 1,
        'message': result['message'],
        'data': result,
    })


# ============================================================
# 2. 人脸识别门禁 API
# ============================================================

def _process_access_image(file_path, filename):
    face_service = current_app.config.get('FACE_SERVICE')
    if not face_service:
        return jsonify({'code': 1, 'message': '人脸识别服务不可用'}), 500

    liveness = face_service.check_liveness(file_path)
    result = face_service.recognize(file_path)

    person = None
    if result['person_id']:
        person = AuthorizedPerson.query.get(result['person_id'])
        if person:
            result['person_name'] = person.name

    access_result = 'unknown'
    detail = result['detail']

    if result['recognized'] and person:
        if person.is_authorized and not person.is_fake:
            access_result = 'granted'
            detail = f'授权人员 {person.name} 识别成功，门禁已开启'
            device_manager.set_device('door', 'unlocked', source='face_recognition')
        elif person.is_fake:
            access_result = 'denied'
            detail = f'伪造身份检测 {person.name}，门禁拒绝'
        else:
            access_result = 'denied'
            detail = f'人员 {person.name} 未授权，门禁拒绝'
    elif result['faces_detected'] > 0:
        access_result = 'denied'
        detail = '未授权人员，门禁拒绝'

    if not liveness['is_live']:
        access_result = 'denied'
        detail += f' | 活体检测失败({liveness["detail"]})'

    log = AccessLog(
        person_id=person.id if person else None,
        person_name=person.name if person else '未知',
        access_time=datetime.utcnow(),
        access_result=access_result,
        confidence=result.get('confidence'),
        image_path=file_path,
        method='face_recognition',
        detail=detail,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'code': 0,
        'message': '识别完成',
        'data': {
            'access_result': access_result,
            'person_name': result.get('person_name'),
            'person_id': result.get('person_id'),
            'confidence': result.get('confidence'),
            'faces_detected': result.get('faces_detected'),
            'liveness': liveness,
            'detail': detail,
            'image_url': f'/api/files/detections/{filename}',
            'log_id': log.id,
        }
    })


@api_bp.route('/access/recognize', methods=['POST'])
def recognize_face():
    """人脸识别开门 - 上传照片进行识别"""
    if 'file' not in request.files:
        return jsonify({'code': 1, 'message': '请上传照片'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'code': 1, 'message': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'code': 1, 'message': '不支持的文件格式'}), 400

    # 保存图片
    filename = _timestamped_upload_filename('access', file.filename)
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'detections')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    file.save(file_path)

    face_service = current_app.config.get('FACE_SERVICE')
    if not face_service:
        return jsonify({'code': 1, 'message': '人脸识别服务不可用'}), 500

    # 活体检测
    liveness = face_service.check_liveness(file_path)

    # 人脸识别
    result = face_service.recognize(file_path)

    # 查询人员信息
    person = None
    if result['person_id']:
        person = AuthorizedPerson.query.get(result['person_id'])
        if person:
            result['person_name'] = person.name

    # 判断访问结果
    access_result = 'unknown'
    detail = result['detail']

    if result['recognized'] and person:
        if person.is_authorized and not person.is_fake:
            access_result = 'granted'
            detail = f'授权人员 {person.name} 识别成功，门禁已开启'
            # 开门
            device_manager.set_device('door', 'unlocked', source='face_recognition')
        elif person.is_fake:
            access_result = 'denied'
            detail = f'伪造身份检测: {person.name}，门禁拒绝'
        else:
            access_result = 'denied'
            detail = f'人员 {person.name} 未授权，门禁拒绝'
    elif result['faces_detected'] > 0:
        access_result = 'denied'
        detail = '未授权人员，门禁拒绝'

    # 活体检测失败
    if not liveness['is_live']:
        access_result = 'denied'
        detail += f' | 活体检测失败({liveness["detail"]})'

    # 记录访问日志
    log = AccessLog(
        person_id=person.id if person else None,
        person_name=person.name if person else '未知',
        access_time=datetime.utcnow(),
        access_result=access_result,
        confidence=result.get('confidence'),
        image_path=file_path,
        method='face_recognition',
        detail=detail,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'code': 0,
        'message': '识别完成',
        'data': {
            'access_result': access_result,
            'person_name': result.get('person_name'),
            'person_id': result.get('person_id'),
            'confidence': result.get('confidence'),
            'faces_detected': result.get('faces_detected'),
            'liveness': liveness,
            'detail': detail,
            'image_url': f'/api/files/detections/{filename}',
            'log_id': log.id,
        }
    })


@api_bp.route('/access/camera', methods=['POST'])
def recognize_face_from_camera():
    """从运行 Flask 的设备摄像头拍照，并复用门禁识别开门逻辑"""
    timestamp = int(time.time())
    filename = f'access_camera_{timestamp}.jpg'
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'detections')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)

    capture = capture_camera_frame(current_app.config.get('CAMERA_INDEX', 0), file_path)
    if not capture.get('success'):
        return jsonify({
            'code': 1,
            'message': capture.get('error', '摄像头拍照失败'),
        }), 500

    return _process_access_image(file_path, filename)


@api_bp.route('/access/logs', methods=['GET'])
def get_access_logs():
    """获取门禁访问日志"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    result_filter = request.args.get('result')

    query = AccessLog.query
    if result_filter:
        query = query.filter(AccessLog.access_result == result_filter)

    pagination = query.order_by(AccessLog.access_time.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': [log.to_dict() for log in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages,
    })


# ============================================================
# 3. 物体检测 API (YOLO)
# ============================================================

@api_bp.route('/detection/upload', methods=['POST'])
def upload_and_detect():
    """上传图片并进行 YOLO 物体检测"""
    if 'file' not in request.files:
        return jsonify({'code': 1, 'message': '请上传图片'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'code': 1, 'message': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'code': 1, 'message': '不支持的文件格式'}), 400

    # 保存原图
    filename = secure_filename(f'detect_{int(time.time())}_{file.filename}')
    detection_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'detections')
    os.makedirs(detection_dir, exist_ok=True)
    image_path = os.path.join(detection_dir, filename)
    file.save(image_path)

    result_filename = filename.rsplit('.', 1)[0] + '_result.' + filename.rsplit('.', 1)[1]
    result_path = os.path.join(detection_dir, result_filename)

    # 执行检测
    detection_service = current_app.config.get('DETECTION_SERVICE')
    if not detection_service:
        return jsonify({'code': 1, 'message': '检测服务不可用'}), 500

    result = detection_service.detect(image_path, result_path)

    if 'error' in result:
        return jsonify({'code': 1, 'message': result['error']}), 500

    # 检查触发动作
    triggered_action = None
    actions = detection_service.check_trigger(result['objects'])
    if actions:
        triggered_action = json.dumps(actions, ensure_ascii=False)

        # 执行触发的动作
        for action in actions:
            if action['action'] == 'turn_on_light':
                device_manager.set_light_brightness(80, source='auto_detection')
                action['executed'] = True

    # 保存检测记录
    record = DetectionRecord(
        image_path=f'/api/files/detections/{filename}',
        result_image_path=f'/api/files/detections/{result_filename}',
        objects_detected=json.dumps(result['objects'], ensure_ascii=False),
        object_count=result['count'],
        detected_at=datetime.utcnow(),
        source='upload',
        triggered_action=triggered_action,
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({
        'code': 0,
        'message': '检测完成',
        'data': {
            'record_id': record.id,
            'image_url': f'/api/files/detections/{filename}',
            'result_image_url': f'/api/files/detections/{result_filename}',
            'objects': result['objects'],
            'count': result['count'],
            'triggered_actions': json.loads(triggered_action) if triggered_action else None,
        }
    })


@api_bp.route('/detection/camera', methods=['POST'])
def detect_from_camera():
    """从摄像头拍照并检测"""
    detection_service = current_app.config.get('DETECTION_SERVICE')
    if not detection_service:
        return jsonify({'code': 1, 'message': '检测服务不可用'}), 500

    timestamp = int(time.time())
    filename = f'camera_{timestamp}.jpg'
    detection_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'detections')
    os.makedirs(detection_dir, exist_ok=True)
    image_path = os.path.join(detection_dir, filename)

    capture = capture_camera_frame(current_app.config.get('CAMERA_INDEX', 0), image_path)
    if not capture.get('success'):
        return jsonify({
            'code': 1,
            'message': capture.get('error', '摄像头拍照失败'),
        }), 500

    result_filename = f'camera_{timestamp}_result.jpg'
    result_path = os.path.join(detection_dir, result_filename)
    result = detection_service.detect(image_path, result_path)

    if 'error' in result:
        return jsonify({'code': 1, 'message': result['error']}), 500

    # 检查触发
    actions = detection_service.check_trigger(result['objects'])
    if actions:
        for action in actions:
            if action['action'] == 'turn_on_light':
                device_manager.set_light_brightness(80, source='auto_detection')
                action['executed'] = True

    triggered_action = json.dumps(actions, ensure_ascii=False) if actions else None

    record = DetectionRecord(
        image_path=f'/api/files/detections/{filename}',
        result_image_path=f'/api/files/detections/{result_filename}',
        objects_detected=json.dumps(result['objects'], ensure_ascii=False),
        object_count=result['count'],
        detected_at=datetime.utcnow(),
        source='camera',
        triggered_action=triggered_action,
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({
        'code': 0,
        'message': '摄像头检测完成',
        'data': {
            'record_id': record.id,
            'image_url': f'/api/files/detections/{filename}',
            'result_image_url': f'/api/files/detections/{result_filename}',
            'objects': result['objects'],
            'count': result['count'],
            'triggered_actions': json.loads(triggered_action) if triggered_action else None,
        }
    })


@api_bp.route('/detection/records', methods=['GET'])
def get_detection_records():
    """获取检测记录列表"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    pagination = DetectionRecord.query.order_by(
        DetectionRecord.detected_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    })


# ============================================================
# 4. 设备控制 API
# ============================================================

@api_bp.route('/devices', methods=['GET'])
def get_all_devices():
    """获取所有设备状态"""
    return jsonify({
        'code': 0,
        'message': 'success',
        'data': device_manager.get_all_status(),
    })


@api_bp.route('/devices/<device_name>', methods=['GET'])
def get_device_status(device_name):
    """获取单个设备状态"""
    status = device_manager.get_device(device_name)
    return jsonify({'code': 0, 'message': 'success', 'data': status})


@api_bp.route('/devices/<device_name>/control', methods=['POST'])
def control_device(device_name):
    """远程控制设备"""
    data = request.get_json()
    if not data:
        return jsonify({'code': 1, 'message': '缺少参数'}), 400

    status = data.get('status')
    value = data.get('value')
    source = data.get('source', 'remote')

    result = device_manager.set_device(device_name, status, value, source)
    return jsonify({'code': 0, 'message': '控制成功', 'data': result})


@api_bp.route('/devices/<device_name>/toggle', methods=['POST'])
def toggle_device(device_name):
    """切换设备开关"""
    data = request.get_json() or {}
    source = data.get('source', 'remote')
    result = device_manager.toggle_device(device_name, source)
    return jsonify({'code': 0, 'message': '切换成功', 'data': result})


@api_bp.route('/devices/light/brightness', methods=['POST'])
def set_light_brightness():
    """设置灯光亮度"""
    data = request.get_json()
    if not data or 'brightness' not in data:
        return jsonify({'code': 1, 'message': '缺少 brightness 参数'}), 400

    brightness = int(data['brightness'])
    source = data.get('source', 'remote')
    result = device_manager.set_light_brightness(brightness, source)
    return jsonify({'code': 0, 'message': '亮度设置成功', 'data': result})


# ============================================================
# 5. 传感器数据 API
# ============================================================

@api_bp.route('/sensor/current', methods=['GET'])
def get_current_sensor():
    """获取当前传感器读数"""
    return jsonify({
        'code': 0,
        'message': 'success',
        'data': sensor_simulator.get_current_reading(),
    })


@api_bp.route('/sensor/inject', methods=['POST'])
def inject_sensor_data():
    """注入真实传感器数据（硬件端调用）"""
    data = request.get_json()
    if not data or 'temperature' not in data:
        return jsonify({'code': 1, 'message': '缺少 temperature 参数'}), 400

    result = sensor_simulator.inject_reading(
        data['temperature'],
        data.get('humidity'),
    )
    return jsonify({'code': 0, 'message': '数据已注入', 'data': result})


# ============================================================
# 6. 历史数据查询与统计 API
# ============================================================

@api_bp.route('/history/temperature', methods=['GET'])
def get_temperature_history():
    """获取温度历史数据"""
    hours = request.args.get('hours', 24, type=int)
    interval = request.args.get('interval', 'auto')  # auto/hour/day

    since = datetime.utcnow() - timedelta(hours=hours)
    query = TemperatureLog.query.filter(TemperatureLog.recorded_at >= since)

    if interval == 'hour':
        # 按小时聚合
        logs = query.order_by(TemperatureLog.recorded_at).all()
        data = _aggregate_by_hour(logs, 'temperature')
    else:
        logs = query.order_by(TemperatureLog.recorded_at).all()
        data = [log.to_dict() for log in logs]

    # 统计信息
    temps = [d.get('temperature', 0) for d in data]
    stats = {
        'avg': round(sum(temps) / len(temps), 1) if temps else 0,
        'max': max(temps) if temps else 0,
        'min': min(temps) if temps else 0,
        'count': len(temps),
        'fan_activations': sum(1 for d in data if d.get('fan_activated')),
    }

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': data,
        'stats': stats,
    })


@api_bp.route('/history/devices', methods=['GET'])
def get_device_history():
    """获取设备状态历史数据"""
    hours = request.args.get('hours', 24, type=int)
    device_name = request.args.get('device')

    since = datetime.utcnow() - timedelta(hours=hours)
    query = DeviceStatusLog.query.filter(DeviceStatusLog.recorded_at >= since)

    if device_name:
        query = query.filter(DeviceStatusLog.device_name == device_name)

    logs = query.order_by(DeviceStatusLog.recorded_at.desc()).limit(500).all()

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': [log.to_dict() for log in logs],
        'total': len(logs),
    })


@api_bp.route('/history/devices/summary', methods=['GET'])
def get_device_summary():
    """设备状态统计摘要"""
    hours = request.args.get('hours', 24, type=int)
    since = datetime.utcnow() - timedelta(hours=hours)

    devices = ['light', 'door', 'window', 'fan', 'ac']
    summary = {}

    for device in devices:
        logs = DeviceStatusLog.query.filter(
            DeviceStatusLog.device_name == device,
            DeviceStatusLog.recorded_at >= since
        ).all()

        on_count = sum(1 for l in logs if l.status in ('on', 'unlocked', 'open'))
        off_count = sum(1 for l in logs if l.status in ('off', 'locked', 'closed'))

        summary[device] = {
            'total_logs': len(logs),
            'on_count': on_count,
            'off_count': off_count,
            'on_ratio': round(on_count / max(len(logs), 1) * 100, 1),
        }

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': summary,
    })


@api_bp.route('/dashboard', methods=['GET'])
def get_dashboard():
    """获取仪表盘综合数据"""
    # 当前传感器数据
    sensor = sensor_simulator.get_current_reading()

    # 当前设备状态
    devices = device_manager.get_all_status()

    # 最近访问记录
    recent_access = AccessLog.query.order_by(
        AccessLog.access_time.desc()
    ).limit(5).all()

    # 最近检测记录
    recent_detections = DetectionRecord.query.order_by(
        DetectionRecord.detected_at.desc()
    ).limit(5).all()

    # 授权人员统计
    total_persons = AuthorizedPerson.query.count()
    authorized_count = AuthorizedPerson.query.filter_by(is_authorized=True, is_fake=False).count()

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': {
            'sensor': sensor,
            'devices': devices,
            'recent_access': [a.to_dict() for a in recent_access],
            'recent_detections': [d.to_dict() for d in recent_detections],
            'person_stats': {
                'total': total_persons,
                'authorized': authorized_count,
                'unauthorized': total_persons - authorized_count,
            },
        }
    })


# ============================================================
# 7. 文件访问 API
# ============================================================

@api_bp.route('/files/<path:subdir>/<path:filename>', methods=['GET'])
def get_file(subdir, filename):
    """访问上传的文件"""
    directory = os.path.join(current_app.config['UPLOAD_FOLDER'], subdir)
    return send_from_directory(directory, filename)


# ============================================================
# 8. 灯光记录 API
# ============================================================

@api_bp.route('/lighting/history', methods=['GET'])
def get_lighting_history():
    """获取灯光操作历史记录"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    source = request.args.get('source')

    query = LightingRecord.query
    if source:
        query = query.filter(LightingRecord.source == source)

    pagination = query.order_by(LightingRecord.recorded_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    })


@api_bp.route('/lighting/stats', methods=['GET'])
def get_lighting_stats():
    """获取灯光使用统计数据"""
    hours = request.args.get('hours', 24, type=int)
    since = datetime.utcnow() - timedelta(hours=hours)

    records = LightingRecord.query.filter(
        LightingRecord.recorded_at >= since
    ).order_by(LightingRecord.recorded_at).all()

    if not records:
        return jsonify({
            'code': 0,
            'message': 'success',
            'data': {
                'total_operations': 0,
                'total_on_seconds': 0,
                'total_on_hours': 0,
                'total_energy_wh': 0,
                'avg_brightness': 0,
                'max_brightness': 0,
                'turn_on_count': 0,
                'turn_off_count': 0,
                'sources': {},
                'brightness_chart': [],
            }
        })

    turn_on_count = sum(1 for r in records if r.status == 'on')
    turn_off_count = sum(1 for r in records if r.status == 'off')
    on_records = [r for r in records if r.status == 'on' and r.brightness > 0]

    # 来源统计
    sources = {}
    for r in records:
        src = r.source or 'unknown'
        sources[src] = sources.get(src, 0) + 1

    # 亮度时序数据（用于图表）
    brightness_chart = [
        {
            'time': r.recorded_at.strftime('%Y-%m-%d %H:%M:%S'),
            'brightness': r.brightness,
            'status': r.status,
            'source': r.source,
        }
        for r in records
    ]

    # 统计总开灯时长和能耗
    total_on_seconds = 0
    total_energy_wh = 0.0
    last_on = None
    for r in records:
        if r.status == 'on' and r.brightness > 0:
            if last_on is None:
                last_on = r.recorded_at
        elif r.status == 'off' and last_on is not None:
            duration = (r.recorded_at - last_on).total_seconds()
            if 0 < duration < 86400:
                total_on_seconds += int(duration)
                # 查找对应的开灯记录来计算能耗
                on_record = next((x for x in reversed(records[:records.index(r)])
                                  if x.status == 'on' and x.brightness > 0), None)
                avg_brightness_val = on_record.brightness if on_record else r.brightness
                total_energy_wh += LightingRecord.calc_energy(avg_brightness_val, duration)
            last_on = None

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': {
            'total_operations': len(records),
            'total_on_seconds': total_on_seconds,
            'total_on_hours': round(total_on_seconds / 3600.0, 2),
            'total_energy_wh': round(total_energy_wh, 2),
            'avg_brightness': round(sum(r.brightness for r in on_records) / len(on_records), 1) if on_records else 0,
            'max_brightness': max(r.brightness for r in records) if records else 0,
            'turn_on_count': turn_on_count,
            'turn_off_count': turn_off_count,
            'sources': sources,
            'brightness_chart': brightness_chart,
        }
    })


@api_bp.route('/lighting/daily-summary', methods=['GET'])
def get_lighting_daily_summary():
    """获取灯光每日摘要统计"""
    days = request.args.get('days', 7, type=int)
    since = datetime.utcnow() - timedelta(days=days)

    records = LightingRecord.query.filter(
        LightingRecord.recorded_at >= since
    ).order_by(LightingRecord.recorded_at).all()

    # 按日期分组
    from collections import defaultdict
    daily = defaultdict(lambda: {
        'date': '',
        'total_on_seconds': 0,
        'turn_on_count': 0,
        'energy_wh': 0.0,
        'avg_brightness': 0,
        'brightness_values': [],
    })

    last_on = {}
    for r in records:
        day = r.recorded_at.strftime('%Y-%m-%d')
        daily[day]['date'] = day

        if r.status == 'on' and r.brightness > 0:
            daily[day]['turn_on_count'] += 1
            daily[day]['brightness_values'].append(r.brightness)
            if day not in last_on:
                last_on[day] = r.recorded_at
        elif r.status == 'off' and day in last_on and last_on[day] is not None:
            duration = (r.recorded_at - last_on[day]).total_seconds()
            if 0 < duration < 86400:
                daily[day]['total_on_seconds'] += int(duration)
                daily[day]['energy_wh'] += LightingRecord.calc_energy(
                    r.brightness, duration
                )
            last_on[day] = None

    result = []
    for day in sorted(daily.keys()):
        d = daily[day]
        brightness_vals = d['brightness_values']
        result.append({
            'date': day,
            'total_on_hours': round(d['total_on_seconds'] / 3600.0, 2),
            'turn_on_count': d['turn_on_count'],
            'energy_wh': round(d['energy_wh'], 2),
            'avg_brightness': round(sum(brightness_vals) / len(brightness_vals), 1) if brightness_vals else 0,
        })

    return jsonify({
        'code': 0,
        'message': 'success',
        'data': result,
    })


def _aggregate_by_hour(logs, field):
    """按小时聚合数据"""
    from collections import defaultdict
    hourly = defaultdict(list)

    for log in logs:
        dt = log.recorded_at
        hour_key = dt.strftime('%Y-%m-%d %H:00')
        val = getattr(log, field, None)
        if val is not None:
            hourly[hour_key].append(val)

    result = []
    for hour_key in sorted(hourly.keys()):
        values = hourly[hour_key]
        result.append({
            'time': hour_key,
            field: round(sum(values) / len(values), 1),
            'max': max(values),
            'min': min(values),
            'count': len(values),
        })
    return result
