from django.contrib import admin
from django_q.tasks import async_task

from .models import Episode


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("url", "title", "language", "status", "created_at")
    list_filter = ("status", "language")
    readonly_fields = (
        "created_at",
        "updated_at",
        "audio_file",
        "error_message",
        "transcript",
        "transcript_json",
        "summary_generated",
        "entities_json",
    )
    actions = ["reprocess"]

    METADATA_FIELDS = (
        "title",
        "description",
        "published_at",
        "image_url",
        "language",
        "audio_url",
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # Creating a new episode — only url is editable
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        elif obj.status == Episode.Status.NEEDS_REVIEW:
            # Needs review — metadata editable, status read-only
            readonly += ["status", "scraped_html"]
        else:
            # All other statuses — everything read-only except url
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        return readonly

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return [(None, {"fields": ("url",)})]
        main_fields = ["url", "status"]
        if obj.status == Episode.Status.FAILED and obj.error_message:
            main_fields.append("error_message")
        fieldsets = [
            (None, {"fields": main_fields}),
            (
                "Metadata",
                {"fields": self.METADATA_FIELDS},
            ),
        ]
        if obj.audio_file:
            fieldsets.append(("Files", {"fields": ("audio_file",)}))
        if obj.transcript:
            fieldsets.append(("Transcript", {"fields": ("transcript",)}))
        if obj.summary_generated:
            fieldsets.append(("Summary", {"fields": ("summary_generated",)}))
        if obj.entities_json:
            fieldsets.append((
                "Entities",
                {
                    "classes": ("collapse",),
                    "fields": ("entities_json",),
                },
            ))
        if obj.transcript_json:
            fieldsets.append((
                "Transcript JSON",
                {
                    "classes": ("collapse",),
                    "fields": ("transcript_json",),
                },
            ))
        fieldsets += [
            (
                "Debug",
                {
                    "classes": ("collapse",),
                    "fields": ("scraped_html",),
                },
            ),
            (
                "Timestamps",
                {
                    "classes": ("collapse",),
                    "fields": ("created_at", "updated_at"),
                },
            ),
        ]
        return fieldsets

    @admin.action(description="Reprocess selected episodes")
    def reprocess(self, request, queryset):
        count = 0
        for episode in queryset:
            episode.status = Episode.Status.SCRAPING
            episode.save(update_fields=["status", "updated_at"])
            async_task("episodes.scraper.scrape_episode", episode.pk)
            count += 1
        self.message_user(request, f"Queued {count} episode(s) for reprocessing.")
