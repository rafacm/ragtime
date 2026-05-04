"""Unit tests for ``.github/scripts/list_ai_checks.py``.

Run with::

    python -m unittest discover .github/scripts/tests -v

These tests use only the standard library — they're meant to run in a
plain Python runner (no project Django dep), the same way the workflow
does.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

# Make the parent `.github/scripts` directory importable.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import list_ai_checks  # noqa: E402  (import after sys.path tweak)


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


class ParseFrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_well_formed_frontmatter(self):
        p = _write(
            self.dir / "rule.md",
            "---\nname: foo\npaths: episodes/**\n---\nbody\n",
        )
        fm = list_ai_checks.parse_frontmatter(p)
        self.assertEqual(fm, {"name": "foo", "paths": "episodes/**"})

    def test_missing_frontmatter_delimiters(self):
        p = _write(self.dir / "rule.md", "no frontmatter here\n")
        self.assertEqual(list_ai_checks.parse_frontmatter(p), {})

    def test_missing_fields(self):
        p = _write(self.dir / "rule.md", "---\nname: foo\n---\n")
        fm = list_ai_checks.parse_frontmatter(p)
        self.assertEqual(fm, {"name": "foo"})
        self.assertNotIn("paths", fm)

    def test_multi_line_value_only_keeps_first_line(self):
        # Multi-line YAML list form is NOT supported. The `paths:` value
        # is empty (everything after the colon on that line) and the
        # following `- ...` lines have no colon so they're dropped.
        p = _write(
            self.dir / "rule.md",
            "---\nname: foo\npaths:\n  - episodes/**\n  - chat/**\n---\n",
        )
        fm = list_ai_checks.parse_frontmatter(p)
        self.assertEqual(fm.get("paths", ""), "")

    def test_quoted_values_are_not_unquoted(self):
        # Quoted globs are NOT supported — the quote characters become
        # part of the pattern.
        p = _write(
            self.dir / "rule.md",
            '---\nname: foo\npaths: "episodes/**", "README.md"\n---\n',
        )
        fm = list_ai_checks.parse_frontmatter(p)
        self.assertIn('"', fm["paths"])

    def test_comment_lines_ignored(self):
        p = _write(
            self.dir / "rule.md",
            "---\n# this is a comment\nname: foo\n---\n",
        )
        self.assertEqual(list_ai_checks.parse_frontmatter(p), {"name": "foo"})


class AppliesForTests(unittest.TestCase):
    def test_empty_paths_always_applies(self):
        self.assertTrue(list_ai_checks.applies_for({}, []))
        self.assertTrue(list_ai_checks.applies_for({"paths": ""}, ["x.py"]))
        self.assertTrue(list_ai_checks.applies_for({"paths": "   "}, ["x.py"]))

    def test_comma_separated_globs(self):
        fm = {"paths": "episodes/**, chat/**, README.md"}
        self.assertTrue(list_ai_checks.applies_for(fm, ["chat/views.py"]))
        self.assertTrue(list_ai_checks.applies_for(fm, ["README.md"]))
        self.assertTrue(list_ai_checks.applies_for(fm, ["episodes/models.py"]))
        self.assertFalse(list_ai_checks.applies_for(fm, ["frontend/src/x.tsx"]))

    def test_single_glob(self):
        fm = {"paths": "episodes/vector_store.py"}
        self.assertTrue(list_ai_checks.applies_for(fm, ["episodes/vector_store.py"]))
        self.assertFalse(list_ai_checks.applies_for(fm, ["episodes/models.py"]))

    def test_no_matching_files(self):
        fm = {"paths": "frontend/**"}
        self.assertFalse(list_ai_checks.applies_for(fm, ["episodes/x.py", "doc/y.md"]))

    def test_multiple_matching_files(self):
        fm = {"paths": "episodes/**"}
        self.assertTrue(
            list_ai_checks.applies_for(
                fm, ["episodes/a.py", "episodes/b.py", "doc/z.md"]
            )
        )

    def test_empty_changed_files_path_scoped_rule_does_not_apply(self):
        fm = {"paths": "episodes/**"}
        self.assertFalse(list_ai_checks.applies_for(fm, []))

    def test_empty_changed_files_semantic_rule_still_applies(self):
        # No `paths:` -> always applies, even on an empty diff.
        self.assertTrue(list_ai_checks.applies_for({}, []))

    def test_quoted_paths_lock_in_unsupported_behavior(self):
        # Quoted globs do not match anything (the pattern still contains
        # literal quote characters). This locks in the codex-flagged
        # behavior so a future "fix" doesn't silently change it.
        fm = {"paths": '"episodes/**"'}
        self.assertFalse(list_ai_checks.applies_for(fm, ["episodes/models.py"]))

    def test_yaml_list_paths_lock_in_unsupported_behavior(self):
        # When the value comes from a multi-line YAML list, parse_frontmatter
        # leaves `paths` empty, so the rule incorrectly applies to every
        # diff. Lock that in via the parsed value being "".
        self.assertTrue(list_ai_checks.applies_for({"paths": ""}, ["any.py"]))


class MatchesPathsTests(unittest.TestCase):
    def test_nested_path_matching(self):
        self.assertTrue(
            list_ai_checks.matches_paths(["chat/views/foo.py"], ["chat/**"])
        )

    def test_double_star_is_not_segment_aware(self):
        # fnmatch treats ** as just two consecutive *, which already
        # crosses /. So `foo/**` matches `foo/bar/baz`.
        self.assertTrue(list_ai_checks.matches_paths(["foo/bar/baz"], ["foo/**"]))

    def test_star_crosses_slash(self):
        # Document the codex-flagged surprising behavior: `*` crosses `/`.
        self.assertTrue(
            list_ai_checks.matches_paths(
                ["doc/nested/foo.excalidraw"], ["doc/*.excalidraw"]
            )
        )

    def test_no_match(self):
        self.assertFalse(
            list_ai_checks.matches_paths(["episodes/x.py"], ["frontend/**"])
        )


class ChangedFilesTests(unittest.TestCase):
    def test_failure_exits_one(self):
        # Replace subprocess.run with one that always raises CalledProcessError.
        err = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "diff"],
            output="",
            stderr="fatal: bad revision",
        )
        with mock.patch.object(list_ai_checks.subprocess, "run", side_effect=err):
            stderr_buf = io.StringIO()
            with redirect_stderr(stderr_buf):
                with self.assertRaises(SystemExit) as cm:
                    list_ai_checks.changed_files("origin/does-not-exist")
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("Refusing to silently skip", stderr_buf.getvalue())

    def test_success_returns_filtered_lines(self):
        completed = mock.Mock()
        completed.stdout = "a.py\n\nb.py\n"
        with mock.patch.object(list_ai_checks.subprocess, "run", return_value=completed):
            result = list_ai_checks.changed_files("origin/main")
        self.assertEqual(result, ["a.py", "b.py"])


class MainEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.checks_dir = self.root / ".ai-checks"
        self.checks_dir.mkdir()

        # Three rules: two path-scoped, one semantic.
        _write(
            self.checks_dir / "episodes-rule.md",
            "---\nname: episodes-rule\npaths: episodes/**\n---\nbody\n",
        )
        _write(
            self.checks_dir / "frontend-rule.md",
            "---\nname: frontend-rule\npaths: frontend/**\n---\nbody\n",
        )
        _write(
            self.checks_dir / "semantic-rule.md",
            "---\nname: semantic-rule\n---\nbody\n",
        )

    def _run_main(self, changed):
        # Patch CHECKS_DIR to point at our tempdir, and patch changed_files.
        with mock.patch.object(list_ai_checks, "CHECKS_DIR", self.checks_dir):
            with mock.patch.object(
                list_ai_checks, "changed_files", return_value=changed
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = list_ai_checks.main()
        self.assertEqual(rc, 0)
        out = buf.getvalue().strip()
        self.assertTrue(out.startswith("matrix="))
        return json.loads(out[len("matrix=") :])

    def test_only_applicable_rules_appear(self):
        matrix = self._run_main(["episodes/models.py"])
        names = [item["name"] for item in matrix["include"]]
        self.assertIn("episodes-rule", names)
        self.assertIn("semantic-rule", names)
        self.assertNotIn("frontend-rule", names)
        # `applies` field must NOT be emitted.
        for item in matrix["include"]:
            self.assertNotIn("applies", item)

    def test_empty_diff_keeps_only_semantic_rules(self):
        matrix = self._run_main([])
        names = [item["name"] for item in matrix["include"]]
        self.assertEqual(names, ["semantic-rule"])

    def test_no_applicable_rules_emits_empty_matrix(self):
        # Patch out the semantic rule so all remaining rules are
        # path-scoped and won't match.
        (self.checks_dir / "semantic-rule.md").unlink()
        matrix = self._run_main(["doc/anything.md"])
        self.assertEqual(matrix, {"include": []})


if __name__ == "__main__":
    unittest.main()
