"""
智能家居系统 - 硬件对接服务（业务胶水层）

把「协议」翻译成「状态」，把「状态」翻译成「命令」。两端互不认识：

    DeviceManager ──open_door()/close_door()──> HardwareService ──OPEN/CLOSE──> SerialBridge
    DeviceManager <──set_device(source='hardware')── HardwareService <──@EVT/@DATA── SerialBridge

不负责：协议解析与串口收发（在 SerialBridge 里），业务规则（在 DeviceManager 里）。
所以这一层只做三件事：事件归位、命令转发、在线状态汇总。

为什么 source 必须是 'hardware'
------------------------------
板子自己开门（键盘输密码）会上报事件，我们据此更新软件状态；如果这次更新
又触发一次 OPEN 下发，就会形成 命令→事件→命令 的回环。DeviceManager 靠
source 判断来源，硬件回传的变更不再回发。
"""
import logging
import threading
import time
from collections import deque

from services.serial_bridge import PYSERIAL_AVAILABLE, SerialBridge

logger = logging.getLogger(__name__)

# 固件里 OPEN_DURATION = 5000ms，这里多给 1 秒余量。
# 正常情况下板子会主动上报「自动关门」，计时器只是丢包时的兜底。
DEFAULT_AUTO_CLOSE_GRACE = 6.0


