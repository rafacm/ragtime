"""Views for the episodes app."""

import logging

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse

from .wikidata import get_entity, search_entities

logger = logging.getLogger(__name__)


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
