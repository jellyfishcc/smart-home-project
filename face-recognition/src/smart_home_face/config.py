import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]

test_photo = "./test.webp"

AUTHORIZED_FACES_DIR = Path(os.getenv("AUTHORIZED_FACES_DIR", BASE_DIR / "authorized_faces"))
AUTHORIZED_FACE_CACHE_PATH = Path(os.getenv("AUTHORIZED_FACE_CACHE_PATH", BASE_DIR / "authorized_faces_cache.npz"))
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.45"))
INSIGHTFACE_MODEL_NAME = os.getenv("INSIGHTFACE_MODEL_NAME", "buffalo_l")
INSIGHTFACE_MODEL_ROOT = Path(os.getenv("INSIGHTFACE_MODEL_ROOT", BASE_DIR / "models"))
INSIGHTFACE_DET_SIZE = (320, 320)
