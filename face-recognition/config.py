from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from smart_home_face.config import *  # noqa: F401,F403
