#!/usr/bin/env python3
"""Emit a JSON matrix of `.ai-checks/*.md` rules for GitHub Actions.

Output line format (written to $GITHUB_OUTPUT):

    matrix={"include": [{"name": "<rule>", "path": ".ai-checks/foo.md", "applies": true}, ...]}

`applies` is determined by reading each rule's optional `paths:` frontmatter
(comma-separated `fnmatch` globs) and matching it against `git diff
--name-only $BASE_REF...HEAD`. Rules without `paths:` always have
`applies: true` (they're semantic and must be evaluated by the model).

The workflow then gates each matrix shard on `if: ${{ matrix.applies }}` so
non-applicable rules render as gray "skipped" jobs in the PR Checks tab
rather than green "pass" — preserving the signal that the rule was scoped
out, not silently waved through.
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
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return []
    return [line for line in out.splitlines() if line.strip()]


def matches_paths(files: list[str], patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(f, p) for f in files for p in patterns)


def applies_for(fm: dict[str, str], files: list[str]) -> bool:
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
        items.append(
            {
                "name": fm.get("name", p.stem),
                "path": str(p),
                "applies": applies_for(fm, files),
            }
        )

    print(f"matrix={json.dumps({'include': items})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
