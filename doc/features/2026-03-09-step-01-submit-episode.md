# Step 1: Submit Episode

**Date:** 2026-03-09

## Problem

RAGtime had no code — only a specification in README.md. The project needed a Django foundation and the first pipeline step: accepting an episode URL and tracking its processing status.

## Changes

- Bootstrapped a Django project (`ragtime`) with an `episodes` app.
- Created the `Episode` model with two core fields:
  - `url` — unique `URLField` for the episode page URL.
  - `status` — `CharField` using `TextChoices` with all pipeline statuses (`pending` through `ready`, plus `failed`). Defaults to `pending`.
  - `created_at` / `updated_at` timestamps for auditing.
- Registered the model in Django admin with `status`, `created_at`, and `updated_at` as read-only fields, so users can only submit a URL — the system manages status transitions.

## Key parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `url` max length | 200 (Django `URLField` default) | Sufficient for podcast episode URLs |
| `status` max length | 20 | Longest status value is `downloading` (11 chars); 20 gives headroom |
| `url` unique constraint | `True` | Enables dedup check in Step 2 without additional queries |

## Verification

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py test episodes       # 5 tests, all passing
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

1. Visit `http://localhost:8000/admin/` and log in.
2. Navigate to **Episodes > Add Episode**.
3. Enter a URL and save — the episode should appear with status `pending`.
4. Open the episode — `status`, `created_at`, and `updated_at` should be read-only.
5. Submitting the same URL again should fail with a uniqueness error.

## Files modified

| File | Summary |
|------|---------|
| `pyproject.toml` | Project metadata, Python 3.13, Django 5.2 dependency |
| `manage.py` | Django management script |
| `ragtime/settings.py` | Project settings with `episodes` in `INSTALLED_APPS` |
| `ragtime/urls.py` | Root URL config with admin site |
| `ragtime/wsgi.py` | WSGI entry point |
| `ragtime/asgi.py` | ASGI entry point |
| `episodes/models.py` | `Episode` model with `url`, `status`, timestamps |
| `episodes/admin.py` | `EpisodeAdmin` with read-only status and timestamps |
| `episodes/tests.py` | 5 tests covering model defaults, uniqueness, and admin views |
| `episodes/migrations/0001_initial.py` | Initial migration |
