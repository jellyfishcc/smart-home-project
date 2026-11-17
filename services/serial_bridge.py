"""
智能家居系统 - 硬件串口通信层（transport + protocol）

职责边界
--------
只做「信息交换」，不做业务判断：

  1. 串口打开 / 断开自动重连 / 按行收发
  2. 解析两种格式：新协议 `@KIND NAME args...` 与旧固件的裸文本回执
  3. 同步命令：写出去 -> 等 ACK/NAK/回执 -> 超时重试
  4. 把板子主动上报的消息回调给订阅者
  5. 缓存「板子最近一次上报值」，供上层只读查询

不负责：设备状态机、数据库写入、WebSocket 推送 —— 那些由订阅回调在业务层做。
这样本层可以完全脱离 Flask 单独运行（scripts/serial_probe.py 就是这么用的）。

为什么写操作必须串行
--------------------
UNOII 的串口接收是「攒满一行再整体字符串比较」，没有分帧缓冲。`OPEN` 和
`QRAIN` 连发会被拼成 `OPENQRAIN`，两条都匹配不上。所以这里用 _tx_lock
把写操作串成严格的一问一答，并在每条命令之间留出最小间隔。

为什么打开串口等于板子复位
--------------------------
UNO 的 USB 转串口芯片在串口被打开时会拉低 DTR，ATmega328P 因此自动复位，
舵机回到 0°、固件重新打印启动横幅。所以每次连接成功都必须把 `@BOOT`
（或旧固件的 `SmartHome Ready`）当成「门已关、所有待确认命令作废」的硬信号。
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

try:
    import serial
    from serial.tools import list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:  # 没装 pyserial 时不炸，整个桥降级为「未连接」
    serial = None
    list_ports = None
    PYSERIAL_AVAILABLE = False

logger = logging.getLogger(__name__)

# 本层实现的协议版本；@BOOT 里的第一个字段由固件上报，用于后续能力协商
PROTOCOL_VERSION = 1
DEFAULT_BAUD = 9600

# 两条命令之间的最小间隔（秒）。旧固件每读一字节还 delay(2)，
# 7 字节的 `QRAIN\r\n` 约 14ms，留 50ms 足够且不会被用户感知。
MIN_COMMAND_GAP = 0.05

# 常见 Arduino / USB 转串口芯片的 VID，用于端口自动探测
_ARDUINO_VIDS = {
    0x2341,  # Arduino 官方
    0x2A03,  # Arduino.org
    0x1A86,  # CH340 / CH341（国产 UNO 兼容板最常见）
    0x10C4,  # CP210x
    0x0403,  # FTDI
    0x1B4F,  # SparkFun
}
_PORT_KEYWORDS = (
    'arduino', 'ch340', 'ch341', 'usb-serial', 'usb serial',
    'cp210', 'ft232', 'silicon labs', 'wchusbserial', 'usb2.0-serial',
)


# ============================================================
# 消息与回执
# ============================================================

@dataclass
class Message:
    """一条从板子读到的、已经归一化的消息"""
    kind: str                       # BOOT / ACK / NAK / EVT / DATA / PONG / LOG
    name: str = ''                  # 主体：命令名或设备名
    args: List[str] = field(default_factory=list)
    raw: str = ''                   # 原始文本，便于排查
    ts: float = field(default_factory=time.time)
    legacy: bool = False            # True 表示来自旧固件的裸文本

    def __str__(self):
        body = ' '.join([self.name] + self.args).strip()
        return '@%s%s' % (self.kind, (' ' + body) if body else '')


@dataclass
class CommandResult:
    """一次同步命令的最终结局：成功、被拒、或超时"""
    ok: bool
    command: str
    reply: Optional[Message] = None
    error: str = ''
    attempts: int = 0
    elapsed: float = 0.0

    def __bool__(self):
        return self.ok


class _Waiter:
    """一次命令的等待句柄，由读线程负责唤醒"""
    __slots__ = ('event', 'message')

    def __init__(self):
        self.event = threading.Event()
        self.message = None


# 旧固件（未加 @ 前缀）的裸文本 -> 归一化消息
# 这张表让本层可以同时对接「还没改过的固件」和「改过的新固件」
_LEGACY_EXACT = {
    'SmartHome Ready': ('BOOT', '', []),
    'Ready': ('BOOT', '', []),
    'OPEN OK': ('ACK', 'OPEN', []),
    'RAIN': ('DATA', 'RAIN', ['1']),
    'NORAIN': ('DATA', 'RAIN', ['0']),
    '密码正确': ('EVT', 'ACCESS', ['KEYPAD_OK']),
    '密码错误': ('EVT', 'ACCESS', ['KEYPAD_FAIL']),
    '自动关门': ('EVT', 'DOOR', ['CLOSED']),
}
_LEGACY_PREFIX = (
    ('按键:', ('LOG', 'KEY', [])),
)


def parse_line(line):
    """
    把一行文本解析成 Message；空行返回 None。

    @ACK OPEN               -> ACK  OPEN
    @EVT DOOR OPEN          -> EVT  DOOR  [OPEN]
    @DATA ENV 253 61 1 0    -> DATA ENV   [253, 61, 1, 0]
    @BOOT 1                 -> BOOT       [1]
    OPEN OK                 -> ACK  OPEN          (旧固件)
    RAIN / NORAIN           -> DATA RAIN  [1]/[0] (旧固件)
    密码正确 / 自动关门      -> EVT  ...           (旧固件)

    其余无法识别的行统一归为 LOG，只用于人工查看，不参与任何状态判断。
    """
    text = line.strip()
    if not text:
        return None

    if text.startswith('@'):
        parts = text[1:].split()
        if not parts:
            return Message('LOG', raw=line)
        kind = parts[0].upper()
        # BOOT / PONG 后面全是数据，没有「名字」这一层
        if kind in ('BOOT', 'PONG'):
            return Message(kind, '', parts[1:], line)
        name = parts[1].upper() if len(parts) > 1 else ''
        return Message(kind, name, parts[2:], line)

    if text in _LEGACY_EXACT:
        kind, name, args = _LEGACY_EXACT[text]
        return Message(kind, name, list(args), line, legacy=True)

    for prefix, (kind, name, _) in _LEGACY_PREFIX:
        if text.startswith(prefix):
            return Message(kind, name, [text[len(prefix):].strip()], line, legacy=True)

    return Message('LOG', '', [], line)


# ============================================================
# 端口探测
# ============================================================

def list_serial_ports():
    """列出本机串口，附带用于自动探测的评分"""
    if not PYSERIAL_AVAILABLE:
        return []
    ports = []
    for p in list_ports.comports():
        desc = (p.description or '').strip()
        hwid = (p.hwid or '').strip()
        score = 0
        if p.vid in _ARDUINO_VIDS:
            score += 10
        low = (desc + ' ' + hwid).lower()
        if any(kw in low for kw in _PORT_KEYWORDS):
            score += 5
        ports.append({
            'device': p.device,
            'description': desc,
            'hwid': hwid,
            'vid': p.vid,
            'pid': p.pid,
            'score': score,
        })
    ports.sort(key=lambda x: (-x['score'], x['device']))
    return ports


def autodetect_port():
    """挑一个最像 Arduino 的串口；找不到返回空串"""
    for p in list_serial_ports():
        if p['score'] > 0:
            return p['device']
    return ''


# ============================================================
# 通信桥
# ============================================================

class SerialBridge:
    """
    一块 Arduino 的串口通信桥。每个实例对应一条串口，两块板就建两个实例。

    典型用法::

        bridge = SerialBridge(port='COM3', baudrate=9600)
        bridge.on_event(lambda m: print('事件', m))
        bridge.on_data(lambda m: print('数据', m))
        bridge.start()

        r = bridge.open_door()        # 阻塞到收到 ACK 或超时
        if r:
            print('已受理', r.reply)

        rain = bridge.query_rain()    # True / False / None
        bridge.stop()
    """

    def __init__(self,
                 port: str = '',
                 baudrate: int = DEFAULT_BAUD,
                 *,
                 cmd_timeout: float = 0.3,
                 retries: int = 2,
                 boot_wait: float = 2.5,
                 heartbeat_interval: float = 3.0,
                 offline_timeout: float = 10.0,
                 rain_poll_interval: float = 30.0,
                 reconnect_delay: float = 2.0,
                 read_timeout: float = 0.2):
        self.port = port
        self.baudrate = int(baudrate)
        self.cmd_timeout = float(cmd_timeout)
        self.retries = max(0, int(retries))
        self.boot_wait = float(boot_wait)
        self.heartbeat_interval = float(heartbeat_interval)
        self.offline_timeout = float(offline_timeout)
        self.rain_poll_interval = float(rain_poll_interval)
        self.reconnect_delay = float(reconnect_delay)
        self.read_timeout = float(read_timeout)

        self._serial = None
        self._port_actual = ''
        self._lock = threading.RLock()          # 保护 pending / 状态字段
        self._tx_lock = threading.Lock()        # 保证串口写操作严格串行
        self._stop = threading.Event()
        self._running = False
        self._threads = []
        self._open_failures = 0

        self._pending = {}                      # 命令名 -> _Waiter
        self._event_handlers = []
        self._data_handlers = []

        self._connected = False
        self._last_rx = 0.0
        self._opened_at = 0.0
        self._boot_seen = True                  # 注入传输层（测试）时视为已启动
        self._boot_count = 0
        self._proto_version = ''
        self._fw_version = ''
        self._reported = {}                     # 板子最近一次上报值（只读镜像）

        self._counters = {
            'rx_lines': 0,
            'tx_cmds': 0,
            'timeouts': 0,
            'bad_lines': 0,
            'reconnects': 0,
        }

    # ---------------- 订阅 ----------------

    def on_event(self, handler: Callable[[Message], None]):
        """订阅板子主动上报的状态事件（EVT / BOOT / NAK）"""
        self._event_handlers.append(handler)

    def on_data(self, handler: Callable[[Message], None]):
        """订阅传感器数据（DATA / PONG）"""
        self._data_handlers.append(handler)

    # ---------------- 生命周期 ----------------

    def start(self):
        if not PYSERIAL_AVAILABLE:
            logger.error('[Serial] 未安装 pyserial，串口通信层不可用；'
                         '执行 pip install pyserial 后重试')
            return False
        if self._running:
            return True

        self._stop.clear()
        self._running = True
        for target, name in ((self._reader_loop, 'serial-reader'),
                             (self._scheduler_loop, 'serial-scheduler')):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        logger.info('[Serial] 通信层已启动（端口=%s，波特率=%d）',
                    self.port or '自动探测', self.baudrate)
        return True

    def stop(self):
        self._stop.set()
        self._running = False
        with self._lock:
            ser, self._serial = self._serial, None
            self._connected = False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=1.5)
        self._threads.clear()
        logger.info('[Serial] 通信层已停止')

    # ---------------- 对外命令 ----------------

    def _wait_boot(self):
        """
        打开串口会让板子复位，bootloader 阶段写进去的字节会被吞掉。

        所以连上之后的第一条命令必须等到启动横幅（@BOOT / SmartHome Ready），
        最多等 boot_wait 秒；等不到也照发，避免永远卡死。
        """
        if self._boot_seen or self.boot_wait <= 0:
            return
        deadline = self._opened_at + self.boot_wait
        while not self._boot_seen and not self._stop.is_set():
            remain = deadline - time.time()
            if remain <= 0:
                logger.debug('[Serial] 等待启动横幅超时，仍继续发送')
                return
            self._stop.wait(min(0.05, remain))

    def send(self, name: str, *args, expect_reply: bool = True,
             timeout: Optional[float] = None, retries: Optional[int] = None):
        """
        发一条命令并等回执。返回 CommandResult，永远不抛异常。

        expect_reply=False 时写完立即返回，用于不需要回执的广播型命令。
        注意：所有命令都必须是幂等的，因为超时会重发。
        """
        command = name.upper()
        # 只在「既没装 pyserial 又没有可用串口句柄」时报错，
        # 这样测试或自定义传输层可以注入 _serial 直接复用本层逻辑
        if self._serial is None and not PYSERIAL_AVAILABLE:
            return CommandResult(False, command, error='pyserial 未安装')

        self._wait_boot()

        payload = ' '.join([command] + [str(a) for a in args]) + '\n'
        attempts = (self.retries if retries is None else max(0, int(retries))) + 1
        timeout = self.cmd_timeout if timeout is None else float(timeout)
        started = time.time()
        last_error = ''

        for attempt in range(1, attempts + 1):
            waiter = _Waiter()

            # 写操作串行化，避免两条命令在固件的行缓冲里粘连
            with self._tx_lock:
                with self._lock:
                    if self._serial is None:
                        return CommandResult(False, command, error='串口未连接',
                                             attempts=attempt,
                                             elapsed=time.time() - started)
                    self._pending[command] = waiter
                try:
                    self._serial.write(payload.encode('ascii', errors='ignore'))
                    self._serial.flush()
                    with self._lock:
                        self._counters['tx_cmds'] += 1
                except Exception as exc:
                    with self._lock:
                        self._pending.pop(command, None)
                    self._handle_disconnect(exc)
                    return CommandResult(False, command, error='写入失败: %s' % exc,
                                         attempts=attempt,
                                         elapsed=time.time() - started)

                if not expect_reply:
                    with self._lock:
                        self._pending.pop(command, None)
                    return CommandResult(True, command, attempts=attempt,
                                         elapsed=time.time() - started)

                got = waiter.event.wait(timeout)

            if got:
                msg = waiter.message
                if msg is None:  # 等待期间连接断开
                    return CommandResult(False, command, error='连接已断开',
                                         attempts=attempt,
                                         elapsed=time.time() - started)
                ok = msg.kind != 'NAK'
                return CommandResult(
                    ok, command, reply=msg,
                    error='' if ok else '被拒绝: %s' % ' '.join(msg.args),
                    attempts=attempt, elapsed=time.time() - started,
                )

            last_error = '超时 %.0fms 未收到回执' % (timeout * 1000)
            with self._lock:
                self._pending.pop(command, None)
                self._counters['timeouts'] += 1
            if attempt < attempts:
                logger.debug('[Serial] %s 第 %d 次超时，重试', command, attempt)
                self._stop.wait(MIN_COMMAND_GAP)

        return CommandResult(False, command, error=last_error,
                             attempts=attempts, elapsed=time.time() - started)

    def open_door(self):
        """请求开门。注意 ok=True 只代表「固件受理了」，不代表门扇到位。"""
        return self.send('OPEN')

    def close_door(self):
        """请求关门（需要固件支持 CLOSE；旧固件会返回超时）"""
        return self.send('CLOSE')

    def query_rain(self):
        """查询雨滴状态：True=有雨 / False=无雨 / None=没问到"""
        result = self.send('QRAIN')
        if not result.ok or result.reply is None:
            return None
        args = result.reply.args
        if not args:
            return None
        flag = args[0].upper()
        if flag in ('1', 'RAIN', 'TRUE'):
            return True
        if flag in ('0', 'NORAIN', 'FALSE'):
            return False
        return None

    def ping(self):
        """心跳探测，返回往返毫秒数；失败返回 None"""
        result = self.send('PING', retries=0)
        if not result.ok:
            return None
        return round(result.elapsed * 1000, 1)

    # ---------------- 状态查询 ----------------

    @property
    def connected(self):
        with self._lock:
            return self._connected

    @property
    def reported(self):
        """板子最近一次上报值的只读快照"""
        with self._lock:
            return dict(self._reported)

    def status(self):
        with self._lock:
            return {
                'available': PYSERIAL_AVAILABLE,
                'running': self._running,
                'connected': self._connected,
                'port': self._port_actual or self.port,
                'baudrate': self.baudrate,
                'protocol': self._proto_version or 'legacy',
                'firmware': self._fw_version,
                'boot_count': self._boot_count,
                'last_rx_ago': round(time.time() - self._last_rx, 2) if self._last_rx else None,
                'reported': dict(self._reported),
                'counters': dict(self._counters),
            }

    # ---------------- 内部：串口线程 ----------------

    def _reader_loop(self):
        while not self._stop.is_set():
            if self._serial is None:
                if not self._try_open():
                    self._stop.wait(self.reconnect_delay)
                    continue

            try:
                raw = self._serial.readline()
            except Exception as exc:
                self._handle_disconnect(exc)
                continue

            if raw:
                self._handle_raw(raw)
            else:
                self._check_liveness()

        # 退出前收尾
        with self._lock:
            ser, self._serial = self._serial, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _try_open(self):
        port = self.port or autodetect_port()
        if not port:
            self._note_open_failure('未找到可用串口')
            return False

        if not self.port:
            logger.info('[Serial] 自动探测到串口 %s', port)

        try:
            ser = serial.Serial(
                port=port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.read_timeout,
                write_timeout=1.0,
            )
        except Exception as exc:
            self._note_open_failure('打开 %s 失败: %s' % (port, exc))
            return False

        # 打开端口会拉低 DTR 触发复位，bootloader 阶段可能有残留字节，先清掉
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        self._open_failures = 0
        with self._lock:
            self._serial = ser
            self._port_actual = port
            self._connected = True
            self._last_rx = time.time()
            self._opened_at = time.time()
            self._boot_seen = False             # 板子正在复位，等横幅
            self._proto_version = ''
            self._counters['reconnects'] += 1

        logger.info('[Serial] %s 已打开，等待启动横幅（复位约 %.1fs）', port, self.boot_wait)
        return True

    def _note_open_failure(self, reason):
        """
        打不开端口时不要每 2 秒刷一条警告。

        没插板子是很常见的常态，首次和每 30 次（约 1 分钟）提示一次即可，
        其余降到 debug，避免把日志刷满。
        """
        self._open_failures += 1
        if self._open_failures == 1 or self._open_failures % 30 == 0:
            logger.warning('[Serial] %s（第 %d 次尝试，%s）',
                           reason, self._open_failures,
                           '可用 SMART_HOME_SERIAL_PORT 指定端口')
        else:
            logger.debug('[Serial] %s（第 %d 次）', reason, self._open_failures)

    def _handle_raw(self, raw):
        text = raw.decode('utf-8', errors='replace').rstrip('\r\n')
        if not text.strip():
            return

        msg = parse_line(text)
        if msg is None:
            return

        with self._lock:
            self._counters['rx_lines'] += 1
            self._last_rx = time.time()
            if not self._connected:
                self._connected = True
            # 只把「完全没认出来的行」算坏行；按键这类已知日志不算
            if msg.kind == 'LOG' and not msg.name:
                self._counters['bad_lines'] += 1

        self._update_cache(msg)
        fulfilled = self._fulfill(msg)

        # 认不出来的杂日志只留给人看，不往外发
        if msg.kind == 'LOG' and not msg.name:
            return

        # 已被某条命令的等待者吃掉的数据，不再重复通知订阅者
        if fulfilled and msg.kind in ('ACK', 'NAK', 'PONG'):
            return

        self._dispatch(msg)

    def _update_cache(self, msg):
        with self._lock:
            if msg.kind == 'BOOT':
                self._boot_count += 1
                self._boot_seen = True
                self._proto_version = msg.args[0] if msg.args else 'legacy'
                self._fw_version = msg.args[1] if len(msg.args) > 1 else ''
                # 复位 = 板子回到了初始物理状态，之前的读数与意图全部作废
                self._reported = {}
                self._reported['door'] = 'CLOSED'
            elif msg.kind == 'EVT' and msg.name == 'DOOR':
                self._reported['door'] = (msg.args[0].upper() if msg.args else 'UNKNOWN')
            elif msg.kind == 'DATA' and msg.name == 'RAIN':
                self._reported['rain'] = (msg.args[0] == '1') if msg.args else None
            elif msg.kind == 'DATA' and msg.name == 'ENV':
                self._reported['env'] = list(msg.args)

    def _fulfill(self, msg):
        """把回执交给正在等待的命令；返回是否有人接"""
        key = None
        if msg.kind in ('ACK', 'NAK'):
            key = msg.name
        elif msg.kind == 'PONG':
            key = 'PING'
        elif msg.kind == 'DATA' and msg.name == 'RAIN':
            key = 'QRAIN'   # 旧固件用一个 DATA 行回答 QRAIN
        if not key:
            return False

        with self._lock:
            waiter = self._pending.pop(key, None)
        if waiter is None:
            return False
        waiter.message = msg
        waiter.event.set()
        return True

    def _dispatch(self, msg):
        handlers = self._data_handlers if msg.kind in ('DATA', 'PONG') else self._event_handlers
        for handler in list(handlers):
            try:
                handler(msg)
            except Exception:
                # 订阅方抛异常不能弄死读线程
                logger.exception('[Serial] 消息回调异常: %s', msg)

    def _check_liveness(self):
        # 固件不会主动说话，只有心跳/轮询才有流量；两者都关掉时不做离线判定
        if self.heartbeat_interval <= 0 and self.rain_poll_interval <= 0:
            return
        # 判离线要按「预期多久应该有一次上行」来算，否则轮询周期比超时还长，
        # 板子明明活着也会被反复判成离线
        keepalive = self.heartbeat_interval or self.rain_poll_interval
        window = max(self.offline_timeout, keepalive * 3)
        with self._lock:
            silent = time.time() - self._last_rx
            if self._connected and silent > window:
                self._connected = False
                stale = True
            else:
                stale = False
        if stale:
            logger.warning('[Serial] 超过 %.0fs 无上行数据，标记为离线', silent)
            self._dispatch(Message('EVT', 'LINK', ['OFFLINE'], legacy=True))

    def _handle_disconnect(self, exc):
        with self._lock:
            ser, self._serial = self._serial, None
            was_connected = self._connected
            self._connected = False
            pending = list(self._pending.values())
            self._pending.clear()
        # 让所有正在等待的命令立刻失败，不用干等到超时
        for waiter in pending:
            waiter.message = None
            waiter.event.set()
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        if was_connected:
            logger.warning('[Serial] 串口断开: %s', exc)
            self._dispatch(Message('EVT', 'LINK', ['LOST'], legacy=True))

    # ---------------- 内部：定时任务 ----------------

    def _send_quiet(self, command):
        """定时任务专用：已经有同名命令在路上就跳过，避免两条命令抢同一个等待槽"""
        with self._lock:
            if command in self._pending:
                return
        self.send(command, retries=0)

    def _scheduler_loop(self):
        tick = 0.2
        next_heartbeat = time.time() + self.heartbeat_interval if self.heartbeat_interval > 0 else 0
        next_rain = time.time() + self.rain_poll_interval if self.rain_poll_interval > 0 else 0

        while not self._stop.is_set():
            if self._stop.wait(tick):
                break
            if self._serial is None:
                continue
            # 板子刚复位时还在 bootloader 里，此刻发命令会被吞掉。
            # 这里只按时间等，绝不依赖启动横幅——有些 CH340 板子打开串口
            # 并不复位，横幅早在开机时就打完了，死等它等于永不发心跳。
            if not self._boot_seen and time.time() - self._opened_at < self.boot_wait:
                continue

            # PING 只有升级过的新固件才认；旧固件收到一声不响，链路会被误判成离线。
            # QRAIN 新旧都认，所以「不确定对方是谁」时一律用它保活：
            # 既拿到回执证明链路活着，又顺带刷新雨滴状态。
            keepalive = 'PING' if self._proto_version not in ('', 'legacy') else 'QRAIN'

            now = time.time()
            if next_heartbeat and now >= next_heartbeat:
                next_heartbeat = now + self.heartbeat_interval
                self._send_quiet(keepalive)

            if next_rain and now >= next_rain:
                next_rain = now + self.rain_poll_interval
                if keepalive != 'QRAIN':    # 心跳已经在轮询雨滴，不必重复发
                    self._send_quiet('QRAIN')


# 全局实例由 app.py 按配置决定是否启动。
# 环境板（UNOI）暂时没有实例：它的固件既不上报也不接收串口命令，
# 真接上只会连上又立刻判离线，反而误导前端。
door_bridge = SerialBridge()
