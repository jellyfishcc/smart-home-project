from pathlib import Path


def test_package_exports_face_authorizer_api():
    import smart_home_face

    assert smart_home_face.LocalFaceAuthorizer.__name__ == "LocalFaceAuthorizer"
    assert smart_home_face.InsightFaceBackend.__name__ == "InsightFaceBackend"


def test_package_config_defaults_to_project_data_directories():
    from smart_home_face import config

    assert config.BASE_DIR == Path(__file__).resolve().parents[1]
    assert config.AUTHORIZED_FACES_DIR == config.BASE_DIR / "authorized_faces"
    assert config.AUTHORIZED_FACE_CACHE_PATH == config.BASE_DIR / "authorized_faces_cache.npz"
    assert config.INSIGHTFACE_MODEL_ROOT == config.BASE_DIR / "models"
