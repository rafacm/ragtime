"""Views for Scott's chat UI.

``chat_page`` renders the shell template hosting the React island. The
``api_*`` views back assistant-ui's ``threadList`` and ``history`` adapters.
They pass opaque JSON payloads through to and from :class:`chat.models.Message`
so the Django side stays decoupled from the assistant-ui wire shape.
"""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from .models import Conversation, Message


def _serialize_conversation(conversation: Conversation) -> dict:
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _serialize_message(message: Message) -> dict:
    return {
        "id": message.pk,
        "role": message.role,
        "content": message.content_json,
        "tool_calls": message.tool_calls_json,
        "created_at": message.created_at.isoformat(),
    }


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
        messages = [_serialize_message(m) for m in conversation.messages.all()]
        return JsonResponse(
            {**_serialize_conversation(conversation), "messages": messages}
        )

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
@require_http_methods(["POST"])
def api_conversation_messages(
    request: HttpRequest, conversation_id: int
) -> JsonResponse:
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, user=request.user
    )
    payload = _parse_json(request)
    if payload is None:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    role = payload.get("role")
    if role not in Message.Role.values:
        return JsonResponse({"error": f"invalid role: {role!r}"}, status=400)

    message = Message.objects.create(
        conversation=conversation,
        role=role,
        content_json=payload.get("content", []),
        tool_calls_json=payload.get("tool_calls", []),
    )
    conversation.save(update_fields=["updated_at"])
    return JsonResponse(_serialize_message(message), status=201)


def _parse_json(request: HttpRequest) -> dict | None:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
