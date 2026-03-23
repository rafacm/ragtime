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


def setup():
    """Eagerly initialize the Langfuse TracerProvider at startup.

    Called from ``EpisodesConfig.ready()``. When Langfuse is enabled, this
    ensures the OTel TracerProvider is registered before any pipeline step
    runs. No-op when disabled or during tests.
    """
    if not is_enabled():
        return
    try:
        import langfuse

        langfuse.get_client()
        logger.debug("Langfuse TracerProvider initialized")
    except ImportError:
        pass
    except Exception:
        logger.warning("Failed to initialize Langfuse TracerProvider", exc_info=True)


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


def _update_observation(**kwargs):
    """Update the current Langfuse observation. No-op when disabled."""
    if not is_enabled():
        return
    try:
        from langfuse.decorators import langfuse_context

        langfuse_context.update_current_observation(**kwargs)
    except (ImportError, Exception):
        pass


def set_observation_input(system_prompt, user_content, *, response_schema=None):
    """Set the current Langfuse observation's input in chat-message format.

    Works around the Langfuse OpenAI wrapper not parsing ``instructions``
    from the Responses API into the system prompt field. Call this from
    provider methods before the API call. No-op when disabled.

    When *response_schema* is provided, it is logged in metadata as
    ``response_schema`` (the RAGtime equivalent of ``tool_definitions``).
    """
    update_kwargs = {
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if response_schema is not None:
        update_kwargs["metadata"] = {"response_schema": response_schema}

    _update_observation(**update_kwargs)


def set_observation_output(output):
    """Set the current Langfuse observation's output.

    Call this from provider methods after the API call to log the
    structured response. No-op when disabled.
    """
    _update_observation(output=output)


def observe_provider(func):
    """Decorator that wraps a provider method with its own Langfuse span.

    Creates a child span under the current step trace so that
    ``set_observation_input`` and ``set_observation_output`` update this
    span's fields (not the parent step trace). The auto-captured OpenAI
    generation becomes a grandchild of the step trace.

    No-op when Langfuse is disabled. Designed for instance methods (skips
    ``self`` when capturing arguments).
    """
    observed = None

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        nonlocal observed

        if not is_enabled():
            return func(self, *args, **kwargs)

        try:
            from langfuse import observe as langfuse_observe
        except ImportError:
            return func(self, *args, **kwargs)

        if observed is None:
            observed = langfuse_observe(name=func.__name__)(func)

        return observed(self, *args, **kwargs)

    return wrapper


def observe_step(name):
    """Decorator factory that wraps a pipeline step with Langfuse tracing.

    The decorated function must accept ``episode_id`` as its first argument.
    When enabled, the wrapper creates a Langfuse trace named *name* with
    ``session_id`` set to ``processing-run-{pk}-episode-{id}-{timestamp}``.

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

            if run:
                ts = run.started_at.strftime("%Y-%m-%d-%H-%M")
                session_id = f"processing-run-{run.pk}-episode-{episode_id}-{ts}"
            else:
                session_id = f"episode-{episode_id}"

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
