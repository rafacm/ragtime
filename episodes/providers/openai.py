import json

from episodes.observability import (
    get_openai_client_class,
    observe_provider,
    set_observation_input,
    set_observation_output,
)

from .base import LLMProvider, TranscriptionProvider


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        OpenAI = get_openai_client_class()
        self.client = OpenAI(api_key=api_key)
        self.model = model

    @observe_provider
    def structured_extract(
        self, system_prompt: str, user_content: str, response_schema: dict
    ) -> dict:
        set_observation_input(
            system_prompt, user_content, response_schema=response_schema
        )
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_content,
            text={"format": {"type": "json_schema", **response_schema}},
        )
        result = json.loads(response.output_text)
        set_observation_output(result)
        return result

    @observe_provider
    def generate(self, system_prompt: str, user_content: str) -> str:
        set_observation_input(system_prompt, user_content)
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_content,
        )
        set_observation_output(response.output_text)
        return response.output_text


class OpenAITranscriptionProvider(TranscriptionProvider):
    def __init__(self, api_key: str, model: str):
        OpenAI = get_openai_client_class()
        self.client = OpenAI(api_key=api_key)
        self.model = model

    @observe_provider
    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        set_observation_input(
            audio_path=audio_path,
            model=self.model,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
        kwargs = {
            "model": self.model,
            "file": open(audio_path, "rb"),
            "response_format": "verbose_json",
            "timestamp_granularities": ["word", "segment"],
        }
        if language:
            kwargs["language"] = language
        try:
            response = self.client.audio.transcriptions.create(**kwargs)
            result = response.model_dump()
            set_observation_output(result)
            return result
        finally:
            kwargs["file"].close()
