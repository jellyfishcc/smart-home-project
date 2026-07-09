# Lightweight Face Vector Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache authorized face embeddings in a small local `.npz` file and reload them on later runs when the authorized image list is unchanged.

**Architecture:** `LocalFaceAuthorizer` will accept an optional cache path. Startup will scan authorized images, load a matching `.npz` gallery when possible, and rebuild the cache from source images when missing, stale, or malformed.

**Tech Stack:** Python standard library, NumPy, existing unittest tests.

---

### Task 1: Add Failing Cache Tests

**Files:**
- Modify: `tests/test_face_authorizer.py`

- [ ] **Step 1: Add tests for cache creation, cache reuse, stale cache rebuild, and malformed cache fallback.**

- [ ] **Step 2: Run `python -m unittest tests.test_face_authorizer` and verify the new cache tests fail because `LocalFaceAuthorizer` does not accept or use a cache path yet.**

### Task 2: Implement `.npz` Gallery Cache

**Files:**
- Modify: `services/face_authorizer.py`
- Modify: `config.py`
- Modify: `main.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add optional `cache_path` to `LocalFaceAuthorizer`.**

- [ ] **Step 2: Scan authorized image files once at startup and compare the sorted path list with cache metadata.**

- [ ] **Step 3: Load matching cache records into `AuthorizedFace` objects.**

- [ ] **Step 4: Rebuild cache from source images when the cache is missing, stale, or malformed.**

- [ ] **Step 5: Add `AUTHORIZED_FACE_CACHE_PATH` config and pass it from `main.py`.**

- [ ] **Step 6: Ignore the generated cache file in `.gitignore`.**

### Task 3: Verify Behavior

**Files:**
- Test: `tests/test_face_authorizer.py`

- [ ] **Step 1: Run `python -m unittest tests.test_face_authorizer`.**

- [ ] **Step 2: Confirm all tests pass or report the exact failure.**

