#!/usr/bin/env python3
"""Run a single AI review check against a PR diff.

Reads a markdown rule file with YAML-ish frontmatter, fetches the PR diff,
asks an LLM to evaluate the diff against the rule, and prints a verdict.

Provider routing is handled by LiteLLM. The model string carries the
provider as a prefix, e.g. `openai/gpt-4o-mini`, `anthropic/claude-sonnet-4-6`,
`gemini/gemini-2.0-flash`. LiteLLM auto-reads each provider's canonical env
var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...).

Exits 1 on `fail`, 0 on `pass`. Each invocation is a single GH Actions
matrix job, so the job's pass/fail status becomes the PR check.

Path-scoped non-applicability is now handled at the workflow level: the
`list` job evaluates each rule's `paths:` frontmatter against the PR's
changed files and emits `applies: bool` per matrix include. Shards with
`applies: false` are skipped at the GHA level (gray icon, no runner). The
driver itself only ever returns `pass` or `fail`.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import litellm

DEFAULT_MODEL = "openai/gpt-4o-mini"
MAX_DIFF_CHARS = 200_000

PROVIDER_TO_ENV_VAR: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
}


def required_env_var(model: str) -> str | None:
    """Return the canonical env var name LiteLLM expects for `model`, or None."""
    if "/" not in model:
        return None
    return PROVIDER_TO_ENV_VAR.get(model.split("/", 1)[0].lower())


class ConfigError(RuntimeError):
    """Raised for setup problems (missing/invalid API key) — distinguished from
    rule-evaluation failures so the runner can print a clear setup hint instead
    of a fake `fail` verdict."""


SYSTEM_PROMPT = """You are reviewing a pull request diff against a single review rule.

The rule defines what to check. After reading the diff, report exactly one verdict via the `report_verdict` function:

- pass: the diff complies with the rule, OR the rule does not apply to this diff in any meaningful way. When the rule does not apply, set `summary` to "Rule does not apply." and put a one-line "rule does not apply because …" in `details`.
- fail: the diff clearly violates the rule, with concrete evidence visible in the diff.

Path-scoped non-applicability is handled before you are invoked — if you are evaluating this diff at all, the workflow has decided the rule is in scope. Your job is to check compliance, not to second-guess scope.

Be conservative. Return `fail` only when you can point at specific lines in the diff that violate the rule. Vague concerns, style nitpicks, or "could be improved" remarks are not failures — return `pass` and put your notes in the `details` field."""

USER_TEMPLATE = """# Review rule: {name}

{body}

---

# Pull request diff

```diff
{diff}
```

