from __future__ import annotations

import logging
from pathlib import Path

import cv2


logger = logging.getLogger(__name__)


def _normalize_camera_source(camera_source):
    if isinstance(camera_source, int):
        return camera_source
    source = str(camera_source).strip()
    if source.lstrip('-').isdigit():
        return int(source)
    return source


def capture_camera_frame(camera_source, output_path: str | Path, warmup_frames: int = 2) -> dict:
    """Capture one frame from the camera attached to the machine running Flask."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    camera_source = _normalize_camera_source(camera_source)

    cap = None
    try:
        if isinstance(camera_source, str) and camera_source.startswith('/dev/video'):
            cap = cv2.VideoCapture(camera_source, cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(camera_source)

        if not cap.isOpened():
            message = f'Unable to open camera source {camera_source}'
            logger.warning('[Camera] %s', message)
            return {'success': False, 'error': message}

        frame = None
        ok = False
        for _ in range(max(1, warmup_frames + 1)):
            ok, frame = cap.read()

        if not ok or frame is None:
            message = f'Unable to read frame from camera source {camera_source}'
            logger.warning('[Camera] %s', message)
            return {'success': False, 'error': message}

        if not cv2.imwrite(str(output_path), frame):
            message = f'Unable to write camera frame: {output_path}'
            logger.warning('[Camera] %s', message)
            return {'success': False, 'error': message}

        return {'success': True, 'image_path': str(output_path), 'camera_source': str(camera_source)}
    except Exception as exc:
        logger.exception('[Camera] capture failed')
        return {'success': False, 'error': str(exc)}
    finally:
        if cap is not None:
            cap.release()
