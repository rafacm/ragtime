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
directly. ``os.environ`` is **never** mutated — long-lived workers
that build multiple agents with different keys (e.g. ``fetch_details``
and ``recovery``) keep their credentials isolated. When the key is
empty or the provider's SDK isn't installed, the function returns the
raw model string and lets Pydantic AI's own env-var resolution
(``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` / ``GOOGLE_API_KEY`` …)
handle authentication.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_model(model_string: str, api_key: str) -> Any:
    """Build a Pydantic AI ``Model`` for *model_string* + *api_key*.

    *model_string* is Convention B (``provider:model``), e.g.
    ``openai:gpt-4.1-mini`` or ``anthropic:claude-sonnet-4-20250514``.
    Returns a concrete ``Model`` instance when the provider is known and
    its SDK is installed; otherwise returns the raw string and lets
    Pydantic AI fall back to its own env-var resolution. When *api_key*
    is empty, always falls through to env-var resolution without
    touching ``os.environ``.
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
                "Anthropic SDK not installed — falling back to env-var "
                "resolution for %s. Install with: "
                "uv pip install 'pydantic-ai-slim[anthropic]'",
                model_string,
            )
            return model_string
        return AnthropicModel(
            model_name, provider=AnthropicProvider(api_key=api_key)
        )

    if provider_name == "google":
        try:
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider
        except ImportError:
            logger.warning(
                "Google SDK not installed — falling back to env-var "
                "resolution for %s. Install with: "
                "uv pip install 'pydantic-ai-slim[google]'",
                model_string,
            )
            return model_string
        return GoogleModel(
            model_name, provider=GoogleProvider(api_key=api_key)
        )

    # Unknown provider — return the raw string and let Pydantic AI's
    # own resolution handle it. Never mutate os.environ.
    logger.warning(
        "Unknown provider %r in model string %r — falling back to "
        "Pydantic AI env-var resolution; the configured api_key will "
        "be ignored unless the same value is set in the provider's "
        "ambient env var.",
        provider_name,
        model_string,
    )
    return model_string
