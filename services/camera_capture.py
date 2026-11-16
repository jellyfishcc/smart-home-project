"""
摄像头单帧抓拍（兼容旧接口）

实现已切换为「复用常驻采集线程」：同一进程内只允许一路 VideoCapture，
避免人脸识别、物体检测、哨兵、推流各自 open 设备导致抢占（Windows 摄像头通常独占）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from services.camera_stream import camera_stream


logger = logging.getLogger(__name__)


def _normalize_camera_source(camera_source):
    if isinstance(camera_source, int):
        return camera_source
    source = str(camera_source).strip()
    if source.lstrip('-').isdigit():
        return int(source)
    return source


def capture_camera_frame(
    camera_source,
    output_path: str | Path,
    warmup_frames: int = 2,
    first_frame_timeout: float = 5.0,
) -> dict:
    """抓取当前最新一帧并写盘。

    warmup_frames 保留仅为兼容旧调用：常驻采集线程一直在读帧，
    取到的本来就是预热后的画面，无需再丢弃前几帧。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    camera_source = _normalize_camera_source(camera_source)

    hub = camera_stream
    hub_source = _normalize_camera_source(hub.status()['source'])

    if not hub.running:
        if hub_source != camera_source:
            hub.set_source(camera_source)
        hub.start()
        if hub.wait_for_frame(-1, timeout=first_frame_timeout) is None:
            error = hub.status().get('error') or '摄像头无可用画面'
            hub.stop()
            logger.warning('[Camera] %s', error)
            return {'success': False, 'error': error}
    elif hub_source != camera_source:
        message = f'采集线程已占用设备 {hub_source}，无法切换到 {camera_source}'
        logger.warning('[Camera] %s', message)
        return {'success': False, 'error': message}

    result = hub.save_frame(output_path, max_age=first_frame_timeout)
    if not result.get('success'):
        logger.warning('[Camera] %s', result.get('error'))
        return {'success': False, 'error': result.get('error', '摄像头抓帧失败')}

    return {
        'success': True,
        'image_path': str(output_path),
        'camera_source': str(camera_source),
        'seq': result.get('seq'),
    }
