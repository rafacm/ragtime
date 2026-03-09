# Session: Step 1 — Submit Episode

**Date:** 2026-03-09

## Goal

Implement Step 1 of the RAGtime processing pipeline: bootstrapping the Django project and creating the Episode model with admin interface.

---

## Conversation

### User

Let's come up with a plan to implement Step 1 of the processing pipeline. Ask me any clarifying questions and do not start the implementation until we have come up with a plan.

### Assistant

Before planning, a few clarifying questions:

1. **Django project bootstrapping** — Should I set up the full Django project (`manage.py`, settings, etc.), the `episodes` app, and `pyproject.toml` with dependencies as part of this step? Or do you want that as a separate prerequisite step?
2. **Submission interface** — The spec mentions HTMX + Tailwind. For Step 1, do you want a full web form, just the model + Django admin, or a management command / API endpoint first?
3. **Episode model scope** — Step 1 only needs `url` and `status`, but later steps need more fields. Should I define the full model now (with nullable fields) or keep it minimal?
4. **Task queue** — Step 1 just creates the record. Should it also enqueue the pipeline (Django Q2) so Step 2 kicks off automatically?
5. **Validation** — Any specific URL validation beyond basic URL format?

### User

My answers:

1. Django project bootstrapping: set up the full Django project but only with the configuration resources and settings needed for the current step we are implementing
2. Just the model + a Django admin interface for now
3. Episode model scope: only the URL and status for the time being. Note that the status should not be user-editable since it will be used by the system to manage the processing status of an episode
4. Task queue: just store the record. We will introduce Django Q2 later.
5. Validation: only basic URL validation

### Assistant

Created a plan covering:

1. **`pyproject.toml`** — Python 3.13, Django 5.2, no build-system
2. **Django project** — `ragtime` via `startproject`
3. **`episodes` app** — registered in `INSTALLED_APPS`
4. **`settings.py`** — minimal config, SQLite default, skip dotenv for now
5. **Episode model** — `url` (unique URLField), `status` (TextChoices with all pipeline statuses, default `pending`), `created_at`, `updated_at`
6. **Admin interface** — `status`, `created_at`, `updated_at` read-only; user can only input URL
7. **Migrations** — generate and apply
8. **Tests** — default status, URL uniqueness, str representation, admin pages load

### User

*(Approved the plan)*

### Assistant

Implemented the plan:

#### Files created

| File | Description |
|------|-------------|
| `pyproject.toml` | Project metadata + Django 5.2 dependency |
| `manage.py` | Django management script (via startproject) |
| `ragtime/` | Django project package (settings, urls, wsgi, asgi) |
| `episodes/models.py` | Episode model with Status TextChoices |
| `episodes/admin.py` | EpisodeAdmin with read-only status |
| `episodes/tests.py` | 5 tests (model + admin) |
| `episodes/migrations/0001_initial.py` | Initial migration |

#### Episode model

```python
class Episode(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        DOWNLOADING = "downloading"
        TRANSCRIBING = "transcribing"
        SUMMARIZING = "summarizing"
        EXTRACTING = "extracting"
        DEDUPLICATING = "deduplicating"
        EMBEDDING = "embedding"
        READY = "ready"
        FAILED = "failed"

    url = models.URLField(unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

#### Admin interface

```python
@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("url", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("status", "created_at", "updated_at")
```

#### Test results

```
Ran 5 tests in 0.279s — OK
```

Tests cover: default pending status, URL uniqueness constraint, `__str__`, admin changelist, admin add form.

### User

Add the detailed plan in `doc/plans` as a markdown file.

### Assistant

Created `doc/plans/step-01-submit-episode.md` with the full plan.

---

## Verification

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py test episodes      # 5 tests, all passing
uv run python manage.py createsuperuser
uv run python manage.py runserver
# Visit http://localhost:8000/admin/ → Add an episode URL → status is "pending" and read-only
```
