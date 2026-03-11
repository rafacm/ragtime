import json

from openai import OpenAI

from .base import LLMProvider, TranscriptionProvider


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def structured_extract(
        self, system_prompt: str, user_content: str, response_schema: dict
    ) -> dict:
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_content,
            text={"format": {"type": "json_schema", **response_schema}},
        )
        return json.loads(response.output_text)


class OpenAITranscriptionProvider(TranscriptionProvider):
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
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
            return response.model_dump()
        finally:
            kwargs["file"].close()
