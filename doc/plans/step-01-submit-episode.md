# Step 1: Submit — Django Project Bootstrap + Episode Model

## Context

RAGtime has no code yet — only README.md, CLAUDE.md, LICENSE, and .gitignore. This step bootstraps the Django project and implements the first pipeline step: a user submits an episode URL, creating a record with `pending` status. The admin interface is the only UI for now.

## Plan

### 1. Initialize `pyproject.toml`

- Python 3.13, Django 5.2 as the only dependency (minimal for this step)
- Project metadata (name, version, description)
- No build-system (app, not library — per CLAUDE.md)

### 2. Create Django project: `ragtime`

- `uv run django-admin startproject ragtime .` (dot = no nested directory)
- Produces: `manage.py`, `ragtime/settings.py`, `ragtime/urls.py`, `ragtime/wsgi.py`, `ragtime/asgi.py`

### 3. Create Django app: `episodes`

- `uv run python manage.py startapp episodes`
- Register in `INSTALLED_APPS`

### 4. Configure `settings.py`

- Add `episodes` to `INSTALLED_APPS`
- Skip `python-dotenv` for now — no env vars needed for Step 1
- `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` (Django 5.2 default)
- SQLite as the default DB (Django's default)

### 5. Define `Episode` model (`episodes/models.py`)

```python
class Episode(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        DOWNLOADING = "downloading"
        TRANSCRIBING = "transcribing"
        SUMMARIZING = "summarizing"
        EXTRACTING = "extracting"
        RESOLVING = "resolving"
        EMBEDDING = "embedding"
        READY = "ready"
        FAILED = "failed"

    url = models.URLField(unique=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

- `url` is unique — supports dedup check in Step 2
- `status` uses TextChoices with all pipeline statuses (cheap to define upfront)
- Timestamps for auditing

### 6. Admin interface (`episodes/admin.py`)

```python
@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("url", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("status", "created_at", "updated_at")
```

- `status` is read-only in admin (system-managed, not user-editable)
- User can only input the URL when adding an episode
- `created_at` and `updated_at` also read-only

### 7. Generate and apply migrations

```bash
uv run python manage.py makemigrations episodes
uv run python manage.py migrate
```

### 8. Write tests (`episodes/tests.py`)

- Default status is `pending` on creation
- URL uniqueness constraint enforced
- `__str__` returns the URL
- Admin changelist and add form load correctly

## Files created/modified

| File | Action |
|------|--------|
| `pyproject.toml` | Create — project metadata + Django dependency |
| `manage.py` | Create (via startproject) |
| `ragtime/__init__.py` | Create (via startproject) |
| `ragtime/settings.py` | Create + modify (add episodes app) |
| `ragtime/urls.py` | Create (via startproject) |
| `ragtime/wsgi.py` | Create (via startproject) |
| `ragtime/asgi.py` | Create (via startproject) |
| `episodes/__init__.py` | Create (via startapp) |
| `episodes/models.py` | Create — Episode model |
| `episodes/admin.py` | Create — EpisodeAdmin |
| `episodes/tests.py` | Create — basic tests |
| `episodes/migrations/0001_initial.py` | Create (via makemigrations) |

## Verification

```bash
uv sync                                    # Install dependencies
uv run python manage.py migrate            # Apply migrations
uv run python manage.py test episodes      # Run tests (5 tests, all passing)
uv run python manage.py createsuperuser    # Create admin user
uv run python manage.py runserver          # Start dev server
# Visit http://localhost:8000/admin/ → Add an episode URL → verify status is "pending" and read-only
```
