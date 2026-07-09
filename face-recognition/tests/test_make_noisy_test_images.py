from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.make_noisy_test_images import apply_camera_noise, process_directory, resolve_cli_paths


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path)


def read_png(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


class NoisyTestImageTests(unittest.TestCase):
    def test_camera_noise_is_deterministic_and_preserves_image_shape(self):
        image = np.full((32, 32, 3), 128, dtype=np.uint8)

        first = apply_camera_noise(image, profile="damaged", seed=123)
        second = apply_camera_noise(image, profile="damaged", seed=123)

        self.assertEqual(first.shape, image.shape)
        self.assertEqual(first.dtype, np.uint8)
        self.assertTrue(np.array_equal(first, second))
        self.assertFalse(np.array_equal(first, image))

    def test_process_directory_writes_noisy_images_without_changing_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "testphotos"
            output_dir = tmp_path / "testphotos_noisy"
            original = np.full((24, 24, 3), 160, dtype=np.uint8)
            image_path = input_dir / "person_a" / "sample.png"
            write_png(image_path, original)

            written = process_directory(input_dir, output_dir, profile="low", seed=7)

            output_path = output_dir / "person_a" / "sample.png"
            self.assertEqual(written, [output_path])
            self.assertTrue(output_path.exists())
            self.assertTrue(np.array_equal(read_png(image_path), original))
            self.assertEqual(read_png(output_path).shape, original.shape)
            self.assertFalse(np.array_equal(read_png(output_path), original))

    def test_cli_paths_resolve_against_project_root_when_run_from_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            project_root = workspace_root / "face-recognition"
            input_dir = project_root / "testphotos"
            input_dir.mkdir(parents=True)

            input_path, output_path = resolve_cli_paths(
                "testphotos",
                "testphotos_noisy",
                cwd=workspace_root,
                project_root=project_root,
            )

            self.assertEqual(input_path, input_dir)
            self.assertEqual(output_path, project_root / "testphotos_noisy")


if __name__ == "__main__":
    unittest.main()
