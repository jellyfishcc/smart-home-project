from pathlib import Path
import unittest

from scripts.download_face_models import default_model_root, expected_model_dir, missing_files


class DownloadFaceModelsTest(unittest.TestCase):
    def test_default_model_path_matches_face_recognition_config(self):
        repo_root = Path("D:/example/smart-home-project")

        model_root = default_model_root(repo_root)

        self.assertEqual(model_root, repo_root / "face-recognition" / "models")
        self.assertEqual(
            expected_model_dir(model_root, "buffalo_l"),
            repo_root / "face-recognition" / "models" / "models" / "buffalo_l",
        )

    def test_missing_files_reports_only_absent_files(self):
        self.assertEqual(
            missing_files(Path.cwd(), ["README.md", "definitely_missing.onnx"]),
            ["definitely_missing.onnx"],
        )


if __name__ == "__main__":
    unittest.main()
