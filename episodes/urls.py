from django.urls import path

from . import views

app_name = "episodes"

urlpatterns = [
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
