from django.conf import settings

from .base import LLMProvider, TranscriptionProvider


def get_scraping_provider() -> LLMProvider:
    provider_name = settings.RAGTIME_SCRAPING_PROVIDER
    api_key = settings.RAGTIME_SCRAPING_API_KEY
    model = settings.RAGTIME_SCRAPING_MODEL

    if not api_key:
        raise ValueError("RAGTIME_SCRAPING_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown scraping provider: {provider_name}")


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
