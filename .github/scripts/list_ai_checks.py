#!/usr/bin/env python3
"""Emit a JSON matrix of `.ai-checks/*.md` rules for GitHub Actions.

Output line format (written to $GITHUB_OUTPUT):

    matrix={"include": [{"name": "<rule>", "path": ".ai-checks/foo.md"}, ...]}

Only rules that **apply** to the current PR's changed file set are included.
Applicability is determined by reading each rule's optional `paths:`
frontmatter (comma-separated `fnmatch` globs) and matching it against
`git diff --name-only $BASE_REF...HEAD`. Rules without `paths:` always
apply (they're semantic and must be evaluated by the model).

Non-applicable rules are **omitted from the matrix entirely**, so they
simply don't appear in the PR Checks tab. We previously tried emitting
them with `applies: false` and gating the job on `if: ${{ matrix.applies }}`
to render gray "skipped" rows, but GitHub Actions evaluates job-level
`if:` *before* expanding `strategy.matrix`, so `matrix.applies` is not
visible at that scope and the workflow fails to expand any jobs at all.

The future-work option for true gray-skipped rows is to publish them via
the GitHub Checks API from the `list` job (tracked as a separate issue).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CHECKS_DIR = Path(".ai-checks")


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Extract a flat key/value mapping from a Markdown file's YAML-ish frontmatter.

    Supported frontmatter syntax (intentionally minimal — this is NOT a YAML parser):

    - Delimited by `---` lines at the top of the file.
    - Each line is a single ``key: value`` pair.
    - Values are returned as raw strings, with surrounding whitespace stripped.
    - Comment lines starting with ``#`` are ignored.

    Explicitly NOT supported:

    - Multi-line YAML lists (e.g. ``paths:\\n  - foo\\n  - bar``) — the value
      ends at the newline, so the key resolves to an empty string and any
      following ``- foo`` lines are dropped.
    - Quoted values — quote characters are preserved literally in the
      returned string (e.g. ``paths: "foo"`` yields ``'"foo"'``, which then
      fails to match anything via :func:`fnmatch`).
    - Block scalars (``|``, ``>``), anchors, references, etc.

    Returns an empty dict if the file has no frontmatter delimiters.
    """
    text = path.read_text()
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not m:
        return {}
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def changed_files(base: str) -> list[str]:
    """Return the list of files changed between ``base`` and ``HEAD``.

    Fails closed: if ``git diff`` errors out (e.g. unknown base ref, shallow
    clone without the base, repo corruption), this exits the process with
    status 1 and a clear message on stderr. Silently returning ``[]`` would
    cause every path-scoped rule to be marked non-applicable and silently
    dropped from the matrix, which is exactly the kind of "no signal"
    failure mode we're trying to avoid.
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        sys.stderr.write(
            f"ERROR: `git diff --name-only {base}...HEAD` failed: {stderr}. "
            "Refusing to silently skip path-scoped rules.\n"
        )
        sys.exit(1)
    return [line for line in out.splitlines() if line.strip()]


def matches_paths(files: list[str], patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(f, p) for f in files for p in patterns)


def applies_for(fm: dict[str, str], files: list[str]) -> bool:
    """Decide whether a rule applies given its frontmatter and the changed files.

    A rule with no ``paths:`` field (or an empty/whitespace-only value)
    always applies — semantic rules must always run.

    A rule with a ``paths:`` field is treated as a comma-separated list of
    :mod:`fnmatch` glob patterns. The rule applies iff at least one changed
    file matches at least one pattern.

    Glob semantics (inherited from :mod:`fnmatch`):

    - ``*`` matches any number of characters, **including** ``/`` — this is
      not shell-segment-aware. ``doc/*.md`` matches ``doc/nested/foo.md``.
    - ``**`` is **not** treated specially; it's just two consecutive ``*``.
      In practice ``foo/**`` happens to match ``foo/bar/baz.py`` because
      ``*`` already crosses ``/``.
    - ``?`` matches exactly one character (also crossing ``/``).
    - Character classes ``[...]`` are supported.

    Syntax constraints (see :func:`parse_frontmatter`):

    - Single line only.
    - Comma-separated.
    - Unquoted — quote characters become part of the pattern and won't match.
    - YAML list form (``- foo``) is not supported.
    """
    raw = fm.get("paths", "").strip()
    if not raw:
        return True
    patterns = [p.strip() for p in raw.split(",") if p.strip()]
    if not patterns:
        return True
    return matches_paths(files, patterns)


def main() -> int:
    if not CHECKS_DIR.is_dir():
        print(f"matrix={json.dumps({'include': []})}")
        return 0

    base = os.environ.get("BASE_REF", "origin/main")
    files = changed_files(base)

    items = []
    for p in sorted(CHECKS_DIR.glob("*.md")):
        fm = parse_frontmatter(p)
        if not applies_for(fm, files):
            continue
        items.append(
            {
                "name": fm.get("name", p.stem),
                "path": str(p),
            }
        )

    print(f"matrix={json.dumps({'include': items})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
