"""Shared Pydantic AI model factory.

Pure helper used by every step-agent's ``get_agent()`` factory: takes a
Convention B model string (``provider:model``) and an API key, returns a
Pydantic AI ``Model`` (or a model string fallback) that can be passed to
``Agent(...)``.

No Django imports — settings reads happen in the caller's factory so
the agent module stays bootable in tests via
``from episodes.agents.fetch_details import run, EpisodeDetails``
without a Django app registry.

Credential isolation: when an API key is supplied, ``build_model``
constructs a concrete ``Model`` whose provider receives the key
directly. ``os.environ`` is **never** mutated permanently — long-lived
workers that build multiple agents with different keys (e.g.
``fetch_details`` and ``recovery``) keep their credentials isolated.

If a provider's SDK can't be imported through Pydantic AI's submodule
(e.g. a transitive version skew), ``build_model`` falls back to
Pydantic AI's own ``infer_model`` resolver inside a temporarily-scoped
env var: the configured ``RAGTIME_*_API_KEY`` is exposed via
``ANTHROPIC_API_KEY`` / ``GOOGLE_API_KEY`` only for the duration of
model construction (the env var is restored, even on exception). The
constructed provider captures the key into its HTTP client during
construction, so the value never persists in the process. This
preserves credential isolation across agents even when our concrete
branch can't be reached.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Per-provider env vars used by Pydantic AI's default resolution. Used
# only by the env-scoped fallback when the concrete provider class
# can't be imported.
_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


@contextlib.contextmanager
def _temp_env(name: str, value: str) -> Iterator[None]:
    """Set an env var for the duration of the ``with`` block, then restore."""
    prev = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prev


def _build_via_pydantic_ai_resolver(
    model_string: str, env_var: str, api_key: str
) -> Any:
    """Build a Model via Pydantic AI's own ``infer_model`` with the env scoped.

    Used when our concrete provider branch can't be reached (the
    submodule import fails for a known provider). ``infer_model``
    constructs the provider, which captures the key from the env at
    that moment into its SDK client; the env var is restored before
    this function returns, so concurrent / subsequent builds for other
    agents don't pick up the key.
    """
    with _temp_env(env_var, api_key):
        # Late import so we can fall back to the raw model string if
        # even the resolver entry point can't be imported.
        from pydantic_ai.models import infer_model

        return infer_model(model_string)


def build_model(model_string: str, api_key: str) -> Any:
    """Build a Pydantic AI ``Model`` for *model_string* + *api_key*.

    *model_string* is Convention B (``provider:model``), e.g.
    ``openai:gpt-4.1-mini`` or ``anthropic:claude-sonnet-4-20250514``.
    Returns a concrete ``Model`` instance when the provider is known
    and importable; otherwise (a) for ``anthropic``/``google`` whose
    submodule import fails in this environment, falls back to the
    env-scoped resolver so the configured key still wins over any
    ambient env var; (b) for unknown providers, returns the raw model
    string and lets Pydantic AI handle it (an explicit warning fires
    because ambient credentials may take precedence). When *api_key*
    is empty, always returns the raw string so the user's own env
    setup stays in charge.
    """
    if not api_key:
        return model_string

    if ":" in model_string:
        provider_name, _, model_name = model_string.partition(":")
    else:
        provider_name, model_name = "openai", model_string

    if provider_name == "openai":
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIResponsesModel(
            model_name, provider=OpenAIProvider(api_key=api_key)
        )

    if provider_name == "anthropic":
        try:
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider
        except ImportError:
            logger.warning(
                "pydantic_ai.models.anthropic not importable in this "
                "environment for %s — falling back to Pydantic AI's "
                "resolver with ANTHROPIC_API_KEY scoped to the "
                "configured key. Install/upgrade with: "
                "uv pip install -U 'pydantic-ai-slim[anthropic]'",
                model_string,
            )
            return _build_via_pydantic_ai_resolver(
                model_string, _PROVIDER_ENV_VARS["anthropic"], api_key
            )
        return AnthropicModel(
            model_name, provider=AnthropicProvider(api_key=api_key)
        )

    if provider_name == "google":
        try:
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider
        except ImportError:
            logger.warning(
                "pydantic_ai.models.google not importable in this "
                "environment for %s — falling back to Pydantic AI's "
                "resolver with GOOGLE_API_KEY scoped to the "
                "configured key. Install/upgrade with: "
                "uv pip install -U 'pydantic-ai-slim[google]'",
                model_string,
            )
            return _build_via_pydantic_ai_resolver(
                model_string, _PROVIDER_ENV_VARS["google"], api_key
            )
        return GoogleModel(
            model_name, provider=GoogleProvider(api_key=api_key)
        )

    # Unknown provider — we don't know which env var Pydantic AI will
    # consult, so we can't safely scope it. Return the raw string and
    # warn loudly: any ambient env var matching the provider's
    # convention will silently win over the configured api_key.
    logger.warning(
        "Unknown provider %r in model string %r — falling back to "
        "Pydantic AI env-var resolution; the configured api_key may "
        "be ignored if the provider's ambient env var is set.",
        provider_name,
        model_string,
    )
    return model_string
