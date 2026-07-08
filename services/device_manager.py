"""
智能家居系统 - 设备管理服务
管理灯光、风扇、门、窗、空调等设备的状态
支持手动控制、远程控制、自动控制（基于传感器数据）
"""
import json
import threading
import time
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备状态管理器"""

    def __init__(self, app=None):
        self._state = {
            'light': {'on': False, 'brightness': 0},
            'fan': {'on': False, 'speed': 0},
            'door': {'locked': True},
            'window': {'closed': True},
            'ac': {'on': False, 'temp': 26},
        }
        self._lock = threading.Lock()
        self._callbacks = []  # 状态变化回调
        self._db_logger = None
        self._lighting_logger = None  # 灯光专用记录回调
        self._socketio = None
        self._last_light_on_time = None  # 记录最近一次开灯时间

        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app

    def set_socketio(self, socketio):
        self._socketio = socketio

    def set_db_logger(self, logger_func):
        self._db_logger = logger_func

    def set_lighting_logger(self, logger_func):
        self._lighting_logger = logger_func

    @property
    def state(self):
        with self._lock:
            return json.loads(json.dumps(self._state))

    def get_device(self, device_name):
        """获取单个设备状态"""
        with self._lock:
            return self._state.get(device_name, {})

    def set_device(self, device_name, status, value=None, source='manual', record_log=True):
        """
        设置设备状态
        device_name: light/fan/door/window/ac
        status: on/off/locked/unlocked/open/closed
        value: 亮度/风速/温度等数值
        source: manual/remote/auto/sensor/face_recognition
        """
        with self._lock:
            if device_name not in self._state:
                return {'error': f'未知设备: {device_name}'}

            old_state = json.loads(json.dumps(self._state[device_name]))

            # 根据设备类型更新状态
            if device_name == 'light':
                if status == 'on':
                    self._state['light']['on'] = True
                    if value is not None:
                        self._state['light']['brightness'] = int(value)
                    elif self._state['light']['brightness'] == 0:
                        self._state['light']['brightness'] = 50
                elif status == 'off':
                    self._state['light']['on'] = False
                    self._state['light']['brightness'] = 0

            elif device_name == 'fan':
                if status == 'on':
                    self._state['fan']['on'] = True
                    if value is not None:
                        self._state['fan']['speed'] = int(value)
                    elif self._state['fan']['speed'] == 0:
                        self._state['fan']['speed'] = 2
                elif status == 'off':
                    self._state['fan']['on'] = False
                    self._state['fan']['speed'] = 0

            elif device_name == 'door':
                if status in ('locked', 'unlocked'):
                    self._state['door']['locked'] = (status == 'locked')

            elif device_name == 'window':
                if status in ('open', 'closed'):
                    self._state['window']['closed'] = (status == 'closed')

            elif device_name == 'ac':
                if status == 'on':
                    self._state['ac']['on'] = True
                    if value is not None:
                        self._state['ac']['temp'] = int(value)
                elif status == 'off':
                    self._state['ac']['on'] = False

            new_state = self._state[device_name]

        # 记录日志
        if record_log and self._db_logger:
            self._db_logger(device_name, json.dumps(new_state),
                            str(value) if value is not None else status, source)

        # 灯光专用记录
        if device_name == 'light' and record_log and self._lighting_logger:
            now = datetime.utcnow()
            is_on = new_state.get('on', False)
            brightness = new_state.get('brightness', 0)
            self._lighting_logger(
                status='on' if is_on else 'off',
                brightness=brightness,
                source=source,
                recorded_at=now,
            )

        # 通过 WebSocket 推送状态变化
        if self._socketio:
            self._socketio.emit('device_update', {
                'device': device_name,
                'state': new_state,
                'source': source,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })

        logger.info(f'[Device] {device_name} -> {status} (value={value}, source={source})')

        return {
            'device': device_name,
            'status': status,
            'value': value,
            'state': new_state,
            'source': source,
        }

    def set_light_brightness(self, brightness, source='manual'):
        """设置灯光亮度 (0-100)"""
        brightness = max(0, min(100, int(brightness)))
        if brightness == 0:
            return self.set_device('light', 'off', brightness, source)
        else:
            return self.set_device('light', 'on', brightness, source)

    def toggle_device(self, device_name, source='manual'):
        """切换设备开关状态"""
        with self._lock:
            current = self._state.get(device_name, {})

        if device_name == 'light':
            if current.get('on'):
                return self.set_device('light', 'off', source=source)
            else:
                return self.set_device('light', 'on', source=source)
        elif device_name == 'fan':
            if current.get('on'):
                return self.set_device('fan', 'off', source=source)
            else:
                return self.set_device('fan', 'on', source=source)
        elif device_name == 'door':
            if current.get('locked'):
                return self.set_device('door', 'unlocked', source=source)
            else:
                return self.set_device('door', 'locked', source=source)
        elif device_name == 'window':
            if current.get('closed'):
                return self.set_device('window', 'open', source=source)
            else:
                return self.set_device('window', 'closed', source=source)
        elif device_name == 'ac':
            if current.get('on'):
                return self.set_device('ac', 'off', source=source)
            else:
                return self.set_device('ac', 'on', source=source)

    def auto_fan_control(self, temperature, threshold=28.0):
        """自动风扇控制：温度超过阈值时自动开启风扇"""
        if temperature > threshold:
            if not self._state['fan']['on']:
                self.set_device('fan', 'on', value=2, source='auto')
                return True
        else:
            if self._state['fan']['on']:
                self.set_device('fan', 'off', source='auto')
                return True
        return False

    def get_all_status(self):
        """获取所有设备状态"""
        return self.state


# 全局设备管理器实例
device_manager = DeviceManager()
