"""Cross-process pickle-portability test for ``StepFailed``.

The in-process round-trip in ``test_admin.py`` only checks that
``type(rehydrated) is RuntimeError`` inside the same Python process
that defined ``StepFailed``. That isn't quite the property we care
about — DBOS's ``dbos workflow steps`` CLI runs *outside* Django and
can't import ``episodes.workflows``. This test exercises that
genuinely-cross-process property: it spawns a fresh Python
interpreter in a working directory that does not contain the
project, with an empty ``PYTHONPATH``, and asserts the pickled
``StepFailed`` deserializes to a plain ``RuntimeError`` carrying the
original message.

The test relies on the fact that this project is *not* installed as
an editable wheel into the venv — ``episodes`` is only importable
when ``cwd`` is the project root. A sanity-check subprocess at the
end confirms this by trying ``import episodes.workflows`` in the
same isolated environment and asserting it fails with
``ModuleNotFoundError``. If that sanity check passes, the
cross-process property above is genuinely tested rather than
accidentally satisfied by ``episodes`` being on ``sys.path``.
"""

from __future__ import annotations

import base64
import pickle
import subprocess
import sys

from django.test import TestCase

from episodes.workflows import DownloadStepFailed, StepFailed


class StepFailedSubprocessPickleTests(TestCase):
    """Verify ``StepFailed`` pickles round-trip across process boundaries."""

    EPISODE_ID = 11
    ERROR_MESSAGE = "subprocess-portability check"

    def _isolated_subprocess(self, script: str) -> subprocess.CompletedProcess:
        """Run *script* in a fresh interpreter without project access.

        ``cwd="/tmp"`` ensures a relative ``import episodes`` cannot
        find the project package. ``PYTHONPATH=""`` and
        ``PYTHONNOUSERSITE=1`` shut the user-site escape hatch.
        ``sys.executable`` from the test process is reused so we keep
        the same Python version, but since the project isn't
        installed into the venv as a wheel, ``episodes`` is not on
        the resulting ``sys.path``.
        """
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd="/tmp",
            env={"PYTHONPATH": "", "PYTHONNOUSERSITE": "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_pickled_step_failed_deserializes_to_runtime_error_in_subprocess(self):
        """Pickle bytes rehydrate to ``RuntimeError`` in a project-less interpreter.

        This is the property the DBOS CLI / Conductor relies on to
        render step errors as readable text without importing
        ``episodes.workflows``.
        """
        err = DownloadStepFailed(
            episode_id=self.EPISODE_ID, error_message=self.ERROR_MESSAGE
        )
        # Pre-pickle assertion: in-process raise still matches the
        # typed hierarchy.
        self.assertIsInstance(err, StepFailed)

        pickle_bytes = pickle.dumps(err)
        encoded = base64.b64encode(pickle_bytes).decode("ascii")

        script = (
            "import base64, pickle, sys\n"
            f"data = base64.b64decode({encoded!r})\n"
            "obj = pickle.loads(data)\n"
            "assert type(obj).__name__ == 'RuntimeError', type(obj)\n"
            "assert type(obj).__module__ == 'builtins', type(obj).__module__\n"
            "sys.stdout.write(type(obj).__name__ + '\\n')\n"
            "sys.stdout.write(str(obj) + '\\n')\n"
        )
        result = self._isolated_subprocess(script)

        self.assertEqual(
            result.returncode,
            0,
            msg=f"subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertIn("RuntimeError", result.stdout)
        # Original message survives the round trip.
        self.assertIn(f"downloading failed for episode {self.EPISODE_ID}", result.stdout)
        self.assertIn(self.ERROR_MESSAGE, result.stdout)

    def test_subprocess_environment_really_isolates_episodes_module(self):
        """Sanity check: the test environment really has no ``episodes`` package.

        If this passes, the cross-process property tested above is
        genuinely exercised — the subprocess deserializing the
        pickle truly cannot reach into ``episodes.workflows`` to
        rehydrate a typed subclass.
        """
        script = (
            "try:\n"
            "    import episodes.workflows\n"
            "except ModuleNotFoundError as exc:\n"
            "    import sys\n"
            "    sys.stdout.write('isolated:' + exc.name + '\\n')\n"
            "    sys.exit(0)\n"
            "import sys\n"
            "sys.stdout.write('LEAKED\\n')\n"
            "sys.exit(1)\n"
        )
        result = self._isolated_subprocess(script)

        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "subprocess could import episodes.workflows — environment is "
                f"not isolated. stdout={result.stdout!r} stderr={result.stderr!r}"
            ),
        )
        self.assertIn("isolated:episodes", result.stdout)
