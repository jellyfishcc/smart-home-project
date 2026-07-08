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


def face(vector):
    return FaceEmbedding(
        embedding=np.array(vector, dtype=np.float32),
        det_score=0.99,
        bbox=[1.0, 2.0, 3.0, 4.0],
    )


def runtime_root(name):
    root = Path("tests") / "runtime" / f"{name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


class InsightFaceRecognitionServiceTest(unittest.TestCase):
    def test_register_face_stores_embedding_and_recognizes_match(self):
        root = runtime_root("match")
        backend = FakeBackend(
            {
                "register.webp": [face([1.0, 0.0, 0.0])],
                "probe.webp": [face([1.0, 0.0, 0.0])],
            }
        )
        service = FaceRecognitionService(
            known_faces_dir=str(root / "known_faces"),
            data_dir=str(root / "data"),
            confidence_threshold=0.45,
            backend=backend,
        )
        (root / "register.webp").write_bytes(b"fake image bytes")

        registered = service.register_face(1, str(root / "register.webp"), "张明")
        result = service.recognize(str(root / "probe.webp"))

        self.assertTrue(registered["success"])
        self.assertEqual(registered["face_count"], 1)
        self.assertTrue(result["recognized"])
        self.assertEqual(result["person_id"], 1)
        self.assertEqual(result["result"], "granted")
        self.assertAlmostEqual(result["confidence"], 1.0)

    def test_recognize_denies_below_threshold(self):
        root = runtime_root("deny")
        backend = FakeBackend(
            {
                "register.webp": [face([1.0, 0.0, 0.0])],
                "unknown.webp": [face([0.0, 1.0, 0.0])],
            }
        )
        service = FaceRecognitionService(
            known_faces_dir=str(root / "known_faces"),
            data_dir=str(root / "data"),
            confidence_threshold=0.45,
            backend=backend,
        )
        (root / "register.webp").write_bytes(b"fake image bytes")
        service.register_face(1, str(root / "register.webp"), "张明")

        result = service.recognize(str(root / "unknown.webp"))

        self.assertFalse(result["recognized"])
        self.assertEqual(result["result"], "denied")
        self.assertEqual(result["person_id"], 1)
        self.assertAlmostEqual(result["confidence"], 0.0)

    def test_register_face_rejects_no_face_and_multi_face(self):
        root = runtime_root("reject")
        backend = FakeBackend(
            {
                "empty.webp": [],
                "group.webp": [face([1.0, 0.0, 0.0]), face([0.0, 1.0, 0.0])],
            }
        )
        service = FaceRecognitionService(
            known_faces_dir=str(root / "known_faces"),
            data_dir=str(root / "data"),
            confidence_threshold=0.45,
            backend=backend,
        )

        no_face = service.register_face(1, str(root / "empty.webp"), "张明")
        multi_face = service.register_face(1, str(root / "group.webp"), "张明")

        self.assertFalse(no_face["success"])
        self.assertEqual(no_face["face_count"], 0)
        self.assertFalse(multi_face["success"])
        self.assertEqual(multi_face["face_count"], 2)


if __name__ == "__main__":
    unittest.main()
