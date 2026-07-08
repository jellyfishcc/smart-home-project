from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class FaceEmbedding:
    embedding: np.ndarray
    det_score: float | None
    bbox: list[float] | None


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

    def extract_faces(self, image_path: str | Path) -> list[FaceEmbedding]:
        image = self._read_image(image_path)
        faces = self._app.get(image)
        return [self._to_face_embedding(face) for face in faces]

    @staticmethod
    def _read_image(image_path: str | Path):
        import cv2

        image_bytes = np.fromfile(Path(image_path), dtype=np.uint8)
        image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Unable to read image: {image_path}")
        return image

    @staticmethod
    def _to_face_embedding(face) -> FaceEmbedding:
        embedding = getattr(face, "normed_embedding", None)
        if embedding is None:
            embedding = getattr(face, "embedding")
        bbox = getattr(face, "bbox", None)
        return FaceEmbedding(
            embedding=np.asarray(embedding, dtype=np.float32),
            det_score=float(face.det_score) if getattr(face, "det_score", None) is not None else None,
            bbox=np.asarray(bbox, dtype=np.float32).tolist() if bbox is not None else None,
        )