Evaluate the diff against the rule above and call the `report_verdict` function exactly once."""

REPORT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "report_verdict",
        "description": "Report the verdict for this rule against the PR diff.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["pass", "fail"],
                    "description": "Overall verdict for this rule against the diff.",
                },
                "summary": {
                    "type": "string",
                    "description": "One-sentence summary of the verdict.",
                },
                "details": {
                    "type": "string",
                    "description": "Markdown details: violations with file:line references, or 'No issues.' if pass.",
                },
            },
            "required": ["verdict", "summary", "details"],
        },
    },
}


def parse_check(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text()
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"Missing YAML frontmatter in {path}")
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, m.group(2)


def get_diff(base: str) -> tuple[str, list[str]]:
    diff = subprocess.run(
        ["git", "diff", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    return diff, files


def matches_paths(changed: list[str], patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(f, p) for f in changed for p in patterns)


def evaluate(check_path: Path, base: str, model: str) -> dict[str, str]:
    fm, body = parse_check(check_path)
    diff, files = get_diff(base)

    if not diff.strip():
        return {
            "verdict": "pass",
            "summary": "Rule does not apply.",
            "details": "Rule does not apply because the diff is empty.",
        }

    # Workflow normally gates path-scoped rules at the matrix level via
    # `matrix.applies`, so this branch is mostly a safety net for direct
    # CLI invocation. Returns `pass` with an explanatory note rather than
    # `skip` (which is no longer in the verdict enum — semantic
    # non-applicability is now `pass`, path non-applicability is gray-skipped
    # at the GHA job level).
    if "paths" in fm:
        patterns = [p.strip() for p in fm["paths"].split(",") if p.strip()]
        if patterns and not matches_paths(files, patterns):
            return {
                "verdict": "pass",
                "summary": "Rule does not apply.",
                "details": (
                    f"Rule does not apply because no changed files match its "
                    f"path scope: `{fm['paths']}`."
                ),
            }

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[...diff truncated...]"

    chosen_model = fm.get("model", model)
    key_name = required_env_var(chosen_model)
    if key_name and not os.environ.get(key_name):
        raise ConfigError(
            f"Missing `{key_name}`. AI_CHECK_MODEL is `{chosen_model}`, which routes "
            f"to the {chosen_model.split('/', 1)[0]} provider via LiteLLM. Set "
            f"`{key_name}` (in CI: Settings → Secrets and variables → Actions → "
            f"New *repository* secret, not an environment secret; locally: "
            f"`export {key_name}=...`), or change AI_CHECK_MODEL to a provider "
            f"whose key is set."
        )

    try:
        resp = litellm.completion(
            model=chosen_model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": USER_TEMPLATE.format(
                        name=fm.get("name", check_path.stem),
                        body=body.strip(),
                        diff=diff,
                    ),
                },
            ],
            tools=[REPORT_TOOL],
            tool_choice={"type": "function", "function": {"name": "report_verdict"}},
        )
    except litellm.AuthenticationError as e:
        raise ConfigError(
            f"Provider rejected the request as unauthenticated for model `{chosen_model}`. "
            f"The `{key_name}` secret is likely invalid, expired, or revoked. "
            f"Underlying error: {e}"
        ) from e

    msg = resp.choices[0].message
    if not getattr(msg, "tool_calls", None):
        raise RuntimeError("Model did not invoke report_verdict function")
    args = msg.tool_calls[0].function.arguments
    return json.loads(args) if isinstance(args, str) else dict(args)


def write_step_summary(check_name: str, result: dict[str, str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    marker = {"pass": "PASS", "fail": "FAIL"}[result["verdict"]]
    md = (
        f"# [{marker}] {check_name}\n\n"
        f"**Verdict:** `{result['verdict']}`\n\n"
        f"**Summary:** {result['summary']}\n\n"
        f"{result.get('details') or '_No details._'}\n"
    )
    Path(summary_path).write_text(md)


def write_output_json(path: Path, name: str, description: str, result: dict[str, str]) -> None:
    payload = {
        "name": name,
        "description": description,
        "verdict": result["verdict"],
        "summary": result.get("summary", ""),
        "details": result.get("details", ""),
    }
    path.write_text(json.dumps(payload, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("check", type=Path, help="Path to a .ai-checks/*.md rule file")
    ap.add_argument(
        "--base",
        default=os.environ.get("BASE_REF", "origin/main"),
        help="Base ref for the diff (default: origin/main)",
    )
    ap.add_argument(
        "--model",
        default=os.environ.get("AI_CHECK_MODEL", DEFAULT_MODEL),
        help=f"LiteLLM model string, e.g. openai/gpt-4o-mini (default: {DEFAULT_MODEL})",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ["AI_CHECK_OUTPUT"]) if os.environ.get("AI_CHECK_OUTPUT") else None,
        help="Optional path to write the verdict as JSON (also reads $AI_CHECK_OUTPUT).",
    )
    args = ap.parse_args()

    fm, _ = parse_check(args.check)
    name = fm.get("name", args.check.stem)
    description = fm.get("description", "")

    try:
        result = evaluate(args.check, args.base, args.model)
    except ConfigError as e:
        print(f"[CONFIG ERROR] {name}", file=sys.stderr)
        print(str(e), file=sys.stderr)
        result = {
            "verdict": "fail",
            "summary": "Setup error — see job log.",
            "details": str(e),
        }
        write_step_summary(name, result)
        if args.output:
            write_output_json(args.output, name, description, result)
        print(f"::error title=AI check setup error ({name})::{e}")
        return 2

    marker = {"pass": "PASS", "fail": "FAIL"}[result["verdict"]]
    print(f"[{marker}] {name}")
    print(result["summary"])
    if result.get("details"):
        print()
        print(result["details"])

    write_step_summary(name, result)
    if args.output:
        write_output_json(args.output, name, description, result)
    return 1 if result["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
