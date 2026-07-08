import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.insightface_backend import InsightFaceBackend


class FakeInsightFaceApp:
    def __init__(self):
        self.images = []

    def get(self, image):
        self.images.append(image)
        return [
            type(
                "Face",
                (),
                {
                    "normed_embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32),
                    "embedding": np.array([10.0, 0.0, 0.0], dtype=np.float32),
                    "det_score": 0.99,
                    "bbox": np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
                },
            )()
        ]


class InsightFaceBackendTest(unittest.TestCase):
    def test_reads_unicode_paths_with_imdecode(self):
        backend = InsightFaceBackend.__new__(InsightFaceBackend)
        backend._app = FakeInsightFaceApp()
        image_path = Path("known_faces") / "张明" / "OIP.webp"
        decoded = np.zeros((2, 2, 3), dtype=np.uint8)

        with patch("numpy.fromfile", return_value=np.array([1, 2, 3], dtype=np.uint8)), \
             patch("cv2.imdecode", return_value=decoded):
            faces = backend.extract_faces(image_path)

        self.assertEqual(len(faces), 1)
        self.assertTrue(np.array_equal(backend._app.images[0], decoded))
        self.assertAlmostEqual(float(faces[0].embedding[0]), 1.0)
        self.assertEqual(faces[0].det_score, 0.99)
        self.assertEqual(faces[0].bbox, [1.0, 2.0, 3.0, 4.0])


if __name__ == "__main__":
    unittest.main()
