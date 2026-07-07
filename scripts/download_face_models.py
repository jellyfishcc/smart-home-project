from __future__ import annotations

import argparse
import os
from pathlib import Path


DEFAULT_MODEL_NAME = "buffalo_l"
DEFAULT_DET_SIZE = (320, 320)
REQUIRED_MODEL_FILES = (
    "1k3d68.onnx",
    "2d106det.onnx",
    "det_10g.onnx",
    "genderage.onnx",
    "w600k_r50.onnx",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_model_root(root: Path | str | None = None) -> Path:
    base = Path(root) if root is not None else repo_root()
    return base / "face-recognition" / "models"


def expected_model_dir(model_root: Path | str, model_name: str) -> Path:
    return Path(model_root) / "models" / model_name


def missing_files(model_dir: Path | str, required_files: list[str] | tuple[str, ...]) -> list[str]:
    base = Path(model_dir)
    return [file_name for file_name in required_files if not (base / file_name).exists()]


def download_model(model_name: str, model_root: Path, det_size: tuple[int, int]) -> None:
    try:
        from insightface.app import FaceAnalysis
    except ModuleNotFoundError as exc:
        raise SystemExit("insightface is not installed. Run `uv sync` first.") from exc

    model_root.mkdir(parents=True, exist_ok=True)
    app = FaceAnalysis(
        name=model_name,
        root=str(model_root),
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=det_size)


def parse_args() -> argparse.Namespace:
    env_model_root = os.getenv("INSIGHTFACE_MODEL_ROOT")
    parser = argparse.ArgumentParser(description="Download InsightFace models for this repository.")
    parser.add_argument(
        "--model-name",
        default=os.getenv("INSIGHTFACE_MODEL_NAME", DEFAULT_MODEL_NAME),
        help=f"InsightFace model name. Default: {DEFAULT_MODEL_NAME}",
    )
    parser.add_argument(
        "--model-root",
        type=Path,
        default=Path(env_model_root) if env_model_root else default_model_root(),
        help="Model root directory. Default: face-recognition/models",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check whether the model files already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_root = args.model_root.resolve()
    model_dir = expected_model_dir(model_root, args.model_name)

    print(f"Model root: {model_root}")
    print(f"Expected model directory: {model_dir}")

    if not args.check_only:
        download_model(args.model_name, model_root, DEFAULT_DET_SIZE)

    missing = missing_files(model_dir, REQUIRED_MODEL_FILES)
    if missing:
        print("Missing model files:")
        for file_name in missing:
            print(f"  - {file_name}")
        return 1

    print(f"Model `{args.model_name}` is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
