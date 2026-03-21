# Session: manage.py configure — Planning

**Date:** 2026-03-13
**Session ID:** 9a0dcfdd-1c99-4928-ad51-695753dfb44d

## Summary

*(No summary available)*

## Conversation

### User

As you can see in the README file, in the "Configuration" section there are many API keys to configure. This is OK because we want to have the flexibility of using different providers and models for different steps in the pipeline. Nevertheless, this makes configuration difficult and we would like to provide a quicker more guided way to configure everything needed for the app to run. One way could be by implementing a cutom `uv run python manage.py configure` command. One requirement is that the API keys are not persisted or shown in logs. In future steps we will also need to configure other systems like ChromaDB and eventually other systems.

### Assistant

Let me explore the codebase to understand the current configuration landscape.

Now let me read the AGENTS.md for project conventions and check the README configuration section directly.

Now let me design the implementation approach.

Let me check if the management directory structure already exists.

Now I have everything I need. Let me also quickly check if there's a `.gitignore` entry for `.env`.

Good, `.env` is gitignored. Now let me write the plan.

Let me re-read the plan to recall where we left off.

This is the same task — the user re-entered plan mode on the configure command plan. The plan looks complete and ready. Let me ask the clarification question I had before finalizing.

Good — ask for provider even in shared mode, and only cover the 4 implemented systems. Let me update the plan with these decisions and finalize.

Plan is updated with both decisions. Also update the shared-mode description in the implementation section to reflect that provider is always prompted.

Good point — this is a project-wide feature, not episodes-specific. The management command should live under the `ragtime` app (the project-level Django app) instead.

Let me check what exists under the `ragtime/` directory.

The `ragtime/` directory is the project config app (settings, urls, wsgi, asgi) — not a typical Django app with models. The command needs to live somewhere that's in `INSTALLED_APPS`. Let me check what's installed.

The `ragtime/` directory is the Django project config (not in `INSTALLED_APPS`), so management commands can't live there directly. The standard approach is a new app for project-wide utilities.

What would you like to clarify about where the command should live? Do you have a preference for a specific app name or structure?

### User

What about calling the app "config" instead of "core"? Or can using "config" be missleading in a Django context?

### Assistant

`config` is a perfectly fine name — there's no conflict in Django. The only thing called `config` in the Django ecosystem is `django.apps.AppConfig`, but that's a class name, not an app label. You won't get any collisions with Django internals, and it clearly communicates the app's purpose.

The one consideration: if this app later grows to hold other project-wide utilities beyond configuration (e.g., shared template tags, health checks), the name `config` might feel narrow. But you can always rename or add another app later.

Got it — `core` app it is. Let me update the plan.

Also update the test path in verification.

What would you like to change about the plan?
