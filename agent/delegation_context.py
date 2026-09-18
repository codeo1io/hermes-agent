"""Context-local state for delegate_task child execution.

A Hermes process may itself be a Kanban dispatcher worker with HERMES_KANBAN_* in
os.environ. In-process delegate_task children and cron jobs fired via
``cronjob(action="run")`` are NOT dispatcher-owned, so identity gates must fail
closed for them without mutating the process-global environment.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Mapping, MutableMapping, overload

_DELEGATED_CHILD_CONTEXT: ContextVar[bool] = ContextVar("hermes_delegated_child_context", default=False)
# Any in-process execution that is NOT the dispatcher-owned worker (cron jobs). Kept separate
# so delegate_task-specific behaviour (subprocess env scrubbing, its error strings) is unchanged.
_NON_DISPATCHER_OWNED_CONTEXT: ContextVar[bool] = ContextVar("hermes_non_dispatcher_owned_context", default=False)

DELEGATED_CHILD_ENV_MARKER = "HERMES_DELEGATED_CHILD_CONTEXT"

KANBAN_ENV_KEYS: tuple[str, ...] = (
    "HERMES_KANBAN_TASK", "HERMES_KANBAN_RUN_ID", "HERMES_KANBAN_CLAIM_LOCK",
    "HERMES_KANBAN_GOAL_MODE", "HERMES_KANBAN_GOAL_MAX_TURNS",
)

# Board-location pins (as opposed to identity): a descendant's verification
# subprocesses (pytest, conductor fleet runs) must have these repointed at a
# per-lineage scratch board, never the live board the dispatcher pinned.
KANBAN_LOCATION_ENV_KEYS: tuple[str, ...] = (
    "HERMES_KANBAN_DB", "HERMES_KANBAN_WORKSPACES_ROOT", "HERMES_KANBAN_HOME",
)


@contextmanager
def delegated_child_context(session_id: str | None = None) -> Iterator[None]:
    """Mark child execution and isolate its task-local session identity. Even a context
    entered without an id must restore the parent's session ContextVar (child
    construction calls ``set_current_session_id``)."""
    token = _DELEGATED_CHILD_CONTEXT.set(True)
    try:
        from gateway.session_context import scoped_current_session_id  # lazy: it calls is_delegated_child_context()

        with scoped_current_session_id(session_id):
            yield
    finally:
        _DELEGATED_CHILD_CONTEXT.reset(token)


def is_delegated_child_context() -> bool:
    """Return True while code is running for a delegate_task child."""
    return bool(_DELEGATED_CHILD_CONTEXT.get())


def enter_non_dispatcher_owned_context() -> Token[bool]:
    """Token form of :func:`non_dispatcher_owned_context` for long try/finally scopes."""
    return _NON_DISPATCHER_OWNED_CONTEXT.set(True)


def exit_non_dispatcher_owned_context(token: Token[bool]) -> None:
    """Restore the flag saved by :func:`enter_non_dispatcher_owned_context`."""
    _NON_DISPATCHER_OWNED_CONTEXT.reset(token)


@contextmanager
def non_dispatcher_owned_context() -> Iterator[None]:
    """Mark in-process execution that does NOT own the dispatcher's Kanban task; without it
    a cron agent run inside a worker is misread as that worker (kanban toolset force-added,
    ``kanban_complete`` defaulting to its task). ContextVar-scoped rather than clearing
    os.environ, which the worker's claim heartbeat and concurrent readers share."""
    token = enter_non_dispatcher_owned_context()
    try:
        yield
    finally:
        exit_non_dispatcher_owned_context(token)


def is_dispatcher_owned_worker_context() -> bool:
    """The single predicate every ``HERMES_KANBAN_*`` identity gate should use."""
    return not (is_delegated_child_process_context() or _NON_DISPATCHER_OWNED_CONTEXT.get())


def owned_kanban_task() -> str:
    """The board task this execution OWNS: ``HERMES_KANBAN_TASK`` for the dispatcher-owned
    worker, ``""`` otherwise. Tool access is not worker identity — a profile can expose the
    kanban toolset interactively, and children/cron runs inherit the env var — so every
    reader that turns the task id into worker behaviour (guidance, stop nudge, terminal
    outcomes) goes through this one helper."""
    if not is_dispatcher_owned_worker_context():
        return ""
    return (os.environ.get("HERMES_KANBAN_TASK") or "").strip()


def is_delegated_child_process_context() -> bool:
    """Return True in this process or a subprocess spawned by a child."""
    return bool(_DELEGATED_CHILD_CONTEXT.get()) or bool(os.environ.get(DELEGATED_CHILD_ENV_MARKER))


def _fenced_kanban_root() -> str:
    """The board root this process's Kanban lineage lives under (``kanban_home()``); ``"1"`` when it
    cannot be resolved, which readers treat as "fence every board" (the pre-path marker)."""
    try:
        from hermes_cli.kanban_db import kanban_home
        return str(kanban_home())
    except Exception:
        return "1"


