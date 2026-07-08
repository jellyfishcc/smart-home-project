import unittest
import sys
from pathlib import Path

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from routes.api import _timestamped_upload_filename, allowed_file


class AllowedFileTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["ALLOWED_EXTENSIONS"] = config.ALLOWED_EXTENSIONS

    def test_accepts_webp_extensions(self):
        with self.app.app_context():
            self.assertTrue(allowed_file("sample.webp"))
            self.assertTrue(allowed_file("sample.WEBP"))

    def test_rejects_missing_extension(self):
        with self.app.app_context():
            self.assertFalse(allowed_file("sample"))


class UploadFilenameTest(unittest.TestCase):
    def test_timestamped_upload_filename_preserves_webp_extension(self):
        filename = _timestamped_upload_filename("person_1", "face.WEBP", timestamp=123)
        self.assertEqual(filename, "person_1_123.webp")

    def test_timestamped_upload_filename_sanitizes_original_name(self):
        filename = _timestamped_upload_filename("detect", "../../weird name.PNG", timestamp=123)
        self.assertTrue(filename.startswith("detect_123_"))
        self.assertTrue(filename.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
