#!/usr/bin/env python3
"""Aggregate per-rule AI Check verdicts into a sticky PR comment body.

Reads all `*.json` files under a directory (each produced by `run_ai_check.py
--output`) and writes:

- A Markdown body to `--body-out` (only meaningful when there is at least
  one FAIL).
- The literal string `true` or `false` to `--has-fail-out`, so the workflow
  can branch on whether to upsert or delete the sticky comment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


VERDICT_ORDER = {"fail": 0, "skip": 1, "pass": 2}


def load_results(results_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in sorted(results_dir.rglob("*.json")):
        try:
            items.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError) as e:
            print(f"warning: skipping {p}: {e}", file=sys.stderr)
    items.sort(key=lambda r: (VERDICT_ORDER.get(r.get("verdict", "pass"), 9), r.get("name", "")))
    return items


def render_body(results: list[dict[str, Any]]) -> str:
    fails = [r for r in results if r.get("verdict") == "fail"]
    passes = [r for r in results if r.get("verdict") == "pass"]
    skips = [r for r in results if r.get("verdict") == "skip"]

    lines: list[str] = []
    lines.append("## AI Checks summary")
    lines.append("")
    lines.append(
        f"❌ **{len(fails)} fail** · ✅ {len(passes)} pass · ⏭️ {len(skips)} skip"
    )
    lines.append("")

    for r in fails:
        lines.append(f"### ❌ {r.get('name', '(unnamed)')}")
        lines.append("")
        desc = (r.get("description") or "").strip()
        if desc:
            lines.append(f"> {desc}")
            lines.append("")
        summary = r.get("summary") or "_No summary._"
        lines.append(f"**{summary}**")
        lines.append("")
        details = (r.get("details") or "").strip()
        if details:
            lines.append("<details><summary>Details</summary>")
            lines.append("")
            lines.append(details)
            lines.append("")
            lines.append("</details>")
            lines.append("")

    if passes or skips:
        if fails:
            lines.append("---")
            lines.append("")
        lines.append(f"### Other checks ({len(passes)} passing · {len(skips)} skipped)")
        lines.append("")
        lines.append("<details><summary>Show details</summary>")
        lines.append("")
        for r in passes:
            lines.append(f"- ✅ **{r.get('name', '(unnamed)')}** — {r.get('summary', '')}")
        for r in skips:
            lines.append(f"- ⏭️ **{r.get('name', '(unnamed)')}** — {r.get('summary', '')}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--body-out", type=Path, required=True)
    ap.add_argument("--has-fail-out", type=Path, required=True)
    args = ap.parse_args()

    results = load_results(args.results_dir)
    has_fail = any(r.get("verdict") == "fail" for r in results)

    args.has_fail_out.write_text("true" if has_fail else "false")

    if has_fail:
        args.body_out.write_text(render_body(results))
    else:
        args.body_out.write_text("")

    print(f"results: {len(results)}, has_fail: {has_fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
