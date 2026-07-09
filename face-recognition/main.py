from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from smart_home_face.cli import build_authorizer, main


if __name__ == "__main__":
    main()
