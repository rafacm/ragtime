"""Optional Langfuse observability layer for LLM calls.

When ``RAGTIME_LANGFUSE_ENABLED`` is true **and** both API keys are set,
every OpenAI call is auto-traced (via ``langfuse.openai.OpenAI``) and each
pipeline step is wrapped with ``@observe()`` grouped by ``ProcessingRun``.

When disabled (the default) there is zero overhead — Langfuse is never imported.
"""

import functools
import logging
import os
import sys

from django.conf import settings

logger = logging.getLogger(__name__)


def is_enabled():
    """Return True when Langfuse tracing is fully configured.

    Also sets ``LANGFUSE_*`` env vars from Django settings so the SDK picks
    them up automatically.
    """
    # Never trace during test runs
    if "test" in sys.argv:
        return False

    enabled = getattr(settings, "RAGTIME_LANGFUSE_ENABLED", False)
    secret_key = getattr(settings, "RAGTIME_LANGFUSE_SECRET_KEY", "")
    public_key = getattr(settings, "RAGTIME_LANGFUSE_PUBLIC_KEY", "")

    if not (enabled and secret_key and public_key):
        return False

    host = getattr(settings, "RAGTIME_LANGFUSE_HOST", "http://localhost:3000")
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    os.environ.setdefault("LANGFUSE_HOST", host)
    return True


def get_openai_client_class():
    """Return ``langfuse.openai.OpenAI`` when enabled, else ``openai.OpenAI``."""
    if is_enabled():
        try:
            from langfuse.openai import OpenAI

            return OpenAI
        except ImportError:
            logger.warning(
                "Langfuse enabled but not installed — falling back to openai.OpenAI"
            )

    from openai import OpenAI

    return OpenAI


def observe_step(name):
    """Decorator factory that wraps a pipeline step with Langfuse tracing.

    The decorated function must accept ``episode_id`` as its first argument.
    When enabled, the wrapper creates a Langfuse trace named *name* with
    ``session_id`` set to the active ``ProcessingRun.pk``.

    Returns a no-op passthrough when Langfuse is disabled.
    """
    def decorator(func):
        observed_func = None

        @functools.wraps(func)
        def wrapper(episode_id, *args, **kwargs):
            nonlocal observed_func

            if not is_enabled():
                return func(episode_id, *args, **kwargs)

            try:
                from langfuse import observe as langfuse_observe
                from langfuse import propagate_attributes
            except ImportError:
                return func(episode_id, *args, **kwargs)

            from .models import Episode, ProcessingRun

            run = (
                ProcessingRun.objects.filter(
                    episode_id=episode_id,
                    status=ProcessingRun.Status.RUNNING,
                )
                .order_by("-started_at")
                .first()
            )

            # Build descriptive session ID: "run-42-ep-1" instead of "42"
            session_id = (
                f"run-{run.pk}-ep-{episode_id}" if run else f"ep-{episode_id}"
            )

            try:
                episode = Episode.objects.get(pk=episode_id)
            except Episode.DoesNotExist:
                episode = None

            user_id = f"episode-{episode_id}"

            metadata = {"episode_id": str(episode_id)}
            if episode and episode.title:
                metadata["episode_title"] = episode.title

            if observed_func is None:
                observed_func = langfuse_observe(name=name)(func)

            with propagate_attributes(
                session_id=session_id, user_id=user_id, metadata=metadata
            ):
                observed_func(episode_id, *args, **kwargs)

            # Return episode status as trace output (step functions return None)
            if episode:
                episode.refresh_from_db(fields=["status"])
                return {"status": episode.status, "episode_id": episode_id}
            return {"status": "unknown", "episode_id": episode_id}

        return wrapper
    return decorator
