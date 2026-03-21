# Session: Step 1 — Submit Episode

**Date:** 2026-03-09
**Session ID:** da0710ab-70ef-4477-b261-c7844e6a9175

## Summary

*(No summary available)*

## Conversation

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/README.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Let's come up with a plan to implement Step 1 of the processing pipeline. Ask me any clarifying questions and do not start the implementation until we have come up with a plan.

### Assistant

Now let me check what's already been implemented.

So we're starting from scratch — no Django project exists yet. Step 1 is **Submit**: the user submits an episode page URL, and the episode is created with `pending` status.

Before planning, a few clarifying questions:

1. **Django project bootstrapping** — Should I set up the full Django project (`manage.py`, settings, etc.), the `episodes` app, and `pyproject.toml` with dependencies as part of this step? Or do you want that as a separate prerequisite step?

2. **Submission interface** — The spec mentions HTMX + Tailwind. For Step 1, do you want:
   - A full web form (HTML template with HTMX submission)?
   - Just the model + a Django admin interface for now?
   - Or a management command / API endpoint first, with UI later?

3. **Episode model scope** — Step 1 only needs `url` and `status`, but later steps need fields like `title`, `description`, `pub_date`, `image_url`, `language`, `audio_file`, `transcript`, `summary`, etc. Should I define the full model now (with nullable fields for future steps), or keep it minimal and add fields as we implement each step?

4. **Task queue** — Step 1 just creates the record. Should it also enqueue the pipeline (Django Q2) so Step 2 (dedup) kicks off automatically, or should triggering the pipeline be a separate concern?

5. **Validation** — Any specific URL validation beyond basic URL format? (e.g., restrict to known podcast domains, or accept any URL?)

### User

My answers:
1. Django project bootstrapping: set up the full Django project but only with the configuration resources and settings needed for the current step we are implementing
2. Just the model + a Django admin interface for now
3. Episode model scope: only the URL and status for the time being. Note that the status should not be user-editable since it will be used by the system to manage the processing status of an episode
4. Task queue: just store the record. We will introduce Django Q2 later.
5. Validation: only basic URL validation

### Assistant

This is a greenfield project so there's no codebase to explore. Let me go straight to writing the plan.

Now add `episodes` to `INSTALLED_APPS` in settings.

Now write the tests, then run migrations and tests.

All 5 tests pass.

Step 1 is complete. Here's what was created:

- [pyproject.toml](pyproject.toml) — Python 3.13 + Django 5.2 dependency
- **Django project** `ragtime/` — settings, urls, wsgi, asgi
- **`episodes` app** with:
  - [Episode model](episodes/models.py) — `url` (unique URLField), `status` (TextChoices with all pipeline statuses, defaults to `pending`), `created_at`, `updated_at`
  - [Admin interface](episodes/admin.py) — `status`, `created_at`, `updated_at` are read-only; user can only input the URL
  - [Tests](episodes/tests.py) — 5 tests covering default status, URL uniqueness, str representation, and admin page loading

To try it out:
```bash
uv run python manage.py createsuperuser
uv run python manage.py runserver
# Visit http://localhost:8000/admin/ and add an episode
```

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/CLAUDE.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Add the detailed plan in `doc/plans` as a mardown file.

### Assistant

Created [doc/plans/step-01-submit.md](doc/plans/step-01-submit.md).

### User

Rename the plan file to step-01-submit-episode.md

### Assistant

Done — renamed to [doc/plans/step-01-submit-episode.md](doc/plans/step-01-submit-episode.md).

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/CLAUDE.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Export the current session conversation to a Mardown file in `docs/sessions`.

### Assistant

Created [docs/sessions/2026-03-09-step-01-submit-episode.md](docs/sessions/2026-03-09-step-01-submit-episode.md).

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/CLAUDE.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Document this feature in the appropriate place in the project.

### Assistant

Now add the entry to README.md.

Done. Created:

- [doc/features/step-01-submit-episode.md](doc/features/step-01-submit-episode.md) — feature doc with Problem, Changes, Key parameters, Verification, and Files modified sections
- Added a **Features & Fixes** section to [README.md](README.md) with the entry linking to the feature doc

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/CLAUDE.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Commit changes for this feature and push them to the remote

### Assistant

I notice the session file was saved to `docs/sessions/` but CLAUDE.md references `doc/sessions/`. Let me fix that first.

There's both `docs/sessions/` (where I saved the file) and `doc/sessions/` (the convention from CLAUDE.md). Let me move the file to `doc/sessions/` and remove the stale `docs/` directory.

The file is already in the right place (`doc/sessions/`). Let me clean up the empty `docs/` directory.

Now stage and commit.

Committed and pushed. The commit `49cff35` includes all project files, the Episode model, admin config, tests, and the three doc files (plan, feature, session).
