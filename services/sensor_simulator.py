"""
智能家居系统 - 传感器数据模拟服务
在无实际硬件时，模拟温度传感器和门窗传感器数据
同时支持接收真实传感器数据
"""
import random
import threading
import time
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SensorSimulator:
    """传感器数据模拟器"""

    def __init__(self, app=None, interval=30):
        self.interval = interval  # 采样间隔（秒）
        self._running = False
        self._thread = None
        self._socketio = None
        self._db_logger = None
        self._device_manager = None
        self._temp_threshold = 28.0
        self._current_temp = 25.0
        self._current_humidity = 55.0
        self._app = app

        if app:
            self.init_app(app)

    def init_app(self, app):
        self._app = app

    def set_socketio(self, socketio):
        self._socketio = socketio

    def set_db_logger(self, logger_func):
        self._db_logger = logger_func

    def set_device_manager(self, dm):
        self._device_manager = dm

    def set_threshold(self, threshold):
        self._temp_threshold = threshold

    def start(self):
        """启动传感器模拟线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f'[Sensor] 传感器模拟器已启动 (间隔={self.interval}s)')

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        """模拟传感器数据采集循环"""
        hour = datetime.now().hour
        while self._running:
            try:
                # 模拟温度变化（基于时间）
                now_hour = datetime.now().hour
                # 日间温度高，夜间温度低
                base_temp = 25 + 5 * (1 + (now_hour - 12) / 12)  # 中午最高
                base_temp = max(20, min(33, base_temp))
                self._current_temp = round(base_temp + random.uniform(-1.5, 1.5), 1)

                # 湿度与温度负相关
                self._current_humidity = round(60 - (self._current_temp - 25) * 2 + random.uniform(-5, 5), 1)
                self._current_humidity = max(30, min(80, self._current_humidity))

                # 记录到数据库
                fan_activated = self._current_temp > self._temp_threshold
                if self._db_logger:
                    with self._app.app_context():
                        self._db_logger(self._current_temp, self._current_humidity, fan_activated)

                # 自动风扇控制
                if self._device_manager:
                    with self._app.app_context():
                        self._device_manager.auto_fan_control(self._current_temp, self._temp_threshold)

                # 推送实时数据
                if self._socketio:
                    self._socketio.emit('sensor_update', {
                        'temperature': self._current_temp,
                        'humidity': self._current_humidity,
                        'fan_activated': fan_activated,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'threshold': self._temp_threshold,
                    })

                logger.debug(f'[Sensor] T={self._current_temp}C H={self._current_humidity}%')

            except Exception as e:
                logger.error(f'[Sensor] 模拟数据生成失败: {e}')

            time.sleep(self.interval)

    def get_current_reading(self):
        """获取当前传感器读数"""
        return {
            'temperature': self._current_temp,
            'humidity': self._current_humidity,
            'fan_activated': self._current_temp > self._temp_threshold,
            'threshold': self._temp_threshold,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def set_temperature(self, temp):
        """手动设置温度（用于测试）"""
        self._current_temp = round(float(temp), 1)

    def inject_reading(self, temperature, humidity=None):
        """注入真实传感器数据"""
        self._current_temp = round(float(temperature), 1)
        if humidity is not None:
            self._current_humidity = round(float(humidity), 1)

        fan_activated = self._current_temp > self._temp_threshold
        if self._db_logger:
            self._db_logger(self._current_temp, self._current_humidity, fan_activated)

        if self._device_manager:
            self._device_manager.auto_fan_control(self._current_temp, self._temp_threshold)

        if self._socketio:
            self._socketio.emit('sensor_update', {
                'temperature': self._current_temp,
                'humidity': self._current_humidity,
                'fan_activated': fan_activated,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'threshold': self._temp_threshold,
            })

        return self.get_current_reading()


# 全局传感器模拟器实例
sensor_simulator = SensorSimulator()