def _scratch_kanban_root(env: Mapping[str, str]) -> str | None:
    """Per-lineage scratch board root for repinning a descendant's board pins.

    Verification/agent subprocesses a worker spawns (pytest, conductor fleet runs)
    must not carry the dispatcher's live-board ``HERMES_KANBAN_DB`` pin: the pin
    outranks every test-fixture sandbox (``kanban_db_path()`` resolves it first),
    so a test suite that leaks fixture rows writes them into the LIVE board
    (2026-09-17: 7 fixture waves, 156 rows, two real worker runs burned). A strip
    is not enough either — without the pin ``kanban_db_path()`` falls back to
    ``kanban_home()`` (the shared default root), which IS the live board. The pin
    must be repointed at a scratch root the lineage owns.

    The scratch root lives under the worker's task workspace when it is a real
    directory (``HERMES_KANBAN_WORKSPACE``), else under the system temp dir, so
    scratch boards die with the workspace instead of accumulating.
    """
    workspace = str(env.get("HERMES_KANBAN_WORKSPACE") or "").strip()
    if workspace:
        try:
            from pathlib import Path
            root = Path(workspace).expanduser()
            if root.is_dir():
                return str(root / ".kanban-scratch")
        except Exception:
            pass
    from pathlib import Path
    import tempfile
    return str(Path(tempfile.gettempdir()) / f"hermes-kanban-scratch-{os.getpid()}")


def scrub_kanban_env(env: Mapping[str, str] | MutableMapping[str, str]) -> dict[str, str]:
    """Remove worker identity, retaining board/location and an inherited write fence.

    TASK absence alone would promote a descendant to an orchestrator. The marker
    survives later execs, including scripts that remove TASK themselves. This is
    cooperative runtime scoping, not confinement of code with direct SQLite access.

    The marker's value is the fenced board ROOT, so the fence applies to the lineage's
    board and not to every Kanban DB the descendant touches: a child running a repro
    against a temp ``HERMES_HOME`` got a silently read-only board there. An inherited
    path-valued marker is kept (a grandchild that moved HERMES_HOME must not re-fence
    onto its scratch root and unfence the real one).

    Board-location pins are RETAINED for reads (``HERMES_KANBAN_DB`` still names the
    lineage board) but a verification subprocess never sees them: the dispatcher
    repins them to a per-lineage scratch board at spawn (see
    :func:`repin_kanban_board_env`). Only the write fence is inherited.
    """
    cleaned = {k: v for k, v in env.items() if k not in KANBAN_ENV_KEYS}
    inherited = str(env.get(DELEGATED_CHILD_ENV_MARKER) or "")
    cleaned[DELEGATED_CHILD_ENV_MARKER] = inherited if inherited and inherited != "1" else _fenced_kanban_root()
    return cleaned


def repin_kanban_board_env(env: Mapping[str, str] | MutableMapping[str, str]) -> dict[str, str]:
    """Repoint a descendant env's live-board pins at a per-lineage scratch board.

    Counterpart to :func:`scrub_kanban_env` for the operational leak class
    (2026-09-17): the worker's pytest/conductor verification children inherited the
    dispatcher's ``HERMES_KANBAN_DB`` pin and wrote fixture cards into the live
    board. Stripping is insufficient (``kanban_db_path()`` falls back to
    ``kanban_home()``, the live root), so both location pins are repointed:

    * ``HERMES_KANBAN_DB``           -> ``<scratch>/kanban.db``
    * ``HERMES_KANBAN_WORKSPACES_ROOT`` -> ``<scratch>/workspaces``

    ``HERMES_KANBAN_HOME`` (a third location override) is dropped when set — the
    scratch DB pin outranks it everywhere. Read-only board intent survives via the
    inherited write-fence marker; reads fall back to the scratch board, which
    exists for exactly the lifetime of the leak-prone child.

    Not applied when ``env`` carries no kanban pin (a non-worker host process
    spawning an ordinary child must keep its env untouched).
    """
    if not any(key in env for key in KANBAN_LOCATION_ENV_KEYS):
        return dict(env)
    cleaned = dict(env)
    scratch = _scratch_kanban_root(env)
    cleaned["HERMES_KANBAN_DB"] = f"{scratch}/kanban.db"
    cleaned["HERMES_KANBAN_WORKSPACES_ROOT"] = f"{scratch}/workspaces"
    cleaned.pop("HERMES_KANBAN_HOME", None)
    return cleaned


