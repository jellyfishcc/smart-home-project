"""
智能家居系统 - 常驻摄像头采集与帧分发

设计要点（single-writer / multi-reader）：
  1. 全局只有一个采集线程持有 cv2.VideoCapture，所有消费者共用同一路设备。
  2. 写入端每帧替换引用（cap.read 返回新数组），绝不原地复用缓冲区。
  3. 读取端默认返回副本；只读热路径可传 copy=False，但调用方不得修改返回的数组。
  4. 用「最新帧 + 单调 seq」而不是队列：多消费者各自记忆 last_seq 即可去重，
     慢消费者不会堆积延迟，也不会把帧从别人手里抢走。
  5. 推理一律放在消费线程，采集线程不做任何模型计算。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 连续读帧失败多少次后重开设备
_MAX_READ_FAILURES = 5
# 每隔多少帧做一次画面健康检查（全黑/过暗）
_HEALTH_CHECK_EVERY = 5
# fps 统计窗口（秒）
_FPS_WINDOW = 1.0
# 判定画面过暗的均值阈值（0-255）
_BLANK_MEAN_THRESHOLD = 12.0


@dataclass(frozen=True)
class Frame:
    """一帧图像 + 元数据。image 只读，修改前请自行 copy。"""

    seq: int
    captured_at: float
    image: np.ndarray
    source: str

    @property
    def age(self) -> float:
        return time.time() - self.captured_at

    @property
    def shape(self) -> tuple:
        return tuple(self.image.shape)


class CameraStream:
    """常驻采集线程 + 最新帧分发。线程安全，读写分离。"""

    def __init__(self, source=0, history=0, reconnect_delay=2.0, name='camera'):
        """
        source: 0 / '/dev/video0' 等 OpenCV 可接受的设备标识
        history: 环形缓冲保留的帧数，0 表示不保留（哨兵需要回溯时再开）
        reconnect_delay: 读帧失败后重开设备的间隔（秒）
        """
        self._source = source
        self._history_size = max(0, int(history))
        self._reconnect_delay = float(reconnect_delay)
        self._name = name

        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._seq = 0
        self._listeners: list[Callable[[Frame], None]] = []
        self._history: deque[Frame] = deque(maxlen=self._history_size or 1)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cap = None
        self._error: str | None = None
        self._fps = 0.0
        self._fps_mark = (0.0, 0)
        self._frame_count = 0
        self._dark = False
        self._last_mean: float | None = None

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> bool:
        """启动采集线程。已在运行则返回 False。"""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f'{self._name}-capture', daemon=True)
        self._thread.start()
        logger.info('[Camera] 采集线程已启动 (source=%s)', self._source)
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """停止采集并释放设备。会唤醒所有等待中的消费者。"""
        self._stop_event.set()
        with self._cond:
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        logger.info('[Camera] 采集线程已停止')

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_source(self, source) -> bool:
        """在未启动时切换设备标识。运行中切换请先 stop()。"""
        if self.running:
            return False
        self._source = source
        self._error = None
        return True

    # ------------------------------------------------------------------ 读取接口

    def get_frame(self, copy: bool = True, max_age: float | None = None) -> Frame | None:
        """取最新帧。max_age 用于拒绝过期帧（摄像头卡住时返回 None）。"""
        with self._cond:
            frame = self._frame
        if frame is None:
            return None
        if max_age is not None and frame.age > max_age:
            return None
        return _clone(frame) if copy else frame

    def wait_for_frame(
        self,
        after_seq: int = -1,
        timeout: float = 2.0,
        copy: bool = True,
        max_age: float | None = None,
    ) -> Frame | None:
        """阻塞直到出现 seq > after_seq 的新帧；超时或已停机返回 None。"""
        deadline = time.time() + timeout
        with self._cond:
            while True:
                frame = self._frame
                if frame is not None and frame.seq > after_seq:
                    age = frame.age
                    fresh = max_age is None or age <= max_age
                    if fresh:
                        return _clone(frame) if copy else frame
                if not self.running:
                    return None
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)

    def read_image(self, copy: bool = False) -> np.ndarray | None:
        """便捷方法：只要图像数组（默认不拷贝，调用方不得修改）。"""
        frame = self.get_frame(copy=copy)
        return None if frame is None else frame.image

    def save_frame(self, output_path: str | Path, max_age: float | None = 2.0) -> dict:
        """把最新帧写盘，供原有抓拍接口复用。"""
        output_path = Path(output_path)
        frame = self.get_frame(copy=False, max_age=max_age)
        if frame is None:
            return {'success': False, 'error': '摄像头暂无可用画面'}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output_path), frame.image):
            return {'success': False, 'error': f'写入图片失败: {output_path}'}
        return {
            'success': True,
            'image_path': str(output_path),
            'camera_source': str(self._source),
            'seq': frame.seq,
            'captured_at': frame.captured_at,
        }

    def latest_seq(self) -> int:
        with self._cond:
            return self._seq

    # ------------------------------------------------------------------ 订阅接口

    def add_listener(self, callback: Callable[[Frame], None]) -> None:
        """注册帧回调。回调在采集线程里执行，必须在毫秒级返回（只做唤醒/入队）。"""
        with self._cond:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[Frame], None]) -> None:
        with self._cond:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def history(self) -> list[Frame]:
        """返回环形缓冲里的帧（旧 -> 新），供哨兵事件回溯。"""
        with self._cond:
            return list(self._history)

    def status(self) -> dict:
        with self._cond:
            frame = self._frame
            seq = self._seq
            listeners = len(self._listeners)
        return {
            'running': self.running,
            'source': str(self._source),
            'seq': seq,
            'fps': round(self._fps, 1),
            'last_frame_age': None if frame is None else round(frame.age, 3),
            'shape': None if frame is None else frame.shape,
            'dark': self._dark,
            'mean': self._last_mean,
            'listeners': listeners,
            'error': self._error,
        }

    # ------------------------------------------------------------------ 采集线程

    def _run(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            if self._cap is None:
                if not self._open():
                    if self._stop_event.wait(self._reconnect_delay):
                        break
                    continue
                failures = 0

            ok, image = self._cap.read()
            if not ok or image is None:
                failures += 1
                logger.warning('[Camera] 读帧失败 (%d/%d)', failures, _MAX_READ_FAILURES)
                if failures >= _MAX_READ_FAILURES:
                    self._error = '连续读帧失败，正在重开设备'
                    self._release()
                    failures = 0
                continue

            self._error = None
            self._publish(image)

        self._release()

    def _open(self) -> bool:
        source = self._source
        try:
            if isinstance(source, str) and source.startswith('/dev/video'):
                cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
            else:
                cap = cv2.VideoCapture(source)

            if not cap.isOpened():
                self._error = f'无法打开摄像头: {source}'
                logger.warning('[Camera] %s', self._error)
                cap.release()
                return False

            # 尽量降低驱动内部缓冲，保证拿到的是最新画面
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            self._cap = cap
            self._fps_mark = (time.time(), 0)
            self._frame_count = 0
            logger.info('[Camera] 设备已打开: %s', source)
            return True
        except Exception as exc:
            self._error = str(exc)
            logger.exception('[Camera] 打开设备异常')
            return False

    def _release(self) -> None:
        cap = self._cap
        self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def _publish(self, image: np.ndarray) -> None:
        with self._cond:
            self._seq += 1
            frame = Frame(
                seq=self._seq,
                captured_at=time.time(),
                image=image,
                source=str(self._source),
            )
            self._frame = frame
            if self._history_size:
                self._history.append(frame)
            listeners = list(self._listeners)
            self._cond.notify_all()

        self._tick_fps()
        self._check_health(frame)

        for callback in listeners:
            try:
                callback(frame)
            except Exception:
                logger.exception('[Camera] 帧回调异常')

    def _tick_fps(self) -> None:
        self._frame_count += 1
        now = time.time()
        mark_time, mark_count = self._fps_mark
        elapsed = now - mark_time
        if elapsed >= _FPS_WINDOW:
            self._fps = (self._frame_count - mark_count) / elapsed
            self._fps_mark = (now, self._frame_count)

    def _check_health(self, frame: Frame) -> None:
        if frame.seq % _HEALTH_CHECK_EVERY != 0:
            return
        try:
            mean = float(frame.image.mean())
        except Exception:
            return
        self._last_mean = round(mean, 1)
        was_dark = self._dark
        self._dark = mean < _BLANK_MEAN_THRESHOLD
        if self._dark and not was_dark:
            logger.warning('[Camera] 画面过暗 (mean=%.1f)，检查镜头遮挡或隐私开关', mean)


def _clone(frame: Frame) -> Frame:
    """返回图像副本，调用方可以安全原地修改。"""
    return Frame(
        seq=frame.seq,
        captured_at=frame.captured_at,
        image=frame.image.copy(),
        source=frame.source,
    )


# 全局单例：整个进程只允许一路采集，避免多个 VideoCapture 抢占同一设备
def _default_source():
    """默认跟随 config.CAMERA_SOURCE（Windows 为数字索引，Linux 为 /dev/videoN）。"""
    try:
        import config

        return config.CAMERA_SOURCE
    except Exception:
        return 0


camera_stream = CameraStream(source=_default_source())
