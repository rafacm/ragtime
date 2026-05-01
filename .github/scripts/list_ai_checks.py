#!/usr/bin/env python3
"""Emit a JSON matrix of `.ai-checks/*.md` rules for GitHub Actions.

Output line format (written to $GITHUB_OUTPUT):

    matrix={"include": [{"name": "<rule name>", "path": ".ai-checks/foo.md"}, ...]}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CHECKS_DIR = Path(".ai-checks")


def parse_name(path: Path) -> str:
    text = path.read_text()
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not m:
        return path.stem
    for line in m.group(1).splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return path.stem


def main() -> int:
    if not CHECKS_DIR.is_dir():
        print(f"matrix={json.dumps({'include': []})}")
        return 0
    items = [
        {"name": parse_name(p), "path": str(p)}
        for p in sorted(CHECKS_DIR.glob("*.md"))
    ]
    print(f"matrix={json.dumps({'include': items})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