class HardwareService:
    """门禁板（UNO II）+ 环境板（UNO I）的业务对接。

    两块板各占一条串口，各自一个 SerialBridge 实例，互不认识：
    门禁板走 OPEN/CLOSE/QRAIN，环境板走 QENV -> @DATA ENV。
    """

    def __init__(self):
        self._app = None
        self._socketio = None
        self._device_manager = None

        self.door_bridge = None
        self.env_bridge = None
        self._running = False

        self._lock = threading.Lock()
        self._auto_close_timer = None
        self._rain = None
        self._env = None
        self._last_event_at = 0.0
        self._recent = deque(maxlen=30)   # 最近事件，供调试与前端展示
        self._last_command = None

    # ---------------- 注入 ----------------

    def init_app(self, app):
        self._app = app

    def set_socketio(self, socketio):
        self._socketio = socketio

    def set_device_manager(self, dm):
        self._device_manager = dm

    # ---------------- 生命周期 ----------------

    def start(self):
        """按配置启动两块板；任意一块起来就算成功，失败只告警不影响其它功能"""
        if self._running:
            return True
        if not PYSERIAL_AVAILABLE:
            logger.warning('[Hardware] 未安装 pyserial，跳过硬件对接')
            return False

        cfg = self._app.config if self._app else {}
        started = False

        # ---- 门禁板（UNO II）：SERIAL_ENABLED 控制，行为和以前完全一致 ----
        if cfg.get('SERIAL_ENABLED'):
            bridge = SerialBridge(
                port=cfg.get('SERIAL_PORT', ''),
                baudrate=cfg.get('SERIAL_BAUD', 9600),
                cmd_timeout=cfg.get('SERIAL_CMD_TIMEOUT', 0.3),
                retries=cfg.get('SERIAL_CMD_RETRIES', 2),
                boot_wait=cfg.get('SERIAL_BOOT_WAIT', 2.5),
                heartbeat_interval=cfg.get('SERIAL_HEARTBEAT_INTERVAL', 3.0),
                offline_timeout=cfg.get('SERIAL_OFFLINE_TIMEOUT', 10.0),
                rain_poll_interval=cfg.get('SERIAL_RAIN_POLL_INTERVAL', 30.0),
                reconnect_delay=cfg.get('SERIAL_RECONNECT_DELAY', 2.0),
            )
            bridge.on_event(self._on_event)
            bridge.on_data(self._on_data)

            if not bridge.start():
                return False

            self.door_bridge = bridge
            started = True
            logger.info('[Hardware] 门禁板对接已启动')

        # ---- 环境板（UNO I）：可选件，没配端口就不启动 ----
        self.env_bridge = self._start_env_bridge(cfg)

        if self.env_bridge and self.door_bridge and not cfg.get('SERIAL_PORT'):
            # 门禁板端口留空时会在 reader 线程里自动探测，很可能摸到环境板那条口，
            # 两块板抢一个 COM 会互相踩。这里只提醒，不擅自改行为
            logger.warning('[Hardware] 门禁板端口为自动探测，可能与环境板抢同一个 COM；'
                           '建议显式设置 SMART_HOME_SERIAL_PORT')

        if not started and self.env_bridge is None:
            return False

        self._running = True
        return True

    def _start_env_bridge(self, cfg):
        """
        环境板（UNO I）：独立一条串口，只收 @DATA ENV / @PONG，不参与门禁逻辑。

        端口必须显式配置。留空时绝不退回自动探测 —— 自动探测会挑中门禁板那条口，
        两块板共用一个 COM 会互相踩，且打开串口会因 DTR 把对方复位。
        """
        if not cfg.get('SERIAL_ENV_ENABLED'):
            return None
        port = cfg.get('SERIAL_ENV_PORT', '')
        if not port:
            logger.warning('[Hardware] 环境板已启用但未配置环境板端口，跳过'
                           '（设 SMART_HOME_SERIAL_ENV_PORT=COM4）')
            return None

        bridge = SerialBridge(
            port=port,
            baudrate=cfg.get('SERIAL_BAUD', 9600),
            cmd_timeout=cfg.get('SERIAL_CMD_TIMEOUT', 0.3),
            retries=cfg.get('SERIAL_CMD_RETRIES', 2),
            boot_wait=cfg.get('SERIAL_ENV_BOOT_WAIT', 4.0),
            heartbeat_interval=cfg.get('SERIAL_HEARTBEAT_INTERVAL', 3.0),
            offline_timeout=cfg.get('SERIAL_OFFLINE_TIMEOUT', 10.0),
            rain_poll_interval=0,        # 环境板没有雨滴模块，别发 QRAIN
            env_poll_interval=cfg.get('SERIAL_ENV_POLL_INTERVAL', 10.0),
            reconnect_delay=cfg.get('SERIAL_RECONNECT_DELAY', 2.0),
        )
        bridge.on_event(self._on_env_event)
        bridge.on_data(self._on_data)

        if not bridge.start():
            return None
        logger.info('[Hardware] 环境板对接已启动（%s）', port)
        return bridge

    def shutdown(self):
        with self._lock:
            if self._auto_close_timer:
                self._auto_close_timer.cancel()
                self._auto_close_timer = None
        if self.door_bridge:
            self.door_bridge.stop()
        if self.env_bridge:
            self.env_bridge.stop()
        self.door_bridge = None
        self.env_bridge = None
        self._running = False

    # ---------------- 命令转发（供 DeviceManager 调用） ----------------

    def open_door(self):
        """下发开门，返回可直接塞进 JSON 的结果字典"""
        return self._command('OPEN', self._bridge_open)

    def close_door(self):
        """
        下发关门。

        旧固件没有 CLOSE 命令，收到也不回执，硬等只会让接口卡 900ms。
        这里按 @BOOT 上报的协议号判断能力，没升级过就直接跳过。
        """
        bridge = self.door_bridge
        if bridge is None:
            return self._skipped('硬件未连接')
        if bridge.status().get('protocol') == 'legacy':
            return self._skipped('固件不支持 CLOSE，等其自动关门')
        return self._command('CLOSE', bridge.close_door)

    # ---------------- 入站：板子 -> 软件 ----------------

    def _on_event(self, msg):
        self._last_event_at = time.time()
        self._remember(msg)
        try:
            if msg.kind == 'BOOT':
                # 复位后舵机回到 0°，门一定是关的；之前的计时也作废
                self._cancel_auto_close()
                self._sync_door('locked')
                self._emit_status()

            elif msg.kind == 'EVT' and msg.name == 'DOOR':
                state = msg.args[0].upper() if msg.args else ''
                if state == 'OPEN':
                    self._sync_door('unlocked')
                elif state == 'CLOSED':
                    self._cancel_auto_close()
                    self._sync_door('locked')

            elif msg.kind == 'EVT' and msg.name == 'ACCESS':
                # 键盘开门是板子自己执行的，软件只负责跟上状态
                result = msg.args[0].upper() if msg.args else ''
                if result == 'KEYPAD_OK':
                    self._sync_door('unlocked')
                    self._arm_auto_close()
                logger.info('[Hardware] 键盘验证结果: %s', result or '未知')

            elif msg.kind == 'EVT' and msg.name == 'LINK':
                logger.warning('[Hardware] 链路状态: %s', ' '.join(msg.args))
                self._emit_status()

            elif msg.kind == 'NAK':
                logger.warning('[Hardware] 板子拒绝命令 %s: %s', msg.name, ' '.join(msg.args))

        except Exception:
            logger.exception('[Hardware] 处理事件失败: %s', msg)

    def _on_env_event(self, msg):
        """
        环境板的链路事件只记日志，绝不碰门禁状态。

        两块板共用一个 HardwareService，如果这里复用 _on_event，环境板一复位
        就会被当成「门已关」，把门禁状态带偏。所以这里刻意什么都不做，
        只把异常链路打出来。
        """
        if msg.kind == 'EVT' and msg.name == 'LINK':
            logger.warning('[Hardware] 环境板链路: %s', ' '.join(msg.args))
        elif msg.kind == 'NAK':
            logger.info('[Hardware] 环境板回绝 %s: %s', msg.name, ' '.join(msg.args))

    def _on_data(self, msg):
        try:
            if msg.name == 'RAIN':
                self._rain = (msg.args[0] == '1') if msg.args else None
                self._remember(msg)
                self._emit_status()

            elif msg.name == 'ENV':
                # 环境板回传：温度、湿度都已放大 10 倍存整数，避免 AVR 上的浮点打印。
                # 第三个字段是固件的「DHT 读数有效」标志，0 表示现有数值还是上电默认值
                self._env = {
                    'args': list(msg.args),
                    'at': time.time(),
                }
                self._remember(msg)
                self._apply_env_reading(msg.args)

        except Exception:
            logger.exception('[Hardware] 处理数据失败: %s', msg)

    def _apply_env_reading(self, args):
        if len(args) < 2:
            return
        try:
            temperature = int(args[0]) / 10.0
            humidity = int(args[1]) / 10.0
        except ValueError:
            logger.warning('[Hardware] 环境数据格式不对: %s', args)
            return

        # 第三个字段是固件的「DHT 读数有效」标志。为 0 说明板子还没读成功过，
        # 这两个数是上电默认的 25/50，拿去覆盖页面只会让人误以为传感器挂了
        if len(args) >= 3 and args[2] == '0':
            logger.info('[Hardware] 环境板尚未读到 DHT，本次读数不上报')
            return

        from services.sensor_simulator import sensor_simulator

        if self._socketio:
            self._socketio.emit('sensor_update', {
                'temperature': round(temperature, 1),
                'humidity': round(humidity, 1),
                'source': 'hardware',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            })

        if self._app:
            with self._app.app_context():
                sensor_simulator.inject_reading(temperature, humidity)
        else:
            sensor_simulator.inject_reading(temperature, humidity)

    def _sync_door(self, state):
        """
        把板子的事实同步到软件状态。

        只在状态真的变了才写，避免每次心跳都往 device_status_logs 里灌重复行。
        source='hardware' 同时起两个作用：日志可追溯、且不会再回发命令。
        """
        if self._device_manager is None:
            return
        want_locked = (state == 'locked')
        if self._device_manager.get_device('door').get('locked') == want_locked:
            return

        logger.info('[Hardware] 同步门状态 -> %s', state)
        if self._app:
            with self._app.app_context():
                self._device_manager.set_device('door', state, source='hardware')
        else:
            self._device_manager.set_device('door', state, source='hardware')

    # ---------------- 命令执行与兜底计时 ----------------

    def _command(self, name, sender):
        bridge = self.door_bridge
        if bridge is None:
            return self._skipped('硬件未连接')

        result = sender()
        info = {
            'command': name,
            'ok': bool(result),
            'attempts': getattr(result, 'attempts', 0),
            'elapsed_ms': round(getattr(result, 'elapsed', 0.0) * 1000, 1),
            'error': getattr(result, 'error', '') or '',
            'via': 'serial',
        }
        self._last_command = info

        if result:
            logger.info('[Hardware] %s 已下发（%d 次尝试，%.0fms）',
                        name, info['attempts'], info['elapsed_ms'])
            if name == 'OPEN':
                self._arm_auto_close()
        else:
            logger.warning('[Hardware] %s 下发失败: %s', name, info['error'])
            # 命令没送到，软件状态不该停在「已开」，回滚成事实上的关
            if name == 'OPEN':
                self._sync_door('locked')
        return info

    def _bridge_open(self):
        return self.door_bridge.open_door()

    @staticmethod
    def _skipped(reason):
        return {'command': '', 'ok': False, 'skipped': True,
                'attempts': 0, 'elapsed_ms': 0.0, 'error': reason, 'via': 'serial'}

    def _arm_auto_close(self):
        """兜底：板子没上报自动关门时，按固件 5s 的节奏自己回锁"""
        delay = DEFAULT_AUTO_CLOSE_GRACE
        if self._app:
            delay = self._app.config.get('SERIAL_DOOR_AUTO_CLOSE', delay)

        with self._lock:
            if self._auto_close_timer:
                self._auto_close_timer.cancel()
            timer = threading.Timer(delay, self._auto_close_fire)
            timer.daemon = True
            self._auto_close_timer = timer
            timer.start()

    def _auto_close_fire(self):
        with self._lock:
            self._auto_close_timer = None
        logger.info('[Hardware] 兜底回锁计时到期')
        self._sync_door('locked')

    def _cancel_auto_close(self):
        with self._lock:
            if self._auto_close_timer:
                self._auto_close_timer.cancel()
                self._auto_close_timer = None

    # ---------------- 对外状态 ----------------

    def _remember(self, msg):
        self._recent.append({'at': time.strftime('%H:%M:%S'), 'text': str(msg)})

    def _emit_status(self):
        if self._socketio is None:
            return
        try:
            self._socketio.emit('hardware_status', self.status())
        except Exception:
            logger.exception('[Hardware] 推送硬件状态失败')

    def status(self):
        bridge_status = self.door_bridge.status() if self.door_bridge else None
        env_status = self.env_bridge.status() if self.env_bridge else None
        return {
            'enabled': bool(self._app.config.get('SERIAL_ENABLED')) if self._app else False,
            'running': self._running,
            'connected': bool(bridge_status and bridge_status.get('connected')),
            'rain': self._rain,
            'env': self._env,
            'door_bridge': bridge_status,
            'env_bridge': env_status,
            'last_command': self._last_command,
            'recent_events': list(self._recent),
        }


# 全局实例
hardware_service = HardwareService()
