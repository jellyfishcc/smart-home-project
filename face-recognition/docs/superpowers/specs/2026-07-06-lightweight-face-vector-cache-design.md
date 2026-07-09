# Lightweight Face Vector Cache Design

## Scope

Add a lightweight local cache for authorized face embeddings. The expected scale is 4-5 people, up to 3 images per person, so the cache should stay simple and dependency-free. A full vector database, registration timestamps, external services, and approximate nearest-neighbor indexes are out of scope.

## Cache Format

Use one local NumPy `.npz` file to store:

- `person_ids`: one person folder name per embedding.
- `names`: the display name for each embedding, currently the same as the folder name.
- `source_image_paths`: the authorized image path for each embedding.
- `embeddings`: normalized `float32` face vectors.

The default cache path should live next to the authorization folder unless configured otherwise. The file is a generated artifact and should not be committed.

## Startup Flow

When `LocalFaceAuthorizer` starts:

1. Scan `authorized_faces/` for supported image files.
2. Compare the sorted image path list with `source_image_paths` stored in the cache.
3. If the cache exists and the path list matches, load the gallery directly from the cache.
4. If the cache is missing or the path list differs, extract embeddings from the current authorization images and rewrite the cache.

This keeps the implementation deliberately simple. If an existing image is replaced without changing its path, the user can delete the generated cache file to force regeneration.

## Recognition Flow

Recognition remains the same as the current local matcher:

1. Extract the probe image embedding.
2. Normalize it.
3. Compare it with all cached authorized embeddings using cosine similarity.
4. Return `AUTHORIZED` when the best score is greater than or equal to `FACE_MATCH_THRESHOLD`.
5. Return `DENIED` or `NO_FACE` as before.

## Error Handling

If the authorization directory has no usable face images, startup should still raise `ValueError` as it does today. If the cache file is unreadable or malformed, ignore it and rebuild from the authorization directory. If rebuilding succeeds, replace the broken cache.

## Testing

Unit tests should cover:

- First startup extracts authorized embeddings and writes the cache.
- Second startup with the same authorized image list loads from cache without calling the backend for authorized images.
- Adding a new authorized image causes the cache to rebuild and include the new person/vector.
- A malformed cache falls back to rebuilding from source images.

