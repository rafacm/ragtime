from django.conf import settings
from django.db import models


class Conversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or f"Conversation {self.pk}"


class Message(models.Model):
    """A single turn in an assistant-ui thread.

    We store the full assistant-ui ``ThreadMessage`` verbatim in
    ``payload_json`` rather than splitting out role/content/tool_calls,
    so the repository round-trips cleanly through the history adapter.
    ``external_id`` and ``parent_external_id`` carry assistant-ui's own
    identifiers, which must survive the round trip so the message tree
    reconstructs correctly.
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    external_id = models.CharField(max_length=64)
    parent_external_id = models.CharField(max_length=64, blank=True, default="")
    payload_json = models.JSONField()
    run_config_json = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "external_id"],
                name="unique_message_external_id_per_conversation",
            ),
        ]

    def __str__(self) -> str:
        return f"Message {self.external_id} in conversation {self.conversation_id}"
