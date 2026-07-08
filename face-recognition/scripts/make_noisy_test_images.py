from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CameraNoiseProfile:
    gaussian_sigma: float
    salt_pepper_amount: float
    blur_radius: float
    jpeg_quality: int
    downscale_ratio: float


PROFILES = {
    "low": CameraNoiseProfile(
        gaussian_sigma=10.0,
        salt_pepper_amount=0.004,
        blur_radius=0.2,
        jpeg_quality=70,
        downscale_ratio=0.85,
    ),
    "damaged": CameraNoiseProfile(
        gaussian_sigma=30.0,
        salt_pepper_amount=0.025,
        blur_radius=1.0,
        jpeg_quality=28,
        downscale_ratio=0.55,
    ),
}


def apply_camera_noise(
    image: np.ndarray,
    profile: str = "damaged",
    seed: int | None = None,
) -> np.ndarray:
    settings = _profile(profile)
    rng = np.random.default_rng(seed)
    noisy = np.asarray(image, dtype=np.float32).copy()

    noisy += rng.normal(0.0, settings.gaussian_sigma, size=noisy.shape)
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)
    noisy = _apply_salt_pepper(noisy, settings.salt_pepper_amount, rng)
    noisy = _apply_downscale(noisy, settings.downscale_ratio)
    noisy = _apply_blur(noisy, settings.blur_radius)
    noisy = _apply_jpeg_damage(noisy, settings.jpeg_quality)
    return noisy


def process_directory(
    input_dir: str | Path,
    output_dir: str | Path,
    profile: str = "damaged",
    seed: int | None = None,
    overwrite: bool = True,
) -> list[Path]:
    source_root = Path(input_dir)
    target_root = Path(output_dir)
    if not source_root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {source_root}")

    written_paths: list[Path] = []
    for index, source_path in enumerate(_iter_image_files(source_root)):
        relative_path = source_path.relative_to(source_root)
        output_path = target_root / relative_path
        if output_path.exists() and not overwrite:
            continue

        image = _read_rgb_image(source_path)
        noisy = apply_camera_noise(image, profile=profile, seed=_file_seed(seed, relative_path, index))
        _write_rgb_image(output_path, noisy)
        written_paths.append(output_path)

    return written_paths


def resolve_cli_paths(
    input_arg: str | Path,
    output_arg: str | Path,
    cwd: str | Path | None = None,
    project_root: str | Path = PROJECT_ROOT,
) -> tuple[Path, Path]:
    current_dir = Path.cwd() if cwd is None else Path(cwd)
    root = Path(project_root)

    input_path = _resolve_input_path(Path(input_arg), current_dir, root)
    output_path = _resolve_output_path(Path(output_arg), current_dir, root, input_path)
    return input_path, output_path


def _resolve_input_path(path: Path, cwd: Path, project_root: Path) -> Path:
    if path.is_absolute():
        return path

    cwd_path = cwd / path
    if cwd_path.exists():
        return cwd_path

    project_path = project_root / path
    if project_path.exists():
        return project_path

    return cwd_path


def _resolve_output_path(path: Path, cwd: Path, project_root: Path, input_path: Path) -> Path:
    if path.is_absolute():
        return path

    cwd_path = cwd / path
    if input_path.is_relative_to(project_root) or not cwd_path.parent.exists():
        return project_root / path

    return cwd_path


def _profile(profile: str) -> CameraNoiseProfile:
    try:
        return PROFILES[profile]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown profile '{profile}'. Choose one of: {choices}") from exc


def _apply_salt_pepper(
    image: np.ndarray,
    amount: float,
    rng: np.random.Generator,
) -> np.ndarray:
    if amount <= 0:
        return image

    result = image.copy()
    mask = rng.random(image.shape[:2])
    salt = mask < amount / 2
    pepper = (mask >= amount / 2) & (mask < amount)
    result[salt] = 255
    result[pepper] = 0
    return result


def _apply_downscale(image: np.ndarray, ratio: float) -> np.ndarray:
    if ratio >= 1.0:
        return image

    source = Image.fromarray(image)
    width, height = source.size
    small_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
    small = source.resize(small_size, Image.Resampling.BILINEAR)
    return np.asarray(small.resize((width, height), Image.Resampling.BILINEAR))


def _apply_blur(image: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0:
        return image
    return np.asarray(Image.fromarray(image).filter(ImageFilter.GaussianBlur(radius=radius)))


def _apply_jpeg_damage(image: np.ndarray, quality: int) -> np.ndarray:
    buffer = BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return np.asarray(Image.open(buffer).convert("RGB"))


def _read_rgb_image(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def _write_rgb_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    output = Image.fromarray(image)
    if suffix in {".jpg", ".jpeg"}:
        output.save(path, quality=92)
    else:
        output.save(path)


def _iter_image_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]


def _file_seed(seed: int | None, relative_path: Path, index: int) -> int | None:
    if seed is None:
        return None

    digest = hashlib.sha256(f"{seed}:{index}:{relative_path.as_posix()}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate noisy face-recognition test images before verification."
    )
    parser.add_argument("--input", default="testphotos", help="Input test image directory")
    parser.add_argument("--output", default="testphotos_noisy", help="Output directory for noisy images")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="damaged",
        help="Camera quality profile to simulate",
    )
    parser.add_argument("--seed", type=int, default=20260707, help="Seed for reproducible noise")
    parser.add_argument("--no-overwrite", action="store_true", help="Skip images that already exist")
    args = parser.parse_args()
    input_path, output_path = resolve_cli_paths(args.input, args.output)

    written = process_directory(
        input_path,
        output_path,
        profile=args.profile,
        seed=args.seed,
        overwrite=not args.no_overwrite,
    )

    print(f"Wrote {len(written)} noisy image(s) to {output_path}")


if __name__ == "__main__":
    main()
