# Local Face Authorizer Design

## Scope

Implement the first usable face-recognition module for a single input image. The module answers whether the detected face is authorized. GUI, database, camera streaming, and door hardware are intentionally out of scope for this pass.

## Authorization Source

Authorized people are loaded from local folders:

```text
authorized_faces/
  person_a/
    image1.jpg
    image2.jpg
  person_b/
    image1.jpg
```

Each first-level folder is treated as one authorized person. Every supported image in that folder is converted to an InsightFace embedding and used as that person's gallery.

## Recognition Flow

1. Read one input image path.
2. Extract face embeddings with InsightFace on CPU.
3. Return `NO_FACE` if the image has no faces.
4. Return `MULTI_FACE` if the image has more than one face.
5. Compare the single detected face embedding with all enabled local gallery embeddings by cosine similarity.
6. Return `AUTHORIZED` when the best score is greater than or equal to `FACE_MATCH_THRESHOLD`.
7. Return `DENIED` otherwise.

## File Plan

- `config.py`: add threshold, model root, and authorization directory settings.
- `services/face_authorizer.py`: local gallery loading, cosine matching, and result objects.
- `main.py`: command-line entry point for verifying one image.
- `tests/test_face_authorizer.py`: unit tests using a fake face backend.
