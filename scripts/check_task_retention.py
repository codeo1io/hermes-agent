#!/usr/bin/env python3
"""Advisory lint: bare fire-and-forget asyncio dispatches (the rm-089 class).

asyncio keeps only a weak reference to a scheduled task, so an expression-statement
``asyncio.create_task(coro)`` / ``loop.create_task(coro)`` / ``asyncio.ensure_future(coro)``
whose result nobody holds can be garbage-collected mid-flight — the coroutine silently
never finishes ("Task was destroyed but it is pending"). Every fire-and-forget dispatch
must retain its task: the shared bar is ``task_retention.retain_background_task`` (root
module), or an instance/lifecycle set with a done-callback discard
(``gateway.run_adapters._retain_background_task``, ``_track_task``, ``_spawn_bg`` shapes).

Advisory by construction (mirrors ``check_profile_scope_patterns.py``): prints one line
per finding and always exits 0, so it can never break a lane. ``--strict`` exits 1 when
a finding outside the allowlist remains.

Usage:
    python scripts/check_task_retention.py            # whole tree
    python scripts/check_task_retention.py --strict
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that hold no production Python dispatch surface.
SKIP_PREFIXES = (
    "tests/", "website/", "skills/", "optional-skills/", "evals/", "scripts/",
    "apps/", "ui-tui/", "web/", "website/static/", "node_modules/", ".venv/", "venv/",
    "plugins/catalog-cache/", "local_runtime/",
)

# Sites that stay bare, each with the reason. Line numbers are the anchor at the time
# the allowlist was minted — if a fenced edit shifts one, re-anchor the entry (the lint
# is advisory, so drift cannot fail a lane, only soften it).
ALLOWLIST: "dict[tuple[str, int], str]" = {
    ("gateway/run.py", 5336): (
        "operator-signal shutdown handler: the process is mid-teardown and the loop drain "
        "owns the tail; retention is moot past this point"
    ),
    ("agent/lsp/client.py", 306): (
        "claimed by the sibling cycle-2 promotion batch (tests/agent/lsp/"
        "test_dispatch_task_retention.py) — remove when that batch lands"
    ),
    ("gateway/platforms/bluebubbles.py", 609): (
        "claimed by the sibling cycle-2 promotion batch — remove when it lands"
    ),
    ("plugins/platforms/discord/adapter.py", 1218): (
        "claimed by the sibling cycle-2 promotion batch — remove when it lands"
    ),
    ("plugins/platforms/discord/adapter.py", 4097): (
        "claimed by the sibling cycle-2 promotion batch — remove when it lands"
    ),
    ("plugins/platforms/photon/adapter.py", 645): (
        "fenced sibling worktree drift (run-6c1c8a21bd3b region) — remove when reconciled"
    ),
}

SPAWN_ATTRS = {"create_task", "ensure_future"}


def iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        yield path, rel


def bare_spawn_sites(source: str, rel: str):
    """Yield (line, rendered call) for every bare expression-statement spawn."""
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:  # pragma: no cover - defensive
        print(f"{rel}:{exc.lineno or 0}: [task-retention] unparseable: {exc.msg}")
        return
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Attribute) and func.attr in SPAWN_ATTRS):
            continue
        # A bare spawn nested inside a retaining call (retain_background_task(...)) is
        # the fix, not the bug — skip anything that is not a statement of its own.
        yield (node.lineno, ast.unparse(node.value)[:100])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when a finding outside the allowlist remains")
    args = parser.parse_args()

    findings = []
    allowlisted = []
    for path, rel in iter_python_files(REPO_ROOT):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - defensive
            print(f"{rel}: unreadable: {exc}", file=sys.stderr)
            continue
        for line, rendered in bare_spawn_sites(source, rel):
            if (rel, line) in ALLOWLIST:
                allowlisted.append((rel, line))
            else:
                findings.append((rel, line, rendered))

    for rel, line in sorted(allowlisted):
        print(f"{rel}:{line}: allowlisted — {ALLOWLIST[(rel, line)]}")
    for rel, line, rendered in sorted(findings):
        print(f"{rel}:{line}: [task-retention] bare fire-and-forget dispatch: {rendered}")

    stale = sorted(set(ALLOWLIST) - set(allowlisted))
    for rel, line in stale:
        print(f"{rel}:{line}: stale allowlist entry — site moved or fixed; re-anchor or drop it")

    print(f"\ntask-retention: {len(findings)} finding(s), {len(allowlisted)} allowlisted, "
          f"{len(stale)} stale allowlist entrie(s)")
    if findings:
        print("retained dispatches use task_retention.retain_background_task or an "
              "instance set with a done-callback discard")
    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
