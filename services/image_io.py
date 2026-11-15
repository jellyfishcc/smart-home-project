"""OpenCV image file operations that support Unicode paths on Windows."""

from pathlib import Path

import cv2
import numpy as np


def read_image(path):
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if not encoded.size:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def write_image(path, image):
    ok, encoded = cv2.imencode(Path(path).suffix, image)
    if not ok:
        return False
    try:
        Path(path).write_bytes(encoded.tobytes())
    except OSError:
        return False
    return True
