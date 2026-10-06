"""Retention for fire-and-forget asyncio tasks (the rm-089 invariant).

asyncio keeps only a *weak* reference to a scheduled task: a task whose result nobody
holds can be garbage-collected mid-flight while parked on an awaitable nothing else
references, silently destroying the work ("Task was destroyed but it is pending").
Every fire-and-forget dispatch must retain its task until completion.

The gateway's instance-level bar is ``gateway.run_adapters._retain_background_task``;
this module is the dependency-neutral equivalent for code that must not import
``gateway`` (``hermes_cli``, ``tui_gateway``, ``tools``, ``plugins`` — non-gateway
packages never import gateway, and ``tools/`` never imports ``agent/``).
``scripts/check_task_retention.py`` lints the tree for bare dispatches that bypass it.
"""

from __future__ import annotations

import asyncio

_background_tasks: "set[asyncio.Task]" = set()


def retain_background_task(task: "asyncio.Task") -> "asyncio.Task":
    """Hold ``task`` alive until it completes; returns it for inline use.

    A done-callback drops the task from the retention set as soon as it finishes, so the
    set never outlives live work. Classes that own a lifecycle set (an adapter's
    ``_background_tasks`` drained on shutdown) should keep using it — this helper is for
    call sites with no instance to hang the reference on.
    """
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def retained_tasks() -> "tuple[asyncio.Task, ...]":
    """Snapshot of the tasks currently held by the retention set."""
    return tuple(_background_tasks)
