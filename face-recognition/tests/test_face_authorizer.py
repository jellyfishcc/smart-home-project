from pathlib import Path
import unittest
from uuid import uuid4
from unittest.mock import patch

import numpy as np

from smart_home_face import InsightFaceBackend, LocalFaceAuthorizer


TEST_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / ".unit_fixture"


class FakeFaceBackend:
    def __init__(self, embeddings_by_filename):
        self.embeddings_by_filename = embeddings_by_filename
        self.calls = []

    def extract_embeddings(self, image_path):
        self.calls.append(Path(image_path).name)
        values = self.embeddings_by_filename.get(Path(image_path).name, [])
        return [np.array(value, dtype=np.float32) for value in values]


class FakeInsightFaceApp:
    def __init__(self):
        self.images = []

    def get(self, image):
        self.images.append(image)
        return [type("Face", (), {"embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32)})()]


def create_file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake image")


class LocalFaceAuthorizerTests(unittest.TestCase):
    def case_root(self, name):
        root = TEST_FIXTURE_ROOT / name / uuid4().hex
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_authorizes_matching_face_from_local_gallery(self):
        root = self.case_root("authorizes_matching_face")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        create_file(root / "authorized_faces" / "person_b" / "b.jpg")
        create_file(root / "probe_a.jpg")
        backend = FakeFaceBackend(
            {
                "a.jpg": [[1.0, 0.0, 0.0]],
                "b.jpg": [[0.0, 1.0, 0.0]],
                "probe_a.jpg": [[1.0, 0.0, 0.0]],
            }
        )

        authorizer = LocalFaceAuthorizer(root / "authorized_faces", backend, threshold=0.8)
        result = authorizer.verify_image(root / "probe_a.jpg")

        self.assertTrue(result.authorized)
        self.assertEqual(result.result, "AUTHORIZED")
        self.assertEqual(result.person["id"], "person_a")
        self.assertEqual(result.person["name"], "person_a")
        self.assertAlmostEqual(result.similarity_score, 1.0)

    def test_denies_unknown_face_below_threshold(self):
        root = self.case_root("denies_unknown_face")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        create_file(root / "authorized_faces" / "person_b" / "b.jpg")
        create_file(root / "unknown.jpg")
        backend = FakeFaceBackend(
            {
                "a.jpg": [[1.0, 0.0, 0.0]],
                "b.jpg": [[0.0, 1.0, 0.0]],
                "unknown.jpg": [[0.0, 0.0, 1.0]],
            }
        )

        authorizer = LocalFaceAuthorizer(root / "authorized_faces", backend, threshold=0.8)
        result = authorizer.verify_image(root / "unknown.jpg")

        self.assertFalse(result.authorized)
        self.assertEqual(result.result, "DENIED")
        self.assertIsNone(result.person)
        self.assertEqual(result.door_action, "NONE")

    def test_returns_no_face_when_input_has_no_detected_faces(self):
        root = self.case_root("returns_no_face")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        create_file(root / "empty.jpg")
        backend = FakeFaceBackend(
            {
                "a.jpg": [[1.0, 0.0, 0.0]],
                "empty.jpg": [],
            }
        )

        authorizer = LocalFaceAuthorizer(root / "authorized_faces", backend, threshold=0.8)
        result = authorizer.verify_image(root / "empty.jpg")

        self.assertFalse(result.authorized)
        self.assertEqual(result.result, "NO_FACE")
        self.assertEqual(result.message, "未检测到人脸")

    def test_returns_multi_face_when_input_has_multiple_detected_faces(self):
        root = self.case_root("returns_multi_face")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        create_file(root / "group.jpg")
        backend = FakeFaceBackend(
            {
                "a.jpg": [[1.0, 0.0, 0.0]],
                "group.jpg": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            }
        )

        authorizer = LocalFaceAuthorizer(root / "authorized_faces", backend, threshold=0.8)
        result = authorizer.verify_image(root / "group.jpg")

        self.assertFalse(result.authorized)
        self.assertEqual(result.result, "MULTI_FACE")
        self.assertEqual(result.message, "检测到多人，请单人靠近摄像头")

    def test_writes_authorized_face_cache_on_first_startup(self):
        root = self.case_root("writes_cache")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        create_file(root / "authorized_faces" / "person_b" / "b.jpg")
        cache_path = root / "authorized_faces_cache.npz"
        backend = FakeFaceBackend(
            {
                "a.jpg": [[1.0, 0.0, 0.0]],
                "b.jpg": [[0.0, 1.0, 0.0]],
            }
        )

        authorizer = LocalFaceAuthorizer(
            root / "authorized_faces",
            backend,
            threshold=0.8,
            cache_path=cache_path,
        )

        self.assertTrue(cache_path.exists())
        self.assertEqual(["a.jpg", "b.jpg"], backend.calls)
        self.assertEqual(["person_a", "person_b"], [face.person_id for face in authorizer.gallery])

    def test_reuses_authorized_face_cache_when_image_list_is_unchanged(self):
        root = self.case_root("reuses_cache")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        cache_path = root / "authorized_faces_cache.npz"
        first_backend = FakeFaceBackend({"a.jpg": [[1.0, 0.0, 0.0]]})
        LocalFaceAuthorizer(
            root / "authorized_faces",
            first_backend,
            threshold=0.8,
            cache_path=cache_path,
        )
        second_backend = FakeFaceBackend({})

        authorizer = LocalFaceAuthorizer(
            root / "authorized_faces",
            second_backend,
            threshold=0.8,
            cache_path=cache_path,
        )

        self.assertEqual([], second_backend.calls)
        self.assertEqual(1, len(authorizer.gallery))
        self.assertEqual("person_a", authorizer.gallery[0].person_id)

    def test_rebuilds_authorized_face_cache_when_new_image_is_added(self):
        root = self.case_root("rebuilds_stale_cache")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        cache_path = root / "authorized_faces_cache.npz"
        LocalFaceAuthorizer(
            root / "authorized_faces",
            FakeFaceBackend({"a.jpg": [[1.0, 0.0, 0.0]]}),
            threshold=0.8,
            cache_path=cache_path,
        )
        create_file(root / "authorized_faces" / "person_b" / "b.jpg")
        rebuild_backend = FakeFaceBackend(
            {
                "a.jpg": [[1.0, 0.0, 0.0]],
                "b.jpg": [[0.0, 1.0, 0.0]],
            }
        )

        authorizer = LocalFaceAuthorizer(
            root / "authorized_faces",
            rebuild_backend,
            threshold=0.8,
            cache_path=cache_path,
        )

        self.assertEqual(["a.jpg", "b.jpg"], rebuild_backend.calls)
        self.assertEqual(["person_a", "person_b"], [face.person_id for face in authorizer.gallery])

    def test_rebuilds_authorized_face_cache_when_cache_is_malformed(self):
        root = self.case_root("rebuilds_malformed_cache")
        create_file(root / "authorized_faces" / "person_a" / "a.jpg")
        cache_path = root / "authorized_faces_cache.npz"
        cache_path.write_bytes(b"not a numpy cache")
        backend = FakeFaceBackend({"a.jpg": [[1.0, 0.0, 0.0]]})

        authorizer = LocalFaceAuthorizer(
            root / "authorized_faces",
            backend,
            threshold=0.8,
            cache_path=cache_path,
        )

        self.assertEqual(["a.jpg"], backend.calls)
        self.assertEqual(1, len(authorizer.gallery))
        self.assertEqual("person_a", authorizer.gallery[0].person_id)

    def test_insightface_backend_reads_unicode_paths_without_cv2_imread(self):
        root = self.case_root("unicode_paths")
        image_path = root / "丁程欣" / "OIP.webp"
        create_file(image_path)
        backend = InsightFaceBackend.__new__(InsightFaceBackend)
        backend._app = FakeInsightFaceApp()
        decoded_image = np.zeros((2, 2, 3), dtype=np.uint8)

        with patch("cv2.imread", return_value=None), patch("cv2.imdecode", return_value=decoded_image):
            embeddings = backend.extract_embeddings(image_path)

        self.assertEqual(len(embeddings), 1)
        self.assertTrue(np.array_equal(backend._app.images[0], decoded_image))


if __name__ == "__main__":
    unittest.main()
