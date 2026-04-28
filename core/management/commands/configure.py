"""Interactive guided setup for RAGtime environment variables."""

from django.conf import settings
from django.core.management.base import BaseCommand

from ._configure_helpers import (
    SYSTEMS,
    mask_secret,
    prompt_value,
    read_env,
    write_env,
)


class Command(BaseCommand):
    help = "Interactive guided setup for RAGtime environment variables"

    def add_arguments(self, parser):
        parser.add_argument(
            "--show",
            action="store_true",
            help="Show current configuration and exit",
        )

    def handle(self, *args, **options):
        env_path = settings.BASE_DIR / ".env"
        existing, lines = read_env(env_path)

        if options["show"]:
            self._show_config(existing)
            return

        try:
            new_values = self._run_wizard(existing)
        except KeyboardInterrupt:
            self.stdout.write("\nConfiguration cancelled. No changes written.")
            return

        merged = {**existing, **new_values}
        write_env(env_path, merged, lines)
        self.stdout.write(
            self.style.SUCCESS(f"\nConfiguration written to {env_path}")
        )

        self._warn_if_embedding_model_changed(existing, new_values)

    def _warn_if_embedding_model_changed(self, existing, new_values):
        """Warn when the embedding model is changed.

        Different embedding models produce vectors of different dimensions;
        a Qdrant collection created for the old model cannot store vectors
        from the new one. The user needs to drop and recreate the
        collection before re-ingesting.
        """
        old_model = existing.get("RAGTIME_EMBEDDING_MODEL", "")
        new_model = new_values.get("RAGTIME_EMBEDDING_MODEL", "")
        if old_model and new_model and old_model != new_model:
            self.stdout.write(
                self.style.WARNING(
                    f"\n\u26a0  RAGTIME_EMBEDDING_MODEL changed "
                    f"({old_model!r} -> {new_model!r}).\n"
                    f"   Embedding models typically produce vectors with "
                    f"different dimensions, so any existing Qdrant "
                    f"collection\n"
                    f"   was created with the old model's dim and will "
                    f"reject new upserts until recreated. To recreate:\n"
                    f"     uv run python manage.py dbreset\n"
                    f"   or drop only the collection "
                    f"(RAGTIME_QDRANT_COLLECTION, default 'ragtime_chunks') "
                    f"via the Qdrant API."
                )
            )

    def _show_config(self, existing):
        """Print current RAGTIME_* configuration with masked secrets."""
        self.stdout.write("\nRAGtime Configuration")
        self.stdout.write("=" * 21)

        # Build a set of secret keys for masking
        secret_keys = set()
        for system in SYSTEMS:
            for subsystem in system["subsystems"]:
                for suffix, _, is_secret in subsystem["fields"]:
                    if is_secret:
                        secret_keys.add(f"{subsystem['prefix']}_{suffix}")

        has_values = False
        for key, value in sorted(existing.items()):
            if not key.startswith("RAGTIME_"):
                continue
            has_values = True
            display = mask_secret(value) if key in secret_keys else value
            self.stdout.write(f"  {key}={display}")

        if not has_values:
            self.stdout.write("  No RAGTIME_* variables configured.")

        self.stdout.write("")

    def _run_wizard(self, existing):
        """Run the interactive configuration wizard."""
        self.stdout.write("\nRAGtime Configuration")
        self.stdout.write("=" * 21)
        self.stdout.write("Current values shown in [brackets]. Press Enter to keep.\n")

        new_values = {}
        shared_api_key = None

        for system in SYSTEMS:
            self.stdout.write(
                f"--- {system['name']} ({system['description']}) ---"
            )

            if system["shareable"] and len(system["subsystems"]) > 1:
                shared_api_key = self._prompt_shared_system(
                    system, existing, new_values
                )
            else:
                self._prompt_system(
                    system, existing, new_values, shared_api_key
                )

            self.stdout.write("")

        return new_values

    def _prompt_shared_system(self, system, existing, new_values):
        """Prompt for a shareable system (LLM) with optional shared credentials."""
        # Ask if user wants to share provider/key across subsystems
        share_default = "Y"
        share = input(
            f"  Use a single provider and API key for all {system['name']}"
            f" systems? [{share_default}/n]: "
        )
        use_shared = share.strip().lower() not in ("n", "no")

        if use_shared:
            # Prompt for shared provider and API key once
            first_sub = system["subsystems"][0]
            provider_key = f"{first_sub['prefix']}_PROVIDER"
            api_key_key = f"{first_sub['prefix']}_API_KEY"

            # Find defaults from existing or field defaults
            provider_default = existing.get(provider_key, "openai")
            api_key_default = existing.get(api_key_key, "")

            shared_provider = prompt_value("Provider", provider_default, False)
            shared_api_key = prompt_value("API key", api_key_default, True)

            # Apply shared provider/key to all subsystems, prompt per-model
            for subsystem in system["subsystems"]:
                field_suffixes = {f[0] for f in subsystem["fields"]}
                # Convention B subsystems (e.g. RAGTIME_FETCH_DETAILS) encode
                # the provider in the model string and don't define a PROVIDER
                # field — skip writing one for them.
                conventionB = "PROVIDER" not in field_suffixes
                if not conventionB:
                    new_values[f"{subsystem['prefix']}_PROVIDER"] = shared_provider
                new_values[f"{subsystem['prefix']}_API_KEY"] = shared_api_key

                # Prompt for model
                for suffix, default, is_secret in subsystem["fields"]:
                    if suffix == "MODEL":
                        env_key = f"{subsystem['prefix']}_{suffix}"
                        current = existing.get(env_key, default)
                        # For Convention B subsystems, sync the model prefix
                        # to the shared provider so picking ``anthropic`` here
                        # doesn't leave a stale ``openai:`` prefix on the
                        # model default. Idempotent across re-runs.
                        if conventionB:
                            if ":" in current:
                                _, _, model_part = current.partition(":")
                            else:
                                model_part = current
                            current = f"{shared_provider}:{model_part}"
                        new_values[env_key] = prompt_value(
                            f"{subsystem['label']} model", current, False
                        )

            return shared_api_key
        else:
            # Prompt each subsystem independently
            shared_api_key = None
            for subsystem in system["subsystems"]:
                self.stdout.write(f"  [{subsystem['label']}]")
                for suffix, default, is_secret in subsystem["fields"]:
                    env_key = f"{subsystem['prefix']}_{suffix}"
                    current = existing.get(env_key, default)
                    label = suffix.replace("_", " ").title()
                    new_values[env_key] = prompt_value(label, current, is_secret)
                    if suffix == "API_KEY" and shared_api_key is None:
                        shared_api_key = new_values[env_key]
            return shared_api_key

    def _prompt_system(self, system, existing, new_values, shared_api_key):
        """Prompt for a non-shareable system (e.g. transcription)."""
        for subsystem in system["subsystems"]:
            for suffix, default, is_secret in subsystem["fields"]:
                env_key = f"{subsystem['prefix']}_{suffix}"
                current = existing.get(env_key, default)

                label = suffix.replace("_", " ").title()

                # Offer to reuse the shared LLM API key
                if suffix.endswith("API_KEY") and shared_api_key:
                    reuse_display = mask_secret(shared_api_key)
                    if current == shared_api_key or not current:
                        label = f"API key (Enter to reuse LLM key)"
                        current = shared_api_key
                    else:
                        label = f"API key (Enter to keep, or type new)"

                new_values[env_key] = prompt_value(label, current, is_secret)
