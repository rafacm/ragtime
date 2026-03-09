import json

from openai import OpenAI

from .base import LLMProvider


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