# Test-runner invocations whose fixtures historically leaked into the live board
# when the dispatcher's pin rode the child env (2026-09-17: 7 waves / 156 rows).
# Matched as COMMAND TOKENS (never substrings): a repro script under
# /tmp/pytest-of-agent/... carries "pytest" in its path but is not a runner.
_TEST_RUNNER_TOKENS: tuple[str, ...] = ("pytest", "unittest", "nose2", "green")
_TEST_RUNNER_SUFFIXES: tuple[str, ...] = (
    "/pytest", "/unittest", "/nose2",
    "run_tests_parallel.py", "run_tests.sh", "run_tests.py",
)


def _token_is_test_runner(token: str) -> bool:
    if token in _TEST_RUNNER_TOKENS:
        return True
    return any(token.endswith(suffix) for suffix in _TEST_RUNNER_SUFFIXES)


def looks_like_test_runner_command(command: "str | None") -> bool:
    """Whether *command* is (or wraps) a test-runner invocation.

    Token-based, not a substring scan: pytest's own tmp dirs contain ``pytest``
    in every path (``/tmp/pytest-of-agent/pytest-N/...``), so a bare substring
    match would repin ordinary repro scripts that merely live there. A token
    matches when it IS a runner (``pytest``, ``python -m pytest``, ``-m
    unittest``) or is a path to one (``/venv/bin/pytest``,
    ``scripts/run_tests_parallel.py``). This catches the fleet shapes a worker
    actually launches — including inside ``bash -c 'cd ... && pytest -q'``
    conductor wrappers — while leaving ``python /tmp/pytest-of-agent/.../repro.py``
    on the pinned board. False positives only repin a child to a scratch board
    (the safe direction); false negatives fall back to the write fence.
    """
    if not command:
        return False
    head = command[:2048]
    # Strip shell comments: a token after '#' is prose, not a command — the
    # classic footgun here is pytest's own tmp paths plus a trailing annotation.
    cut = head.find("#")
    if cut != -1:
        head = head[:cut]
    for raw in head.split():
        token = raw.strip("\"'(){};|&<>)")
        if not token or "=" in token and not token.startswith("-"):
            # Env-assignment prefixes (FOO=bar cmd) and flags are not commands.
            continue
        if _token_is_test_runner(token):
            return True
    return False


def kanban_env_for_child_command(
    command: "str | None",
    env: Mapping[str, str] | MutableMapping[str, str],
) -> dict[str, str]:
    """Env for a worker descendant subprocess, repinning board pins for runners.

    Split out of :func:`delegated_child_subprocess_env` so the TERMINAL spawn
    surface — the one place the command string is visible — can apply the
    operational guard: a test-runner child gets the live-board location pins
    repointed at a scratch board (fixtures land there even on a stale tree
    with no write fence), while ordinary commands keep their pinned board for
    legitimate reads (``kanban show`` in a repro script). The identity scrub
    and write fence apply to both paths via :func:`scrub_kanban_env`.
    """
    cleaned = dict(env)
    if looks_like_test_runner_command(command):
        cleaned = repin_kanban_board_env(cleaned)
    return scrub_kanban_env(cleaned)


def kanban_path_is_fenced(path: "os.PathLike[str] | str") -> bool:
    """Whether Kanban mutations at *path* (a board DB or board-metadata root) are denied for this
    process: always for an in-process delegate child (the parent's own board); for a spawned
    descendant only when *path* is the dispatcher-pinned ``HERMES_KANBAN_DB`` or lies under the
    fenced root the marker carries. A legacy ``"1"`` marker fences everything."""
    if _DELEGATED_CHILD_CONTEXT.get():
        return True
    marker = os.environ.get(DELEGATED_CHILD_ENV_MARKER, "")
    if not marker:
        return False
    if marker == "1":
        return True
    from pathlib import Path
    target = Path(path).expanduser().resolve()
    pinned = os.environ.get("HERMES_KANBAN_DB", "").strip()
    if pinned and target == Path(pinned).expanduser().resolve():
        return True
    try:
        target.relative_to(Path(marker).expanduser().resolve())
    except ValueError:
        return False
    return True


@overload
def delegated_child_subprocess_env(env: Mapping[str, str]) -> dict[str, str]: ...


@overload
def delegated_child_subprocess_env(env: None = None) -> dict[str, str] | None: ...


def delegated_child_subprocess_env(
    env: Mapping[str, str] | MutableMapping[str, str] | None = None,
) -> dict[str, str] | None:
    """Carry worker/delegate descendant denial across a real process spawn.

    Location and credentials are untouched; callers retain their existing secret policy.
    Dispatcher workers and supervised tool transports grant their own explicit scope.
    (Board-location pins stay for fenced READ access; verification subprocesses get
    them repointed at spawn via :func:`kanban_env_for_child_command`.)
    """
    if not (is_delegated_child_process_context() or os.environ.get("HERMES_KANBAN_TASK")
            or (env and (env.get("HERMES_KANBAN_TASK") or env.get(DELEGATED_CHILD_ENV_MARKER)))):
        return None if env is None else dict(env)
    return scrub_kanban_env(os.environ if env is None else env)
