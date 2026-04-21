"""Views for Scott's chat UI.

``chat_page`` renders the shell template hosting the React island.
The ``api_*`` views back assistant-ui's ``threadList`` and ``history``
adapters:

- ``api_conversations`` / ``api_conversation_detail`` — list, create,
  rename, delete conversations.
- ``api_conversation_history`` — GET returns the full
  ``ExportedMessageRepository`` for a conversation; POST appends one
  ``ExportedMessageRepositoryItem``.
"""

from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from .models import Conversation, Message

logger = logging.getLogger(__name__)


def _serialize_conversation(conversation: Conversation) -> dict:
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _message_to_repository_item(message: Message) -> dict:
    """Render a :class:`Message` as an assistant-ui ``ExportedMessageRepositoryItem``."""
    item: dict = {
        "parentId": message.parent_external_id or None,
        "message": message.payload_json,
    }
    if message.run_config_json is not None:
        item["runConfig"] = message.run_config_json
    return item


@login_required
def chat_page(request: HttpRequest) -> HttpResponse:
    return render(request, "chat/index.html")


@login_required
@require_http_methods(["GET", "POST"])
def api_conversations(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        conversations = Conversation.objects.filter(user=request.user)
        return JsonResponse(
            {"conversations": [_serialize_conversation(c) for c in conversations]}
        )

    payload = _parse_json(request)
    if payload is None:
        return JsonResponse({"error": "invalid JSON body"}, status=400)
    conversation = Conversation.objects.create(
        user=request.user,
        title=payload.get("title", ""),
    )
    return JsonResponse(_serialize_conversation(conversation), status=201)


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def api_conversation_detail(
    request: HttpRequest, conversation_id: int
) -> JsonResponse:
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, user=request.user
    )

    if request.method == "GET":
        return JsonResponse(_serialize_conversation(conversation))

    if request.method == "PATCH":
        payload = _parse_json(request)
        if payload is None:
            return JsonResponse({"error": "invalid JSON body"}, status=400)
        if "title" in payload:
            conversation.title = payload["title"] or ""
            conversation.save(update_fields=["title", "updated_at"])
        return JsonResponse(_serialize_conversation(conversation))

    conversation.delete()
    return JsonResponse({"deleted": True})


@login_required
@require_http_methods(["GET", "POST"])
def api_conversation_history(
    request: HttpRequest, conversation_id: int
) -> JsonResponse:
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, user=request.user
    )

    if request.method == "GET":
        messages = [
            _message_to_repository_item(m) for m in conversation.messages.all()
        ]
        return JsonResponse({"messages": messages})

    payload = _parse_json(request)
    if payload is None:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    message_payload = payload.get("message")
    if not isinstance(message_payload, dict):
        return JsonResponse({"error": "'message' must be an object"}, status=400)

    external_id = message_payload.get("id")
    if not isinstance(external_id, str) or not external_id:
        return JsonResponse(
            {"error": "'message.id' is required and must be a non-empty string"},
            status=400,
        )

    parent_id = payload.get("parentId") or ""
    run_config = payload.get("runConfig")

    with transaction.atomic():
        # Upsert on (conversation, external_id). Duplicate appends can happen
        # when the assistant-ui client retries after a transient network error.
        message, _ = Message.objects.update_or_create(
            conversation=conversation,
            external_id=external_id,
            defaults={
                "parent_external_id": parent_id,
                "payload_json": message_payload,
                "run_config_json": run_config,
            },
        )
        conversation.save(update_fields=["updated_at"])

    return JsonResponse(_message_to_repository_item(message), status=201)


@login_required
@require_http_methods(["POST"])
async def api_generate_title(
    request: HttpRequest, conversation_id: int
) -> JsonResponse:
    from asgiref.sync import sync_to_async
    from pydantic_ai import Agent

    from .agent import build_model

    conversation = await sync_to_async(get_object_or_404)(
        Conversation, pk=conversation_id, user=request.user
    )

    payload = _parse_json(request)
    if payload is None:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    messages = payload.get("messages", [])
    snippets: list[str] = []
    for msg in messages[:4]:
        role = msg.get("role", "")
        parts = msg.get("content", [])
        text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        text = " ".join(text_parts).strip()
        if text:
            snippets.append(f"{role}: {text[:200]}")

    if not snippets:
        return JsonResponse({"title": ""})

    agent: Agent[None, str] = Agent(
        model=build_model(),
        instructions=(
            "Generate a concise conversation title (max 6 words). "
            "Return ONLY the title text, nothing else. No quotes."
        ),
    )
    try:
        result = await agent.run(
            "\n".join(snippets),
        )
        title = result.output.strip().strip('"').strip("'")[:80]
    except Exception:
        logger.exception("Title generation failed for conversation %d", conversation_id)
        return JsonResponse({"title": conversation.title or ""})
    conversation.title = title
    await sync_to_async(conversation.save)(update_fields=["title", "updated_at"])
    return JsonResponse({"title": title})


def _parse_json(request: HttpRequest) -> dict | None:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
