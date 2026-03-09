from django.contrib import admin

from .models import Episode


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("url", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("status", "created_at", "updated_at")
