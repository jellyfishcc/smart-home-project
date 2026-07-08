"""
智能家居系统 - 数据库模型
使用 SQLAlchemy ORM 定义所有数据表
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class AuthorizedPerson(db.Model):
    """授权人员表 - 管理门禁授权人员信息"""
    __tablename__ = 'authorized_persons'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, comment='姓名')
    employee_id = db.Column(db.String(50), unique=True, nullable=False, comment='工号/编号')
    role = db.Column(db.String(50), default='成员', comment='角色/身份')
    is_authorized = db.Column(db.Boolean, default=True, comment='是否授权')
    is_fake = db.Column(db.Boolean, default=False, comment='是否为假身份(用于测试2真1假)')
    face_image_path = db.Column(db.String(500), comment='人脸照片路径')
    face_encoding_path = db.Column(db.String(500), comment='人脸特征数据文件路径')
    phone = db.Column(db.String(20), comment='联系电话')
    department = db.Column(db.String(100), comment='部门')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    access_logs = db.relationship('AccessLog', backref='person', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'employee_id': self.employee_id,
            'role': self.role,
            'is_authorized': self.is_authorized,
            'is_fake': self.is_fake,
            'face_image_path': self.face_image_path,
            'phone': self.phone,
            'department': self.department,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class AccessLog(db.Model):
    """门禁访问日志表"""
    __tablename__ = 'access_logs'

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('authorized_persons.id'), nullable=True, comment='人员ID(未识别时为空)')
    person_name = db.Column(db.String(100), comment='识别到的人员姓名')
    access_time = db.Column(db.DateTime, default=datetime.utcnow, comment='访问时间')
    access_result = db.Column(db.String(20), nullable=False, comment='结果: granted/denied/unknown')
    confidence = db.Column(db.Float, comment='识别置信度')
    image_path = db.Column(db.String(500), comment='抓拍照片路径')
    method = db.Column(db.String(50), default='face_recognition', comment='开门方式')
    detail = db.Column(db.String(500), comment='详细信息')

    def to_dict(self):
        return {
            'id': self.id,
            'person_id': self.person_id,
            'person_name': self.person_name,
            'access_time': self.access_time.strftime('%Y-%m-%d %H:%M:%S') if self.access_time else None,
            'access_result': self.access_result,
            'confidence': round(self.confidence, 2) if self.confidence else None,
            'image_path': self.image_path,
            'method': self.method,
            'detail': self.detail,
        }


class TemperatureLog(db.Model):
    """温度记录表"""
    __tablename__ = 'temperature_logs'

    id = db.Column(db.Integer, primary_key=True)
    temperature = db.Column(db.Float, nullable=False, comment='温度值(摄氏度)')
    humidity = db.Column(db.Float, comment='湿度(%)')
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, comment='记录时间')
    fan_activated = db.Column(db.Boolean, default=False, comment='是否触发了风扇')

    def to_dict(self):
        return {
            'id': self.id,
            'temperature': round(self.temperature, 1),
            'humidity': round(self.humidity, 1) if self.humidity else None,
            'recorded_at': self.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if self.recorded_at else None,
            'fan_activated': self.fan_activated,
        }


class DeviceStatusLog(db.Model):
    """设备状态日志表 - 记录灯/门/窗/风扇的状态变化"""
    __tablename__ = 'device_status_logs'

    id = db.Column(db.Integer, primary_key=True)
    device_name = db.Column(db.String(50), nullable=False, comment='设备名称: light/door/window/fan/ac')
    status = db.Column(db.String(100), nullable=False, comment='状态JSON字符串')
    value = db.Column(db.String(100), comment='数值(如亮度、风速)')
    source = db.Column(db.String(50), default='manual', comment='操作来源: manual/auto/sensor/remote')
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, comment='记录时间')

    def to_dict(self):
        return {
            'id': self.id,
            'device_name': self.device_name,
            'status': self.status,
            'value': self.value,
            'source': self.source,
            'recorded_at': self.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if self.recorded_at else None,
        }


class DetectionRecord(db.Model):
    """物体检测记录表"""
    __tablename__ = 'detection_records'

    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(500), nullable=False, comment='原图路径')
    result_image_path = db.Column(db.String(500), comment='标注后图片路径')
    objects_detected = db.Column(db.Text, comment='检测到的物体JSON列表')
    object_count = db.Column(db.Integer, default=0, comment='检测到的物体总数')
    detected_at = db.Column(db.DateTime, default=datetime.utcnow, comment='检测时间')
    source = db.Column(db.String(50), default='upload', comment='来源: upload/camera/auto')
    triggered_action = db.Column(db.String(200), comment='触发的动作(如检测到灯泡后开灯)')

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'image_path': self.image_path,
            'result_image_path': self.result_image_path,
            'objects_detected': json.loads(self.objects_detected) if self.objects_detected else [],
            'object_count': self.object_count,
            'detected_at': self.detected_at.strftime('%Y-%m-%d %H:%M:%S') if self.detected_at else None,
            'source': self.source,
            'triggered_action': self.triggered_action,
        }


class LightingRecord(db.Model):
    """灯光记录表 - 专门记录灯光的开关、亮度、能耗等详细数据"""
    __tablename__ = 'lighting_records'

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(10), nullable=False, comment='状态: on/off')
    brightness = db.Column(db.Integer, default=0, comment='亮度 (0-100)')
    source = db.Column(db.String(50), default='manual', comment='操作来源: manual/remote/auto/auto_detection')
    duration_seconds = db.Column(db.Integer, default=0, comment='本次状态持续时长(秒)，关灯时计算')
    energy_wh = db.Column(db.Float, default=0.0, comment='本次能耗(瓦时)，按亮度比例估算')
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, comment='记录时间')
    last_on_time = db.Column(db.DateTime, comment='最近一次开灯时间，用于计算持续时长')

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'brightness': self.brightness,
            'source': self.source,
            'duration_seconds': self.duration_seconds,
            'energy_wh': round(self.energy_wh, 2) if self.energy_wh else 0,
            'recorded_at': self.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if self.recorded_at else None,
            'last_on_time': self.last_on_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_on_time else None,
        }

    @staticmethod
    def calc_energy(brightness, duration_seconds):
        """估算能耗：假设100%亮度对应60W，按比例计算瓦时"""
        max_power_w = 60.0
        power_w = max_power_w * (brightness / 100.0)
        return round(power_w * duration_seconds / 3600.0, 2)
