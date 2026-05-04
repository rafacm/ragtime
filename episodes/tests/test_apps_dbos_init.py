"""Role detection in ``EpisodesConfig._init_dbos``.

Verifies that DBOS launches in worker mode for ``runserver`` / ``uvicorn``,
in enqueue-only mode (``listen_queues([])``) for client commands, and
not at all for bootstrap / unrelated commands.
"""

from unittest import TestCase
from unittest.mock import patch

from django.apps import apps


class InitDbosRoleTests(TestCase):
    def setUp(self):
        self.config = apps.get_app_config("episodes")

    def _run(self, argv):
        with patch("sys.argv", argv), \
             patch("dbos.DBOS") as MockDBOS:
            self.config._init_dbos()
            return MockDBOS

    def test_uvicorn_launches_full_worker(self):
        MockDBOS = self._run(["uvicorn", "ragtime.asgi:application"])
        MockDBOS.listen_queues.assert_not_called()
        MockDBOS.launch.assert_called_once()

    def test_runserver_launches_full_worker(self):
        MockDBOS = self._run(["manage.py", "runserver"])
        MockDBOS.listen_queues.assert_not_called()
        MockDBOS.launch.assert_called_once()

    def test_submit_episode_launches_enqueue_only(self):
        MockDBOS = self._run(["manage.py", "submit_episode", "https://x/ep/1"])
        MockDBOS.listen_queues.assert_called_once_with([])
        MockDBOS.launch.assert_called_once()

    def test_enrich_entities_launches_enqueue_only(self):
        MockDBOS = self._run(["manage.py", "enrich_entities"])
        MockDBOS.listen_queues.assert_called_once_with([])
        MockDBOS.launch.assert_called_once()

    def test_migrate_skips_dbos_entirely(self):
        MockDBOS = self._run(["manage.py", "migrate"])
        MockDBOS.listen_queues.assert_not_called()
        MockDBOS.launch.assert_not_called()

    def test_test_command_skips_dbos_entirely(self):
        MockDBOS = self._run(["manage.py", "test"])
        MockDBOS.listen_queues.assert_not_called()
        MockDBOS.launch.assert_not_called()

    def test_shell_skips_dbos_entirely(self):
        MockDBOS = self._run(["manage.py", "shell"])
        MockDBOS.listen_queues.assert_not_called()
        MockDBOS.launch.assert_not_called()
