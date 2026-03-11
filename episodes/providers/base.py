from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def structured_extract(
        self, system_prompt: str, user_content: str, response_schema: dict
    ) -> dict:
        """Send prompt + content to LLM, return structured JSON dict."""
        ...

    @abstractmethod
    def generate(self, system_prompt: str, user_content: str) -> str:
        """Send prompt + content to LLM, return plain text."""
        ...


class TranscriptionProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        """Transcribe audio file, return transcript with timestamps."""
        ...


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...
