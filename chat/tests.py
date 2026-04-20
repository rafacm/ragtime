"""Tests for Scott — the RAG chatbot.

Covers:
- :func:`episodes.vector_store.search_chunks` with a faked Qdrant backend.
- Scott agent behavior: mandatory tool call, refusal on empty retrieval,
  citation integrity (every ``[N]`` maps to ``ScottState.retrieved_chunks``).
- Chat API endpoints: auth gating + basic CRUD scoped to the owner.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from pydantic_ai.ag_ui import StateDeps
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chat.agent import ScottState, get_scott_agent
from chat.models import Conversation, Message
from episodes.vector_store import ChunkSearchResult


def _chunk(
    chunk_id: int,
    title: str = "Test Episode",
    text: str = "lorem ipsum",
    score: float = 0.75,
    start: float = 10.0,
    end: float = 40.0,
) -> ChunkSearchResult:
    return ChunkSearchResult(
        chunk_id=chunk_id,
        episode_id=1,
        episode_title=title,
        episode_url="https://example.com/ep1",
        episode_image_url="",
        start_time=start,
        end_time=end,
        language="en",
        text=text,
        score=score,
    )


class SearchChunksTests(TestCase):
    """``episodes.vector_store.search_chunks`` end-to-end with faked plumbing."""

    def test_passes_filter_and_threshold_to_store(self):
        captured = {}

        class FakeStore:
            def search(
                self, query_vector, top_k, episode_id=None, score_threshold=None
            ):
                captured.update(
                    {
                        "dim": len(query_vector),
                        "top_k": top_k,
                        "episode_id": episode_id,
                        "score_threshold": score_threshold,
                    }
                )
                return [_chunk(42)]

        class FakeEmbedder:
            def embed(self, texts):
                return [[0.1] * 8 for _ in texts]

        from episodes import vector_store

        with (
            patch.object(vector_store, "get_vector_store", return_value=FakeStore()),
            patch(
                "episodes.providers.factory.get_embedding_provider",
                return_value=FakeEmbedder(),
            ),
        ):
            results = vector_store.search_chunks(
                "miles davis", top_k=3, episode_id=7, score_threshold=0.42
            )

        assert [r.chunk_id for r in results] == [42]
        assert captured == {
            "dim": 8,
            "top_k": 3,
            "episode_id": 7,
            "score_threshold": 0.42,
        }


@override_settings(RAGTIME_SCOTT_API_KEY="sk-test-placeholder")
class ScottAgentBehaviorTests(TestCase):
    """Verify the strict-RAG contract against a scripted LLM."""

    def setUp(self):
        # Reset the cached agent so tests that patch the model get a fresh one.
        get_scott_agent.cache_clear()
        self.deps = StateDeps(ScottState())

    @staticmethod
    def _fake_search(results):
        def _impl(query, top_k=5, episode_id=None, score_threshold=None):
            return results

        return _impl

    def _install_model(self, script):
        agent = get_scott_agent()
        calls = {"n": 0}

        def responder(messages: list[ModelMessage], info: AgentInfo):
            idx = calls["n"]
            calls["n"] += 1
            return script[idx]

        return agent.override(model=FunctionModel(responder)), calls

    def test_refusal_when_no_chunks(self):
        script = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_chunks_tool",
                        args={"query": "mystery artist"},
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    TextPart(
                        content=(
                            "No podcast content covers that — I can't answer "
                            "from general knowledge."
                        )
                    )
                ]
            ),
        ]

        with patch(
            "chat.agent.search_chunks",
            side_effect=self._fake_search([]),
        ):
            override, calls = self._install_model(script)
            with override:
                result = get_scott_agent().run_sync(
                    "Tell me about mystery artist", deps=self.deps
                )

        assert calls["n"] == 2
        assert self.deps.state.retrieved_chunks == []
        assert "can't answer" in result.output.lower()

    def test_citation_indices_all_map_to_state(self):
        chunks = [_chunk(1, title="Ep 1"), _chunk(2, title="Ep 2")]
        script = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_chunks_tool",
                        args={"query": "kind of blue"},
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    TextPart(
                        content=(
                            "Kind of Blue is discussed on the show [1], and "
                            "its modal style is explored further [2]."
                        )
                    )
                ]
            ),
        ]

        with patch(
            "chat.agent.search_chunks",
            side_effect=self._fake_search(chunks),
        ):
            override, _ = self._install_model(script)
            with override:
                result = get_scott_agent().run_sync(
                    "What do they say about Kind of Blue?", deps=self.deps
                )

        state = self.deps.state
        assert [c["chunk_id"] for c in state.retrieved_chunks] == [1, 2]

        cited = {int(m) for m in re.findall(r"\[(\d+)\]", result.output)}
        assert cited, "LLM did not emit any [N] markers"
        for idx in cited:
            assert 1 <= idx <= len(state.retrieved_chunks), (
                f"Citation [{idx}] out of range: state has "
                f"{len(state.retrieved_chunks)} chunks"
            )


class ChatAPITests(TestCase):
    """Auth gating + CRUD for the assistant-ui persistence endpoints."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice", password="secret-pass"
        )

    def test_chat_page_requires_login(self):
        response = self.client.get(reverse("chat:page"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_asgi_agent_route_rejects_anonymous(self):
        """Exercise the ASGI dispatcher: /chat/agent/ without a session → 401."""
        from ragtime.asgi import application

        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/chat/agent/",
            "headers": [],
        }
        asyncio.run(application(scope, receive, send))

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 401

    def test_conversation_lifecycle(self):
        self.client.force_login(self.user)

        created = self.client.post(
            reverse("chat:conversations"),
            data=json.dumps({"title": "Blue Notes"}),
            content_type="application/json",
        )
        assert created.status_code == 201
        conv_id = created.json()["id"]

        listing = self.client.get(reverse("chat:conversations"))
        assert listing.status_code == 200
        assert [c["id"] for c in listing.json()["conversations"]] == [conv_id]

        msg = self.client.post(
            reverse("chat:conversation_messages", args=[conv_id]),
            data=json.dumps(
                {"role": "user", "content": [{"type": "text", "text": "hello"}]}
            ),
            content_type="application/json",
        )
        assert msg.status_code == 201

        detail = self.client.get(
            reverse("chat:conversation_detail", args=[conv_id])
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["title"] == "Blue Notes"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"

        deleted = self.client.delete(
            reverse("chat:conversation_detail", args=[conv_id])
        )
        assert deleted.status_code == 200
        assert not Conversation.objects.filter(pk=conv_id).exists()
        assert not Message.objects.filter(conversation_id=conv_id).exists()

    def test_conversations_are_scoped_to_owner(self):
        other = get_user_model().objects.create_user(
            username="bob", password="secret-pass"
        )
        Conversation.objects.create(user=other, title="not mine")

        self.client.force_login(self.user)
        listing = self.client.get(reverse("chat:conversations"))
        assert listing.status_code == 200
        assert listing.json()["conversations"] == []

    def test_invalid_role_rejected(self):
        conv = Conversation.objects.create(user=self.user, title="t")
        self.client.force_login(self.user)
        bad = self.client.post(
            reverse("chat:conversation_messages", args=[conv.pk]),
            data=json.dumps({"role": "banana", "content": []}),
            content_type="application/json",
        )
        assert bad.status_code == 400


class ChunkSearchResultShapeTests(TestCase):
    """Regression: the dataclass shape matches what the agent state stores."""

    def test_asdict_round_trip_keeps_required_fields(self):
        chunk = _chunk(99)
        data = asdict(chunk)
        for field in (
            "chunk_id",
            "episode_id",
            "episode_title",
            "episode_url",
            "episode_image_url",
            "start_time",
            "end_time",
            "language",
            "text",
            "score",
        ):
            assert field in data
