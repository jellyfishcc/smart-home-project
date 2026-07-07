from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class FaceBackend(Protocol):
    def extract_embeddings(self, image_path: str | Path) -> list[np.ndarray]:
        """Return one embedding per detected face in an image."""


@dataclass(frozen=True)
class AuthorizedFace:
    person_id: str
    name: str
    embedding: np.ndarray
    source_image_path: str


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    result: str
    authorized: bool
    person: dict[str, str] | None
    similarity_score: float | None
    door_action: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


class InsightFaceBackend:
    def __init__(
        self,
        model_name: str = "buffalo_l",
        model_root: str | Path = "models",
        det_size: tuple[int, int] = (320, 320),
    ):
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(
            name=model_name,
            root=str(model_root),
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=-1, det_size=det_size)

    def extract_embeddings(self, image_path: str | Path) -> list[np.ndarray]:
        import cv2

        image = self._read_image(image_path)
        faces = self._app.get(image)
        return [np.asarray(face.embedding, dtype=np.float32) for face in faces]

    @staticmethod
    def _read_image(image_path: str | Path) -> np.ndarray:
        import cv2

        path = Path(image_path)
        image_bytes = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")
        return image
    
    @property
    def app(self):
        return self._app

def get_nearest_face_embedding(app, frame):
    faces = app.get(frame)

    if len(faces) == 0:
        return None, None

    nearest_face = max(
        faces,
        key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])
    )

    return nearest_face.normed_embedding, nearest_face

