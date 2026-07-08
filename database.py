"""
智能家居系统 - 数据库初始化
创建所有表并插入演示数据
"""
import os
import json
from datetime import datetime, timedelta
import random
from models import db, AuthorizedPerson, AccessLog, TemperatureLog, DeviceStatusLog, DetectionRecord, LightingRecord


def init_db(app):
    """初始化数据库"""
    with app.app_context():
        db.create_all()
        print('[DB] 数据库表已创建')

        # 如果没有数据，插入演示数据
        if AuthorizedPerson.query.count() == 0:
            _seed_authorized_persons()
            print('[DB] 已插入授权人员演示数据')

        if TemperatureLog.query.count() == 0:
            _seed_temperature_logs()
            print('[DB] 已插入温度演示数据')

        if DeviceStatusLog.query.count() == 0:
            _seed_device_logs()
            print('[DB] 已插入设备状态演示数据')

        if AccessLog.query.count() == 0:
            _seed_access_logs()
            print('[DB] 已插入门禁日志演示数据')

        if LightingRecord.query.count() == 0:
            _seed_lighting_records()
            print('[DB] 已插入灯光记录演示数据')


def _seed_authorized_persons():
    """插入授权人员 - 2真1假"""
    persons = [
        # 2个真实授权人员
        AuthorizedPerson(
            name='张明',
            employee_id='EMP001',
            role='管理员',
            is_authorized=True,
            is_fake=False,
            phone='13800138001',
            department='研发部',
        ),
        AuthorizedPerson(
            name='李华',
            employee_id='EMP002',
            role='成员',
            is_authorized=True,
            is_fake=False,
            phone='13800138002',
            department='运营部',
        ),
        # 1个假身份（未授权/伪造身份）
        AuthorizedPerson(
            name='未知人员',
            employee_id='FAKE001',
            role='无',
            is_authorized=False,
            is_fake=True,
            phone='无',
            department='无',
        ),
    ]
    for p in persons:
        db.session.add(p)
    db.session.commit()


def _seed_temperature_logs():
    """插入过去24小时的温度数据（每30分钟一条）"""
    now = datetime.utcnow()
    for i in range(48):
        recorded_at = now - timedelta(minutes=30 * (47 - i))
        # 模拟温度在 22-32 度之间波动
        base_temp = 25 + 4 * (1 + (i % 12 - 6) / 6)  # 日间波动
        temperature = round(base_temp + random.uniform(-1.5, 1.5), 1)
        humidity = round(45 + random.uniform(-10, 15), 1)
        fan_activated = temperature > 28.0

        log = TemperatureLog(
            temperature=temperature,
            humidity=humidity,
            recorded_at=recorded_at,
            fan_activated=fan_activated,
        )
        db.session.add(log)
    db.session.commit()


def _seed_device_logs():
    """插入设备状态历史数据"""
    now = datetime.utcnow()
    devices = ['light', 'door', 'window', 'fan', 'ac']

    for i in range(50):
        recorded_at = now - timedelta(hours=(49 - i))
        for device in devices:
            if device == 'light':
                brightness = random.choice([0, 30, 50, 70, 80, 100])
                status = 'on' if brightness > 0 else 'off'
                log = DeviceStatusLog(
                    device_name=device,
                    status=status,
                    value=str(brightness),
                    source=random.choice(['manual', 'remote', 'auto']),
                    recorded_at=recorded_at,
                )
            elif device == 'door':
                log = DeviceStatusLog(
                    device_name=device,
                    status=random.choice(['locked', 'unlocked']),
                    value=random.choice(['locked', 'unlocked']),
                    source=random.choice(['manual', 'face_recognition', 'remote']),
                    recorded_at=recorded_at,
                )
            elif device == 'window':
                log = DeviceStatusLog(
                    device_name=device,
                    status=random.choice(['closed', 'open']),
                    value=random.choice(['closed', 'open']),
                    source='sensor',
                    recorded_at=recorded_at,
                )
            elif device == 'fan':
                on = random.random() > 0.6
                log = DeviceStatusLog(
                    device_name=device,
                    status='on' if on else 'off',
                    value=str(random.choice([0, 1, 2, 3]) if on else 0),
                    source='auto',
                    recorded_at=recorded_at,
                )
            elif device == 'ac':
                on = random.random() > 0.5
                log = DeviceStatusLog(
                    device_name=device,
                    status='on' if on else 'off',
                    value=str(random.choice([24, 25, 26, 27]) if on else 0),
                    source='remote',
                    recorded_at=recorded_at,
                )
            db.session.add(log)
    db.session.commit()


def _seed_access_logs():
    """插入门禁访问日志"""
    now = datetime.utcnow()
    persons = AuthorizedPerson.query.all()

    for i in range(20):
        access_time = now - timedelta(hours=(19 - i))
        person = random.choice(persons)

        if person.is_authorized and not person.is_fake:
            result = 'granted'
            confidence = random.uniform(15, 50)  # LBPH 置信度越低越匹配
        elif person.is_fake:
            result = 'denied'
            confidence = random.uniform(80, 120)
        else:
            result = 'unknown'
            confidence = random.uniform(60, 100)

        log = AccessLog(
            person_id=person.id,
            person_name=person.name,
            access_time=access_time,
            access_result=result,
            confidence=round(confidence, 2),
            method='face_recognition',
            detail=f'人脸识别{"成功" if result == "granted" else "失败"}, 置信度={round(confidence, 2)}',
        )
        db.session.add(log)
    db.session.commit()


def _seed_lighting_records():
    """插入灯光操作记录 - 模拟过去24小时的灯光开关数据"""
    now = datetime.utcnow()
    sources = ['manual', 'manual', 'manual', 'remote', 'remote', 'auto_detection', 'auto']

    # 模拟多次开关灯场景（过去24小时每30分钟一条记录）
    for i in range(48):
        recorded_at = now - timedelta(minutes=30 * (47 - i))

        # 模拟作息规律：白天较亮，夜间较暗
        hour = recorded_at.hour
        if 18 <= hour <= 23:
            on_prob = 0.85
            brightness_range = (50, 100)
        elif 6 <= hour <= 8:
            on_prob = 0.5
            brightness_range = (30, 70)
        elif 9 <= hour <= 17:
            on_prob = 0.15
            brightness_range = (20, 50)
        else:
            on_prob = 0.05
            brightness_range = (10, 30)

        is_on = random.random() < on_prob
        brightness = random.randint(*brightness_range) if is_on else 0
        source = random.choice(sources)

        log = LightingRecord(
            status='on' if is_on else 'off',
            brightness=brightness,
            source=source,
            recorded_at=recorded_at,
        )
        db.session.add(log)
    db.session.commit()
