from django.conf import settings

from .base import LLMProvider, TranscriptionProvider


def get_llm_provider() -> LLMProvider:
    provider_name = settings.RAGTIME_LLM_PROVIDER
    api_key = settings.RAGTIME_LLM_API_KEY
    model = settings.RAGTIME_LLM_MODEL

    if not api_key:
        raise ValueError("RAGTIME_LLM_API_KEY is not set")

    if provider_name == "openai":
        from .openai import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)

    raise ValueError(f"Unknown LLM provider: {provider_name}")


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
