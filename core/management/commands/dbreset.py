"""Drop and recreate the PostgreSQL database."""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Drop and recreate the PostgreSQL database, run migrations, and seed entity types"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        db_name = db["NAME"]
        db_user = db["USER"]
        db_password = db["PASSWORD"]
        db_host = db["HOST"]
        db_port = db["PORT"]

        if not options["yes"]:
            confirm = input(
                f"This will DROP the database '{db_name}' and all its data. "
                f"Are you sure? [y/N]: "
            )
            if confirm.strip().lower() not in ("y", "yes"):
                self.stdout.write("Cancelled.")
                return

        self.stdout.write(f"Dropping database '{db_name}'...")

        import psycopg
        from psycopg import sql

        # Connect to the maintenance database to drop/create
        with psycopg.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            dbname="postgres",
            autocommit=True,
        ) as conn:
            # Terminate existing connections
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(db_name), sql.Identifier(db_user)
                )
            )

        self.stdout.write(self.style.SUCCESS(f"Database '{db_name}' recreated."))

        self.stdout.write("Running migrations...")
        call_command("migrate", verbosity=0)
        self.stdout.write(self.style.SUCCESS("Migrations applied."))

        self.stdout.write("Seeding entity types...")
        call_command("load_entity_types", verbosity=0)
        self.stdout.write(self.style.SUCCESS("Entity types loaded."))

        self.stdout.write(
            "\nDone. Run 'uv run python manage.py createsuperuser' to create an admin account."
        )
