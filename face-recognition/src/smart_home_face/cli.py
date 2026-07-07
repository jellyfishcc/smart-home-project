import argparse
import json

from smart_home_face.config import (
    AUTHORIZED_FACE_CACHE_PATH,
    AUTHORIZED_FACES_DIR,
    FACE_MATCH_THRESHOLD,
    INSIGHTFACE_DET_SIZE,
    INSIGHTFACE_MODEL_NAME,
    INSIGHTFACE_MODEL_ROOT,
)
from smart_home_face.face_authorizer import InsightFaceBackend, LocalFaceAuthorizer


def build_authorizer() -> LocalFaceAuthorizer:
    backend = InsightFaceBackend(
        model_name=INSIGHTFACE_MODEL_NAME,
        model_root=INSIGHTFACE_MODEL_ROOT,
        det_size=INSIGHTFACE_DET_SIZE,
    )
    return LocalFaceAuthorizer(
        authorized_faces_dir=AUTHORIZED_FACES_DIR,
        backend=backend,
        threshold=FACE_MATCH_THRESHOLD,
        cache_path=AUTHORIZED_FACE_CACHE_PATH,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify whether one face image is authorized.")
    parser.add_argument("image", help="Path to the image to verify")
    args = parser.parse_args()

    result = build_authorizer().verify_image(args.image)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
