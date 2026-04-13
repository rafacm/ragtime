import json
import os

from openai import OpenAI

from episodes.telemetry import record_llm_input, record_llm_output, trace_provider

from .base import LLMProvider, TranscriptionProvider


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    @trace_provider
    def structured_extract(
        self, system_prompt: str, user_content: str, response_schema: dict
    ) -> dict:
        record_llm_input(
            system_prompt, user_content, response_schema=response_schema
        )
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_content,
            text={"format": {"type": "json_schema", **response_schema}},
        )
        result = json.loads(response.output_text)
        record_llm_output(result)
        return result

    @trace_provider
    def generate(self, system_prompt: str, user_content: str) -> str:
        record_llm_input(system_prompt, user_content)
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_content,
        )
        record_llm_output(response.output_text)
        return response.output_text


class OpenAITranscriptionProvider(TranscriptionProvider):
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    TRANSCRIPTION_RESPONSE_FORMAT = "verbose_json"
    TRANSCRIPTION_TIMESTAMP_GRANULARITIES = ["word", "segment"]

    @trace_provider
    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        record_llm_input(
            audio_file=os.path.basename(audio_path),
            model=self.model,
            language=language,
            response_format=self.TRANSCRIPTION_RESPONSE_FORMAT,
            timestamp_granularities=self.TRANSCRIPTION_TIMESTAMP_GRANULARITIES,
        )
        kwargs = {
            "model": self.model,
            "file": open(audio_path, "rb"),
            "response_format": self.TRANSCRIPTION_RESPONSE_FORMAT,
            "timestamp_granularities": self.TRANSCRIPTION_TIMESTAMP_GRANULARITIES,
        }
        if language:
            kwargs["language"] = language
        try:
            response = self.client.audio.transcriptions.create(**kwargs)
            result = response.model_dump()
            summary = {
                "text": result.get("text"),
                "duration": result.get("duration"),
                "language": result.get("language"),
            }
            words = result.get("words")
            if isinstance(words, list):
                summary["words_count"] = len(words)
            segments = result.get("segments")
            if isinstance(segments, list):
                summary["segments_count"] = len(segments)
            record_llm_output(summary)
            return result
        finally:
            kwargs["file"].close()
