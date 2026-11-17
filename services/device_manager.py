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
        self._hardware = None  # 硬件对接层（services/hardware_service.py）

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

    def set_hardware_bridge(self, hardware):
        """
        挂接硬件对接层。传 None 表示纯软件模式，所有控制只更新内存状态。

        对接层需要提供 open_door() / close_door() / set_fan() / set_lamp()，
        每个方法返回一个可 JSON 化的字典。
        DeviceManager 不关心底层是串口、MQTT 还是别的什么，也不 importing 它。
        """
        self._hardware = hardware

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
            now = datetime.now()
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

        # 出站：把状态变化翻译成硬件命令。
        # source == 'hardware' 表示这次变化本身就来自板子（例如键盘开门），
        # 再回发一次会形成 命令 -> 事件 -> 命令 的死循环，必须排除。
        hardware_info = None
        if source != 'hardware':
            hardware_info = self._dispatch_hardware(device_name, status, value)

        result = {
            'device': device_name,
            'status': status,
            'value': value,
            'state': new_state,
            'source': source,
        }
        if hardware_info is not None:
            result['hardware'] = hardware_info
        return result

    def _dispatch_hardware(self, device_name, status, value=None):
        """
        把设备状态变化转成硬件命令；返回 None 表示这次变化不需要下发。

        door  -> UNO II（舵机）：OPEN / CLOSE
        light -> UNO I（WS2812）：LAMP 1 <亮度> / LAMP 0
        fan   -> UNO I（风扇模块）：FAN 1 / FAN 0

        环境板这两条命令按「开即接管、关即交还」执行：
        下发「开」之后固件不再按温度/光线自治，一直保持到软件再发「关」；
        下发「关」之后固件立刻交还自治，下一轮就重新按传感器判断。
        所以这里下发是安全的，不会刚开就被板子改回去。
        """
        hw = self._hardware
        if hw is None:
            return None

        handler = None
        if device_name == 'door':
            if status == 'unlocked':
                handler = getattr(hw, 'open_door', None)
            elif status == 'locked':
                handler = getattr(hw, 'close_door', None)

        elif device_name == 'light':
            setter = getattr(hw, 'set_lamp', None)
            if setter is not None:
                if status == 'on':
                    # 亮度取这次下发的值，没带就用当前状态，避免传 None 把灯调暗
                    level = value if value is not None else self.get_device('light').get('brightness')
                    try:
                        level = int(level)
                    except (TypeError, ValueError):
                        level = 50
                    handler = lambda: setter(True, level)   # noqa: E731
                elif status == 'off':
                    handler = lambda: setter(False)         # noqa: E731

        elif device_name == 'fan':
            setter = getattr(hw, 'set_fan', None)
            if setter is not None and status in ('on', 'off'):
                handler = lambda: setter(status == 'on')    # noqa: E731

        if handler is None:
            return None

        try:
            return handler()
        except Exception as e:
            logger.warning(f'[Device] 硬件下发失败 ({device_name}->{status}): {e}')
            return {'ok': False, 'error': str(e), 'via': 'hardware'}

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
        """按温度阈值自动开关风扇。

        注意：**当前没有自动调用方**。温度→风扇的联动在环境板固件里用
        真实 DHT11 完成（30 开 / 28 关）；软件侧不再用模拟温度驱动执行器，
        否则页面上的假温度会让风扇自己开关。此方法仅供显式调用保留。
        """
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
