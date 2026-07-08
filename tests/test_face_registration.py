import sys
import unittest
import uuid
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.insightface_backend import FaceEmbedding
from services.face_recognition_service import FaceRecognitionService


class FakeBackend:
    def __init__(self, faces_by_name):
        self.faces_by_name = faces_by_name

    def extract_faces(self, image_path):
        return self.faces_by_name.get(Path(image_path).name, [])


def face(vector, bbox=None):
    return FaceEmbedding(
        embedding=np.array(vector, dtype=np.float32),
        det_score=0.99,
        bbox=bbox,
    )


def runtime_root(name):
    root = Path("tests") / "runtime" / f"{name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


class FaceRegistrationTest(unittest.TestCase):
    def test_register_face_returns_failure_when_no_face_can_be_extracted(self):
        root = runtime_root("registration_no_face")
        service = FaceRecognitionService(
            known_faces_dir=str(root / "known_faces"),
            data_dir=str(root / "data"),
            backend=FakeBackend({"missing-face-image.jpg": []}),
        )

        result = service.register_face(1, "missing-face-image.jpg", "Test User")

        self.assertFalse(result["success"])
        self.assertEqual(result["face_count"], 0)

    def test_detect_faces_returns_compatibility_boxes_from_backend_bbox(self):
        root = runtime_root("registration_detect_faces")
        service = FaceRecognitionService(
            known_faces_dir=str(root / "known_faces"),
            data_dir=str(root / "data"),
            backend=FakeBackend({
                "person.webp": [face([1.0, 0.0, 0.0], bbox=[10.0, 20.0, 40.0, 70.0])],
            }),
        )

        faces, _ = service.detect_faces(str(root / "person.webp"))

        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0].tolist(), [10, 20, 30, 50])


if __name__ == "__main__":
    unittest.main()
