# Plan: Step 2 — Dedup

## Goal

Prevent duplicate episode submissions by checking whether an episode URL already exists in the database.

## Approach

Leverage the `unique=True` constraint on `Episode.url` (added in Step 1). The database itself rejects duplicate URLs via `IntegrityError`. No additional application-level query or pipeline step code is needed at this stage.

When the full pipeline is implemented, the dedup step will catch `IntegrityError` (or check `Episode.objects.filter(url=...).exists()`) and skip processing gracefully with a user-friendly message.

## Tasks

1. **Verify constraint exists** — Confirm `Episode.url` has `unique=True` in the model and migration.
2. **Verify test coverage** — Confirm `test_url_uniqueness` asserts `IntegrityError` on duplicate URL creation.
3. **Document** — Create feature documentation following project conventions.
