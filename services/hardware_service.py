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

from services.serial_bridge import PYSERIAL_AVAILABLE, SerialBridge, decode_env

logger = logging.getLogger(__name__)

# 固件里 OPEN_DURATION = 5000ms，这里多给 1 秒余量。
# 定时器只能标记自动关门未确认，不能推断实体门位置。
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
        self._startup_error = None

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
            self._startup_error = 'pyserial_missing'
            logger.warning('[Hardware] 未安装 pyserial，跳过硬件对接')
            return False

        cfg = self._app.config if self._app else {}
        started = False
        door_id, env_id = cfg.get('DOOR_USB_SERIAL', ''), cfg.get('ENVIRONMENT_USB_SERIAL', '')
        if door_id and door_id == env_id:
            self._startup_error = 'duplicate_board_mapping'
            return False

        # ---- 门禁板（UNO II）：SERIAL_ENABLED 控制，按 USB 身份连接 ----
        if cfg.get('SERIAL_ENABLED'):
            bridge = SerialBridge(
                port=cfg.get('SERIAL_PORT', ''),
                usb_serial=cfg.get('DOOR_USB_SERIAL', ''),
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

        # ---- 环境板（UNO I）：必须配置独立 USB 身份 ----
        self.env_bridge = self._start_env_bridge(cfg)

        if not started and self.env_bridge is None:
            return False

        self._running = True
        return True

    def _start_env_bridge(self, cfg):
        """
        环境板（UNO I）：独立一条串口，只收 @DATA ENV / @PONG，不参与门禁逻辑。

        USB Serial Number 必须显式配置，不允许按设备节点顺序猜测角色。
        """
        if not cfg.get('SERIAL_ENV_ENABLED'):
            return None
        if not cfg.get('ENVIRONMENT_USB_SERIAL'):
            self._startup_error = 'environment_usb_serial_mapping_required'
            return None
        port = cfg.get('SERIAL_ENV_PORT', '')
        bridge = SerialBridge(
            port=port,
            usb_serial=cfg.get('ENVIRONMENT_USB_SERIAL', ''),
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

    def set_fan(self, on):
        """发送明确 ON/OFF；ACK 表示接受，输出可由后续 EVT 校正。"""
        bridge = self.env_bridge
        if bridge is None:
            return self._skipped('环境板未连接')
        if not self._env_capable():
            return self._skipped('环境板固件不支持 FAN 命令')
        return self._command('FAN', lambda: bridge.send('FAN', 1 if on else 0),
                             bridge=bridge)

    def set_lamp(self, on, brightness=100):
        """
        灯带开关 + 亮度（0~100）。

        WS2812 只有亮度和通断，没有颜色；固件把 100% 封顶在 255 的 39%，
        因为 8 颗全白约 480mA，会顶到 UNO 的 USB 保险丝。
        """
        bridge = self.env_bridge
        if bridge is None:
            return self._skipped('环境板未连接')
        if not self._env_capable():
            return self._skipped('环境板固件不支持 LAMP 命令')

        level = max(0, min(100, int(brightness)))
        if on:
            sender = lambda: bridge.send('LAMP', 1, level)
        else:
            sender = lambda: bridge.send('LAMP', 0)
        return self._command('LAMP', sender, bridge=bridge)

    def set_fan_auto(self):
        return self._set_env_auto('FAN')

    def set_lamp_auto(self):
        return self._set_env_auto('LAMP')

    def _set_env_auto(self, name):
        bridge = self.env_bridge
        if bridge is None:
            return self._skipped('环境板未连接')
        # Older FAN parsers convert AUTO to integer zero. Require explicit capability.
        if bridge.status().get('firmware') != 'env-tristate-1':
            return self._skipped('AUTO 需要 env-tristate-1 UNOI 固件')
        return self._command(name, lambda: bridge.send(name, 'AUTO'), bridge=bridge)

    def _sync_env_mode(self, device, mode):
        setter = getattr(self._device_manager, 'set_control_mode', None)
        if setter:
            setter(device, mode)

    def _env_capable(self):
        """
        环境板固件是否支持 FAN/LAMP（只认打过 @BOOT 1 的新固件）。

        protocol 显示 legacy 有两种情况：板子还在复位、没发横幅；或者真是老固件。
        用 boot_count 区分：收到过横幅还叫 legacy，那才是老固件该跳过。
        老固件收到 FAN 会一声不响，硬等只会让接口卡 900ms。
        """
        if self.env_bridge is None:
            return False
        st = self.env_bridge.status()
        return not (st.get('protocol') == 'legacy' and st.get('boot_count'))

    # ---------------- 入站：板子 -> 软件 ----------------

    def _on_event(self, msg):
        self._last_event_at = time.time()
        self._remember(msg)
        try:
            if msg.kind == 'BOOT':
                # Boot reports a reset, not measured door position.
                self._cancel_auto_close()
                self._sync_door('reset')
                self._emit_status()

            elif msg.kind == 'EVT' and msg.name == 'DOOR':
                state = msg.args[0].upper() if msg.args else ''
                if state == 'OPEN':
                    self._sync_door('open_commanded')
                elif state == 'CLOSED':
                    self._cancel_auto_close()
                    self._sync_door('close_commanded')

            elif msg.kind == 'EVT' and msg.name == 'ACCESS':
                # 键盘开门是板子自己执行的，软件只负责跟上状态
                result = msg.args[0].upper() if msg.args else ''
                if result == 'KEYPAD_OK':
                    self._sync_door('open_commanded')
                    self._arm_auto_close()
                logger.info('[Hardware] 键盘验证结果: %s', result or '未知')

            elif msg.kind == 'EVT' and msg.name == 'LINK':
                self._sync_door('unknown')
                logger.warning('[Hardware] 链路状态: %s', ' '.join(msg.args))
                self._emit_status()

            elif msg.kind == 'NAK':
                logger.warning('[Hardware] 板子拒绝命令 %s: %s', msg.name, ' '.join(msg.args))

        except Exception:
            logger.exception('[Hardware] 处理事件失败: %s', msg)

    def _on_env_event(self, msg):
        """
        环境板的入站事件。

        两块板共用一个 HardwareService，这里只跟风扇/灯带，绝不碰门禁状态：
        如果复用 _on_event，环境板一复位就会被当成「门已关」。

        为什么要处理 @EVT FAN/LAMP：板子还有自治逻辑（温度到 30 开风扇、
        天黑开灯），它自己改了状态就得让页面跟上，否则两边各说各话。
        """
        try:
            if msg.kind == 'BOOT':
                # 复位后风扇停、灯带灭（setup() 的初始状态），软件状态跟着回零
                logger.info('[Hardware] 环境板复位，风扇/灯带状态回零')
                self._sync_env_mode('fan', 'auto')
                self._sync_env_mode('light', 'auto')
                self._sync_env_state(fan=False, lamp=False)
                self._emit_status()

            elif msg.kind == 'EVT' and msg.name == 'FAN':
                state = msg.args[0].upper() if msg.args else ''
                if state in ('ON', 'OFF'):
                    self._sync_env_state(fan=(state == 'ON'), event_at=msg.ts)

            elif msg.kind == 'EVT' and msg.name == 'LAMP':
                state = msg.args[0].upper() if msg.args else ''
                level = None
                if len(msg.args) > 1:
                    try:
                        level = int(msg.args[1])
                    except ValueError:
                        level = None
                if state in ('ON', 'OFF'):
                    self._sync_env_state(lamp=(state == 'ON'), brightness=level, event_at=msg.ts)

            elif msg.kind == 'EVT' and msg.name == 'CTL':
                if len(msg.args) >= 2:
                    mode, role = msg.args[:2]
                    if mode in ('AUTO', 'MANUAL_ON', 'MANUAL_OFF') and role in ('FAN', 'LAMP'):
                        self._sync_env_mode('fan' if role == 'FAN' else 'light', mode.lower())
                logger.info('[Hardware] 环境板控制模式: %s',
                            ' '.join(msg.args) or '-')

            elif msg.kind == 'EVT' and msg.name == 'LINK':
                from services.sensor_simulator import sensor_simulator
                sensor_simulator._reading_valid = False
                logger.warning('[Hardware] 环境板链路: %s', ' '.join(msg.args))

            elif msg.kind == 'NAK':
                logger.info('[Hardware] 环境板回绝 %s: %s', msg.name, ' '.join(msg.args))

        except Exception:
            logger.exception('[Hardware] 处理环境板事件失败: %s', msg)

    def _sync_env_state(self, fan=None, lamp=None, brightness=None, event_at=None):
        """
        把环境板的事实同步到软件状态（风扇/灯带）。

        source='hardware' 让 DeviceManager 跳过下发，否则会形成
        「命令 -> @EVT -> 命令」的死循环。只有真的变了才写，避免刷日志。
        """
        dm = self._device_manager
        if dm is None:
            return

        reporter = getattr(dm, 'record_environment_report', None)
        if reporter:
            def apply():
                if fan is not None:
                    reporter('fan', fan, event_at=event_at)
                if lamp is not None:
                    reporter('light', lamp, brightness=brightness, event_at=event_at)
            if self._app:
                with self._app.app_context():
                    apply()
            else:
                apply()
            return

        if fan is not None:
            current = dm.get_device('fan').get('on')
            if current != fan:
                logger.info('[Hardware] 同步风扇状态 -> %s', 'on' if fan else 'off')
                self._device_call('fan', 'on' if fan else 'off')

        if lamp is not None:
            current = dm.get_device('light')
            if lamp:
                want = int(brightness) if brightness else int(current.get('brightness') or 50)
                if not current.get('on') or int(current.get('brightness') or 0) != want:
                    logger.info('[Hardware] 同步灯光状态 -> on %s%%', want)
                    self._device_call('light', 'on', want)
            elif current.get('on'):
                logger.info('[Hardware] 同步灯光状态 -> off')
                self._device_call('light', 'off')

    def _device_call(self, device, status, value=None):
        if self._app:
            with self._app.app_context():
                self._device_manager.set_device(device, status, value=value,
                                                source='hardware')
        else:
            self._device_manager.set_device(device, status, value=value,
                                            source='hardware')

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
                    'valid': decode_env(msg.args) is not None,
                    'at': time.time(),
                }
                self._remember(msg)
                self._apply_env_reading(msg.args)

        except Exception:
            logger.exception('[Hardware] 处理数据失败: %s', msg)

    def _apply_env_reading(self, args):
        if self._app and not self._app.config.get('SERIAL_ENV_ENABLED'):
            return
        from services.sensor_simulator import sensor_simulator
        reading = decode_env(args)
        if reading is None:
            sensor_simulator._reading_valid = False
            if self._socketio:
                self._socketio.emit('sensor_update', {
                    'temperature': None, 'humidity': None, 'source': 'hardware',
                    'available': False, 'valid': False, 'fan_activated': None,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                })
            return
        temperature, humidity = reading

        if self._socketio:
            self._socketio.emit('sensor_update', {
                'temperature': round(temperature, 1),
                'humidity': round(humidity, 1),
                'source': 'hardware',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            })

        if self._app:
            with self._app.app_context():
                sensor_simulator.inject_reading(temperature, humidity, source='hardware')
        else:
            sensor_simulator.inject_reading(temperature, humidity, source='hardware')

    def _sync_door(self, state):
        """
        把板子的事实同步到软件状态。

        只在状态真的变了才写，避免每次心跳都往 device_status_logs 里灌重复行。
        source='hardware' 同时起两个作用：日志可追溯、且不会再回发命令。
        """
        if self._device_manager is None:
            return
        self._device_manager.set_door_command(state)

    # ---------------- 命令执行与兜底计时 ----------------

    def _command(self, name, sender, bridge=None, missing='硬件未连接'):
        """
        执行一条串口命令并整理成可直接塞进 JSON 的结果。

        bridge 默认走门禁板；环境板的 FAN/LAMP 显式传 env_bridge 进来。
        """
        bridge = self.door_bridge if bridge is None else bridge
        if bridge is None:
            return self._skipped(missing)

        try:
            result = sender()
        except Exception as exc:
            from services.serial_bridge import CommandResult
            result = CommandResult(False, name, error=str(exc))
        info = {
            'command': name,
            'ok': bool(result),
            'attempts': getattr(result, 'attempts', 0),
            'elapsed_ms': round(getattr(result, 'elapsed', 0.0) * 1000, 1),
            'error': getattr(result, 'error', '') or '',
            'via': 'serial',
        }
        reply = getattr(result, 'reply', None)
        if name in ('FAN', 'LAMP') and reply is not None:
            info['ack'] = {'kind': reply.kind, 'name': reply.name,
                           'args': list(reply.args), 'at': reply.ts}
        self._last_command = info
        if name in ('FAN', 'LAMP'):
            self._emit_status()

        if result:
            logger.info('[Hardware] %s 已下发（%d 次尝试，%.0fms）',
                        name, info['attempts'], info['elapsed_ms'])
            if name in ('OPEN', 'CLOSE'):
                self._sync_door(name.lower() + '_accepted')
            if name == 'OPEN':
                self._arm_auto_close()
        else:
            logger.warning('[Hardware] %s 下发失败: %s', name, info['error'])
            # Timeout may mean execution with a lost ACK; position stays unknown.
            if name == 'OPEN':
                self._sync_door('unknown')
        return info

    def _bridge_open(self):
        return self.door_bridge.open_door()

    @staticmethod
    def _skipped(reason):
        return {'command': '', 'ok': False, 'skipped': True,
                'attempts': 0, 'elapsed_ms': 0.0, 'error': reason, 'via': 'serial'}

    def _arm_auto_close(self):
        """Expire the expected motion window without inventing physical closure."""
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
        logger.info('[Hardware] 自动关门等待到期，位置仍未确认')
        self._sync_door('auto_close_unconfirmed')

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
        cfg = self._app.config if self._app else {}
        return {
            'mode': 'hardware' if cfg.get('SERIAL_ENABLED') or cfg.get('SERIAL_ENV_ENABLED') else ('mock' if cfg.get('SIMULATION_MODE', True) else 'unavailable'),
            'sensor_source': 'hardware' if cfg.get('SERIAL_ENV_ENABLED') else ('simulation' if cfg.get('SIMULATION_MODE', True) else 'unavailable'),
            'door_usb_serial': cfg.get('DOOR_USB_SERIAL') or None,
            'environment_enabled': bool(cfg.get('SERIAL_ENV_ENABLED')),
            'environment_usb_serial': cfg.get('ENVIRONMENT_USB_SERIAL') or None,
            'error': self._startup_error,
            'physical_position': 'unknown',
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
