"""Optional Langfuse observability layer for LLM calls.

When ``RAGTIME_LANGFUSE_ENABLED`` is true **and** both API keys are set,
every OpenAI call is auto-traced (via ``langfuse.openai.OpenAI``) and each
pipeline step is wrapped with ``@observe()`` grouped by ``ProcessingRun``.

When disabled (the default) there is zero overhead — Langfuse is never imported.
"""

import functools
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def is_enabled():
    """Return True when Langfuse tracing is fully configured.

    Also sets ``LANGFUSE_*`` env vars from Django settings so the SDK picks
    them up automatically.
    """
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
        @functools.wraps(func)
        def wrapper(episode_id, *args, **kwargs):
            if not is_enabled():
                return func(episode_id, *args, **kwargs)

            try:
                from langfuse import observe as langfuse_observe
                from langfuse import propagate_attributes
            except ImportError:
                return func(episode_id, *args, **kwargs)

            from .models import Episode
            from .processing import get_active_run

            try:
                episode = Episode.objects.get(pk=episode_id)
            except Episode.DoesNotExist:
                return func(episode_id, *args, **kwargs)

            run = get_active_run(episode)
            session_id = str(run.pk) if run else None
            metadata = {"episode_id": episode_id}

            observed_func = langfuse_observe(name=name)(func)

            with propagate_attributes(
                session_id=session_id, metadata=metadata
            ):
                return observed_func(episode_id, *args, **kwargs)

        return wrapper
    return decorator
