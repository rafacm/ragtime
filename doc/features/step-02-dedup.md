# Step 2: Dedup — Duplicate Episode Detection

## Problem

Without dedup, the same podcast episode URL could be submitted multiple times, leading to redundant processing (scraping, transcription, embedding) and duplicate data in the database and vector store.

## Changes

Dedup is enforced at the database level via a `unique=True` constraint on the `Episode.url` field, introduced in Step 1. Any attempt to create a second episode with an identical URL raises `django.db.IntegrityError`, preventing duplicates before any downstream processing begins.

No additional code was needed for this step — the model constraint is the dedup mechanism.

## Key parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `url` unique constraint | `True` | Database-level enforcement is the most reliable dedup strategy — it works regardless of application-level checks or race conditions |

## Verification

```bash
uv run python manage.py test episodes
```

The `test_url_uniqueness` test in `episodes/tests.py` covers this:

1. Creates an episode with a given URL.
2. Attempts to create a second episode with the same URL.
3. Asserts that `IntegrityError` is raised.

You can also verify manually via the Django admin — submitting the same URL twice produces a validation error on the second attempt.

## Files modified

No files were modified for this step. The dedup mechanism was built into Step 1 via the `unique=True` constraint on `Episode.url` (`episodes/models.py`) and tested in `episodes/tests.py`.