class LocalFaceAuthorizer:
    def __init__(
        self,
        authorized_faces_dir: str | Path,
        backend: FaceBackend,
        threshold: float,
        cache_path: str | Path | None = None,
    ):
        self.authorized_faces_dir = Path(authorized_faces_dir)
        self.backend = backend
        self.threshold = float(threshold)
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self.gallery = self._load_gallery()

    def _legacy_verify_image_without_cache(self, image_path: str | Path) -> VerificationResult:
        embeddings = self.backend.extract_embeddings(image_path)

        if len(embeddings) == 0:
            return VerificationResult(
                success=True,
                result="NO_FACE",
                authorized=False,
                person=None,
                similarity_score=None,
                door_action="NONE",
                message="未检测到人脸",
            )

        if len(embeddings) > 1:
            return VerificationResult(
                success=True,
                result="MULTI_FACE",
                authorized=False,
                person=None,
                similarity_score=None,
                door_action="NONE",
                message="检测到多人，请单人靠近摄像头",
            )

        best_face, best_score = self._best_match(embeddings[0])
        if best_face is not None and best_score >= self.threshold:
            return VerificationResult(
                success=True,
                result="AUTHORIZED",
                authorized=True,
                person={"id": best_face.person_id, "name": best_face.name},
                similarity_score=best_score,
                door_action="OPEN",
                message="人脸识别成功，门已打开",
            )

        return VerificationResult(
            success=True,
            result="DENIED",
            authorized=False,
            person=None,
            similarity_score=best_score,
            door_action="NONE",
            message="未知人员，拒绝开门",
        )

    def _legacy_load_gallery_without_cache(self) -> list[AuthorizedFace]:
        if not self.authorized_faces_dir.exists():
            raise FileNotFoundError(f"授权人脸目录不存在: {self.authorized_faces_dir}")

        gallery: list[AuthorizedFace] = []
        for person_dir in sorted(self.authorized_faces_dir.iterdir()):
            if not person_dir.is_dir():
                continue

            person_id = person_dir.name
            for image_path in self._iter_image_files(person_dir):
                embeddings = self.backend.extract_embeddings(image_path)
                if len(embeddings) == 0:
                    continue
                if len(embeddings) > 1:
                    embeddings[0] = get_nearest_face_embedding(self.backend.app,frame = self.backend._read_image(image_path))[0]
                gallery.append(
                    AuthorizedFace(
                        person_id=person_id,
                        name=person_id,
                        embedding=self._normalize(embeddings[0]),
                        source_image_path=str(image_path),
                    )
                )

        if not gallery:
            raise ValueError(f"授权人脸目录中没有可用的单人脸照片: {self.authorized_faces_dir}")

        return gallery

    def verify_image(self, image_path: str | Path) -> VerificationResult:
        embeddings = self.backend.extract_embeddings(image_path)

        if len(embeddings) == 0:
            return VerificationResult(
                success=True,
                result="NO_FACE",
                authorized=False,
                person=None,
                similarity_score=None,
                door_action="NONE",
                message="未检测到人脸",
            )

        if len(embeddings) > 1:
            return VerificationResult(
                success=True,
                result="MULTI_FACE",
                authorized=False,
                person=None,
                similarity_score=None,
                door_action="NONE",
                message="检测到多人，请单人靠近摄像头",
            )

        best_face, best_score = self._best_match(embeddings[0])
        if best_face is not None and best_score >= self.threshold:
            return VerificationResult(
                success=True,
                result="AUTHORIZED",
                authorized=True,
                person={"id": best_face.person_id, "name": best_face.name},
                similarity_score=best_score,
                door_action="OPEN",
                message="人脸识别成功，门已打开",
            )

        return VerificationResult(
            success=True,
            result="DENIED",
            authorized=False,
            person=None,
            similarity_score=best_score,
            door_action="NONE",
            message="未知人员，拒绝开门",
        )

    def _load_gallery(self) -> list[AuthorizedFace]:
        if not self.authorized_faces_dir.exists():
            raise FileNotFoundError(f"授权人脸目录不存在: {self.authorized_faces_dir}")

        image_paths = self._authorized_image_paths()
        cached_gallery = self._load_gallery_from_cache(image_paths)
        if cached_gallery is not None:
            return cached_gallery

        gallery = self._build_gallery(image_paths)
        self._write_gallery_cache(gallery)
        return gallery

    def _authorized_image_paths(self) -> list[Path]:
        image_paths: list[Path] = []
        for person_dir in sorted(self.authorized_faces_dir.iterdir()):
            if person_dir.is_dir():
                image_paths.extend(self._iter_image_files(person_dir))
        return image_paths

    def _load_gallery_from_cache(self, image_paths: list[Path]) -> list[AuthorizedFace] | None:
        if self.cache_path is None or not self.cache_path.exists():
            return None

        expected_paths = [str(path) for path in image_paths]
        try:
            with np.load(self.cache_path, allow_pickle=False) as cache:
                source_image_paths = [str(path) for path in cache["source_image_paths"].tolist()]
                if source_image_paths != expected_paths:
                    return None

                person_ids = [str(person_id) for person_id in cache["person_ids"].tolist()]
                names = [str(name) for name in cache["names"].tolist()]
                embeddings = np.asarray(cache["embeddings"], dtype=np.float32)

            if embeddings.ndim != 2:
                return None
            if not (len(person_ids) == len(names) == len(source_image_paths) == len(embeddings)):
                return None

            gallery = [
                AuthorizedFace(
                    person_id=person_id,
                    name=name,
                    embedding=self._normalize(embedding),
                    source_image_path=source_image_path,
                )
                for person_id, name, source_image_path, embedding in zip(
                    person_ids,
                    names,
                    source_image_paths,
                    embeddings,
                )
            ]
        except Exception:
            return None

        if not gallery:
            return None
        return gallery

    def _build_gallery(self, image_paths: list[Path]) -> list[AuthorizedFace]:
        gallery: list[AuthorizedFace] = []
        for image_path in image_paths:
            person_id = image_path.parent.name
            embeddings = self.backend.extract_embeddings(image_path)
            if len(embeddings) == 0:
                continue
            if len(embeddings) > 1:
                largest_embedding, _ = self._largest_face_embedding(image_path)
                if largest_embedding is not None:
                    embeddings[0] = largest_embedding
            gallery.append(
                AuthorizedFace(
                    person_id=person_id,
                    name=person_id,
                    embedding=self._normalize(embeddings[0]),
                    source_image_path=str(image_path),
                )
            )

        if not gallery:
            raise ValueError(f"授权人脸目录中没有可用的单人脸照片: {self.authorized_faces_dir}")

        return gallery

    def _largest_face_embedding(self, image_path: Path) -> tuple[np.ndarray | None, object | None]:
        app = getattr(self.backend, "app", None)
        read_image = getattr(self.backend, "_read_image", None)
        if app is None or read_image is None:
            return None, None
        return get_nearest_face_embedding(app, frame=read_image(image_path))

    def _write_gallery_cache(self, gallery: list[AuthorizedFace]) -> None:
        if self.cache_path is None:
            return

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            self.cache_path,
            person_ids=np.array([face.person_id for face in gallery]),
            names=np.array([face.name for face in gallery]),
            source_image_paths=np.array([face.source_image_path for face in gallery]),
            embeddings=np.stack([face.embedding for face in gallery]).astype(np.float32),
        )

    def _best_match(self, probe_embedding: np.ndarray) -> tuple[AuthorizedFace | None, float | None]:
        probe = self._normalize(probe_embedding)
        best_face: AuthorizedFace | None = None
        best_score: float | None = None

        for face in self.gallery:
            score = float(np.dot(probe, face.embedding))
            if best_score is None or score > best_score:
                best_score = score
                best_face = face

        return best_face, best_score

    @staticmethod
    def _normalize(embedding: np.ndarray) -> np.ndarray:
        vector = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError("人脸 embedding 不能为零向量")
        return vector / norm

    @staticmethod
    def _iter_image_files(person_dir: Path) -> list[Path]:
        return [
            path
            for path in sorted(person_dir.iterdir())
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ]
