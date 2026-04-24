from django.urls import path

from . import views

app_name = "episodes"

urlpatterns = [
    path(
        "api/episodes/",
        views.api_episode_list,
        name="api-episode-list",
    ),
    path(
        "wikidata/search/",
        views.wikidata_search,
        name="wikidata-search",
    ),
    path(
        "wikidata/entity/<str:qid>/",
        views.wikidata_entity_detail,
        name="wikidata-entity-detail",
    ),
]
