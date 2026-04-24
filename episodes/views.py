"""Views for the episodes app."""

import logging

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from .models import Episode
from .wikidata import get_entity, search_entities

logger = logging.getLogger(__name__)

EPISODE_DESCRIPTION_PREVIEW_CHARS = 280
EPISODE_LIMIT_MAX = 500


def _episode_audio_url(episode: Episode) -> str:
    if episode.audio_url:
        return episode.audio_url
    if episode.audio_file:
        return episode.audio_file.url
    return ""


def _serialize_episode(episode: Episode) -> dict:
    description = episode.description or ""
    if len(description) > EPISODE_DESCRIPTION_PREVIEW_CHARS:
        description = description[:EPISODE_DESCRIPTION_PREVIEW_CHARS].rstrip() + "…"
    return {
        "id": episode.pk,
        "title": episode.title,
        "duration": episode.duration,
        "published_at": (
            episode.published_at.isoformat() if episode.published_at else None
        ),
        "audio_url": _episode_audio_url(episode),
        "image_url": episode.image_url,
        "description": description,
    }


@login_required
@require_GET
def api_episode_list(request: HttpRequest) -> JsonResponse:
    """Return all READY episodes for the browsable right-rail in the chat UI."""
    qs = Episode.objects.filter(status=Episode.Status.READY).order_by(
        F("published_at").desc(nulls_last=True), "-id"
    )

    raw_limit = request.GET.get("limit")
    if raw_limit:
        try:
            limit = int(raw_limit)
        except ValueError:
            return JsonResponse({"error": "invalid limit"}, status=400)
        limit = max(1, min(limit, EPISODE_LIMIT_MAX))
        qs = qs[:limit]

    return JsonResponse({"episodes": [_serialize_episode(e) for e in qs]})


@staff_member_required
def wikidata_search(request):
    """AJAX endpoint for searching Wikidata entities from the admin UI."""
    query = request.GET.get("q", "").strip()
    min_chars = getattr(settings, "RAGTIME_WIKIDATA_MIN_CHARS", 3)

    if len(query) < min_chars:
        return JsonResponse({"results": []})

    try:
        results = search_entities(query, limit=10)
        return JsonResponse({"results": results})
    except Exception:
        logger.exception("Wikidata search failed for query '%s'", query)
        return JsonResponse({"results": [], "error": "Wikidata search failed"}, status=502)


@staff_member_required
def wikidata_entity_detail(request, qid):
    """AJAX endpoint for fetching Wikidata entity details."""
    try:
        entity = get_entity(qid)
        aliases = entity.get("aliases", [])

        return JsonResponse({
            "qid": entity["qid"],
            "label": entity["label"],
            "description": entity["description"],
            "aliases": aliases,
        })
    except Exception:
        logger.exception("Wikidata entity fetch failed for %s", qid)
        return JsonResponse({"error": "Failed to fetch entity"}, status=502)
