from django.apps import AppConfig


class EpisodesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'episodes'

    def ready(self):
        import episodes.signals  # noqa: F401

        from .observability import setup as setup_observability
        from .recovery import handle_step_failure
        from .signals import step_failed

        step_failed.connect(handle_step_failure)
        setup_observability()
