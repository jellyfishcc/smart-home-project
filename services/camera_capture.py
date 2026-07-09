from __future__ import annotations

import logging
from pathlib import Path

import cv2


logger = logging.getLogger(__name__)


def capture_camera_frame(camera_index: int, output_path: str | Path, warmup_frames: int = 2) -> dict:
    """Capture one frame from the camera attached to the machine running Flask."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cap = None
    try:
        cap = cv2.VideoCapture(int(camera_index))
        if not cap.isOpened():
            message = f'Unable to open camera index {camera_index}'
            logger.warning('[Camera] %s', message)
            return {'success': False, 'error': message}

        frame = None
        ok = False
        for _ in range(max(1, warmup_frames + 1)):
            ok, frame = cap.read()

        if not ok or frame is None:
            message = f'Unable to read frame from camera index {camera_index}'
            logger.warning('[Camera] %s', message)
            return {'success': False, 'error': message}

        if not cv2.imwrite(str(output_path), frame):
            message = f'Unable to write camera frame: {output_path}'
            logger.warning('[Camera] %s', message)
            return {'success': False, 'error': message}

        return {'success': True, 'image_path': str(output_path)}
    except Exception as exc:
        logger.exception('[Camera] capture failed')
        return {'success': False, 'error': str(exc)}
    finally:
        if cap is not None:
            cap.release()
