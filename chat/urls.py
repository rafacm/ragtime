from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.chat_page, name="page"),
    path("api/conversations/", views.api_conversations, name="conversations"),
    path(
        "api/conversations/<int:conversation_id>/",
        views.api_conversation_detail,
        name="conversation_detail",
    ),
    path(
        "api/conversations/<int:conversation_id>/history/",
        views.api_conversation_history,
        name="conversation_history",
    ),
    path(
        "api/conversations/<int:conversation_id>/generate-title/",
        views.api_generate_title,
        name="generate_title",
    ),
]
