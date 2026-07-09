from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from smart_home_face.face_authorizer import *  # noqa: F401,F403

