from django.conf import settings

from .base import EmbeddingProvider, LLMProvider, TranscriptionProvider


def get_scraping_provider() -> LLMProvider:
    """Provider factory for the Fetch Details step.

    Transitional during the agent migration. Reads the new
    ``RAGTIME_FETCH_DETAILS_*`` env vars (Convention B model string) and
    splits the ``provider:model`` prefix back into the legacy
    ``OpenAILLMProvider`` constructor. Slated for deletion in the
    follow-up commit that replaces the call site with a Pydantic AI
    agent.
    """
    api_key = settings.RAGTIME_FETCH_DETAILS_API_KEY
    model_string = settings.RAGTIME_FETCH_DETAILS_MODEL

    if not api_key:
        raise ValueError("RAGTIME_FETCH_DETAILS_API_KEY is not set")

    if ":" in model_string:
        provider_name, _, model = model_string.partition(":")
    else:
        provider_name, model = "openai", model_string

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown fetch_details provider: {provider_name}")


def get_transcription_provider() -> TranscriptionProvider:
    provider_name = settings.RAGTIME_TRANSCRIPTION_PROVIDER
    api_key = settings.RAGTIME_TRANSCRIPTION_API_KEY
    model = settings.RAGTIME_TRANSCRIPTION_MODEL

    if not api_key:
        raise ValueError("RAGTIME_TRANSCRIPTION_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAITranscriptionProvider

        return OpenAITranscriptionProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown transcription provider: {provider_name}")


def get_summarization_provider() -> LLMProvider:
    provider_name = settings.RAGTIME_SUMMARIZATION_PROVIDER
    api_key = settings.RAGTIME_SUMMARIZATION_API_KEY
    model = settings.RAGTIME_SUMMARIZATION_MODEL

    if not api_key:
        raise ValueError("RAGTIME_SUMMARIZATION_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown summarization provider: {provider_name}")


def get_extraction_provider() -> LLMProvider:
    provider_name = settings.RAGTIME_EXTRACTION_PROVIDER
    api_key = settings.RAGTIME_EXTRACTION_API_KEY
    model = settings.RAGTIME_EXTRACTION_MODEL

    if not api_key:
        raise ValueError("RAGTIME_EXTRACTION_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown extraction provider: {provider_name}")


def get_resolution_provider() -> LLMProvider:
    provider_name = settings.RAGTIME_RESOLUTION_PROVIDER
    api_key = settings.RAGTIME_RESOLUTION_API_KEY
    model = settings.RAGTIME_RESOLUTION_MODEL

    if not api_key:
        raise ValueError("RAGTIME_RESOLUTION_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown resolution provider: {provider_name}")


def get_translation_provider() -> LLMProvider:
    provider_name = settings.RAGTIME_TRANSLATION_PROVIDER
    api_key = settings.RAGTIME_TRANSLATION_API_KEY
    model = settings.RAGTIME_TRANSLATION_MODEL

    if not api_key:
        raise ValueError("RAGTIME_TRANSLATION_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown translation provider: {provider_name}")


def get_embedding_provider() -> EmbeddingProvider:
    provider_name = settings.RAGTIME_EMBEDDING_PROVIDER
    api_key = settings.RAGTIME_EMBEDDING_API_KEY
    model = settings.RAGTIME_EMBEDDING_MODEL

    if not api_key:
        raise ValueError("RAGTIME_EMBEDDING_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown embedding provider: {provider_name}")
