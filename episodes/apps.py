from django.apps import AppConfig


class EpisodesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'episodes'

    def ready(self):
        # Import signals module to register custom signal definitions.
        # step_completed and step_failed are still emitted by processing.py
        # for audit logging (PipelineEvent records). Recovery is now handled
        # by the LangGraph recovery node — no default handler is connected
        # here. External code can still connect to these signals for custom
        # listeners (e.g., notifications).
        import episodes.signals  # noqa: F401

        from .telemetry import setup as setup_telemetry

        setup_telemetry()
