"""OpenCode delegate-session client (server API, no TUI scraping).

Hermes drives a headless ``opencode serve`` process over its HTTP JSON API:
create a session, run prompts asynchronously (``prompt_async`` returns HTTP
204), poll messages until the assistant reply lands, and supervise native
interactive questions (``GET /question`` -> auto-answer -> ``POST
/question/{id}/reply`` with ``{answers:[[label], ...]}``).

The HTTP transport is injectable for hermetic tests; by default a small
``urllib`` transport talks to a single lazily-spawned, process-wide shared
server that stays running for the life of the Hermes process — every delegate
session creates a new session inside that one server, scoped per-request via
the ``?directory=`` query parameter.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional, Protocol

from agent.delegate_errors import DelegateTurnStalled, classify_delegate_failure
from agent.delegate_start_budget import bootstrap_stage_budgets

logger = logging.getLogger(__name__)

# Answerer contract shared with the Pi backend: (method, question, options) -> str | None
QuestionAnswerer = Callable[[str, str, list[str]], Optional[str]]

# Readiness gate for a spawned ``opencode serve``: cold boots measured 14-29s
# live (plugin + provider init), so the historical hard-coded 30s gate aborted
# delegate sessions at startup. Plain constant, not an env knob: the repo
# rejects new HERMES_* behaviour env vars (contribution rubric); tests tune
# these via monkeypatch.
_DEFAULT_READY_TIMEOUT = 90.0
_DEFAULT_POLL_INTERVAL = 0.5
# Post-question continuation window: how long after answering a question the
# client must treat idle/stable-without-text as PREMATURE completion (the
# model resumes generating its real continuation after the answer). Sized
# generously — glm-5.3 sat 40+ seconds between question-answer and final
# text in the live failure — while staying well under typical phase budgets
# so a genuinely dead continuation still surfaces within one window.
_POST_QUESTION_GRACE_SECONDS = 90.0
# Bounded legacy fallback for transports that never stamp
# ``info.time.completed``: after an open assistant message has sat this long
# on a fully stable transcript with nothing running, accept the stable exit
# instead of holding the veto until the caller's deadline. Stamp-stamping
# transports (glmplus/OpenCode 1.19.4 verified live) release the veto the
# moment the real turn ends, so this only gates the legacy path.
_STAMPLESS_GENERATION_FALLBACK_SECONDS = 120.0


class _Transport(Protocol):
    def request(
        self, method: str, path: str, body: Optional[dict] = None
    ) -> tuple[int, str]: ...


class _UrllibTransport:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self, method: str, path: str, body: Optional[dict] = None
    ) -> tuple[int, str]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Shared server lifecycle (ONE opencode serve per Hermes process)
# ---------------------------------------------------------------------------

_server_lock = threading.Lock()
# A single shared server hosts every delegate session: sessions (and their
# pending native questions, via ``GET /question``) are addressable in any
# existing directory through the ``?directory=`` query scope, so per-session
# working directories do NOT need their own server process. The server is
# spawned once, kept running for the life of the Hermes process, and each
# delegate_session client creates its own session inside it.
_servers: dict[str, _ServerHandle] = {}
_retired_servers: list[_ServerHandle] = []

_SINGLETON_KEY = "__opencode_singleton__"


class _ServerHandle:
    def __init__(
        self,
        base_url: str,
        proc: Optional[subprocess.Popen],
        config_fingerprint: Optional[tuple] = None,
    ):
        self.base_url = base_url
        self.proc = proc
        self.refcount = 0
        self.config_fingerprint = config_fingerprint
        self.retired = False


def _server_state() -> dict[str, _ServerHandle]:
    return dict(_servers)


def _reset_server_singleton() -> None:
    """Test hook: forget all servers without killing anything."""
    with _server_lock:
        _servers.clear()
        _retired_servers.clear()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _opencode_command() -> list[str]:
    raw = os.environ.get("HERMES_OPENCODE_BIN", "").strip()
    if raw:
        return raw.split()
    binary = shutil.which("opencode") or str(
        os.path.join(Path_home(), ".local", "bin", "opencode")
    )
    return [binary]


def Path_home() -> str:
    return os.path.expanduser("~")


def _hash_file(path: str) -> tuple:
    try:
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        return (path, digest)
    except OSError:
        return (path, None)


def _opencode_config_fingerprint() -> tuple:
    # Content fingerprint for config loaded by opencode serve.
    config_home = os.getenv("XDG_CONFIG_HOME", "").strip()
    if not config_home:
        config_home = os.path.join(Path_home(), ".config")
    root = os.path.join(config_home, "opencode")
    signatures: list[tuple] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        if (
            name.endswith((".json", ".jsonc", ".yaml", ".yml", ".toml", ".lock"))
            or name == "bun.lockb"
        ):
            signatures.append(_hash_file(path))

    explicit = os.environ.get("OPENCODE_CONFIG", "").strip()
    if explicit:
        explicit_path = os.path.abspath(os.path.expanduser(explicit))
        signatures.append(("OPENCODE_CONFIG",) + _hash_file(explicit_path))

    inline = os.environ.get("OPENCODE_CONFIG_CONTENT", "")
    if inline:
        signatures.append(
            (
                "OPENCODE_CONFIG_CONTENT",
                hashlib.sha256(inline.encode("utf-8")).hexdigest(),
            )
        )
    return (root, tuple(signatures))


def _terminate_server_process(handle: _ServerHandle) -> None:
    proc = handle.proc
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _wait_ready(
    base_url: str,
    timeout: float,
    stages: list[float] | None = None,
    proc: Optional[Any] = None,
) -> None:
    # Staged readiness ladder (agent/delegate_start_budget.py, the A4 fix the
    # Pi backend already has): stage 1 keeps the historical 30s wedge-fail
    # bound, later stages give a slow-but-alive server room to finish booting
    # (config+LSP+plugin scan takes 40-160s on a loaded host), and the child
    # is liveness-probed between stages so a crashed serve never burns the
    # full ladder. `stages=None` keeps the legacy single bounded wait.
    last_error: Optional[Exception] = None
    for stage in stages or [timeout]:
        deadline = time.monotonic() + stage
        while time.monotonic() < deadline:
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(
                    f"opencode serve exited with code {proc.poll()} before "
                    f"becoming ready at {base_url}"
                )
            try:
                transport = _UrllibTransport(base_url, timeout=5.0)
                status, _text = transport.request("GET", "/session")
                if status == 200:
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(0.25)
        # Stage exhausted: fall through to the next stage (a live process
        # under load gets the full ladder), or raise after the last one.
    raise RuntimeError(
        f"opencode server not ready at {base_url}: {last_error or 'no response'}"
    )


def acquire_opencode_server(
    working_directory: str = "",
    ready_timeout: float = _DEFAULT_READY_TIMEOUT,
    stages: list[float] | None = None,
) -> _ServerHandle:
    """Return the ONE shared server handle, spawning it on first use.

    ``working_directory`` is accepted for API compatibility but ignored: every
    call is scoped per-request via the ``?directory=`` query parameter, so a
    single long-lived server hosts delegate sessions in any directory.

    ``stages`` carries the staged readiness ladder from
    ``agent/delegate_start_budget.py`` (A4): a fresh ``opencode serve`` boots
    in 40-160s on a loaded host (config + LSP + plugin scan), so the legacy
    fixed 30s gate misclassified every slow-but-alive boot as dead, killed it,
    and re-spawned another — the exact herd the ladder exists to prevent.
    """
    with _server_lock:
        handle = _servers.get(_SINGLETON_KEY)
        if handle is not None:
            proc = handle.proc
            if proc is None:
                handle.refcount += 1
                return handle
            if proc.poll() is None:
                if handle.config_fingerprint == _opencode_config_fingerprint():
                    handle.refcount += 1
                    return handle
                logger.info("OpenCode config changed; rolling over shared server")
                _servers.pop(_SINGLETON_KEY, None)
                if handle.refcount > 0:
                    handle.retired = True
                    _retired_servers.append(handle)
                else:
                    _terminate_server_process(handle)
            else:
                _servers.pop(_SINGLETON_KEY, None)

        external = os.environ.get("HERMES_OPENCODE_SERVER_URL", "").strip()
        if external:
            # Externally managed server: never spawned, never terminated here.
            handle = _ServerHandle(external.rstrip("/"), None)
        else:
            port = _free_port()
            cmd = _opencode_command() + [
                "serve",
                "--port",
                str(port),
                "--hostname",
                "127.0.0.1",
            ]
            # Spawn from a stable home directory: the per-session directory is
            # a query parameter on each call, so the startup cwd only needs to
            # exist for the process lifetime; user plugins load normally.
            spawn_cwd = Path_home()
            proc = subprocess.Popen(
                cmd,
                cwd=spawn_cwd if os.path.isdir(spawn_cwd) else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            handle = _ServerHandle(
                f"http://127.0.0.1:{port}", proc, _opencode_config_fingerprint()
            )
        # Readiness-gate only servers we spawned; an externally managed URL
        # (HERMES_OPENCODE_SERVER_URL) is trusted as-is so a temporarily
        # unreachable remote does not break startup — real calls surface
        # connection errors themselves.
        try:
            if handle.proc is not None:
                _wait_ready(handle.base_url, ready_timeout, stages, handle.proc)
        except Exception:
            if handle.proc is not None:
                _terminate_server_process(handle)
            raise
        handle.refcount = 1
        _servers[_SINGLETON_KEY] = handle
        _ensure_shutdown_hook()
        return handle


def release_opencode_server(handle: _ServerHandle) -> None:
    """Release a client reference and reap retired stale servers."""
    terminate = False
    with _server_lock:
        handle.refcount -= 1
        handle.refcount = max(handle.refcount, 0)
        if handle.retired and handle.refcount == 0:
            if handle in _retired_servers:
                _retired_servers.remove(handle)
            terminate = True
    if terminate:
        _terminate_server_process(handle)


def shutdown_opencode_server() -> None:
    """Terminate the shared server (called at Hermes process exit)."""
    global _shutdown_registered
    with _server_lock:
        handles = list(_servers.values()) + list(_retired_servers)
        _servers.clear()
        _retired_servers.clear()
    for handle in handles:
        _terminate_server_process(handle)


_shutdown_registered = False


def _ensure_shutdown_hook() -> None:
    global _shutdown_registered
    if not _shutdown_registered:
        atexit.register(shutdown_opencode_server)
        _shutdown_registered = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OpenCodeClient:
    """Persistent OpenCode delegate-session client with question supervision."""

    def __init__(
        self,
        *,
        persistent_session: bool = True,
        session_id: str = "",
        session_name: str = "",
        acp_cwd: str = ".",
        question_answerer: Optional[QuestionAnswerer] = None,
        transport_factory: Optional[Callable[[str], _Transport]] = None,
    ):
        self.persistent_session = persistent_session
        self.session_id = session_id
        self.session_name = session_name or f"Hermes {session_id[:8]}"
        self.cwd = os.path.abspath(acp_cwd)
        self.question_answerer = question_answerer
        self._transport_factory = transport_factory
        self._transport: Optional[_Transport] = None
        self._server_handle: Optional[_ServerHandle] = None
        # Readiness budget stashed by start() (A4 ladder for the shared
        # server spawn); defaults reproduce the legacy single 30s wait.
        self._ready_timeout: float = _DEFAULT_READY_TIMEOUT
        self._ready_stages: Optional[list[float]] = None
        self.native_session_id: Optional[str] = None
        # Question ids already replied/rejected (SSE watcher + poll loop race).
        self._answered_questions: set = set()
        self.is_closed = False
        # Wall-clock of the last observed in-turn progress (transcript
        # change). The delegate observer polls this so an outside reader of
        # the durable metadata can tell a live opencode turn from a wedged
        # one — without it opencode delegations are liveness-blind.
        self.last_turn_activity_at: Optional[float] = None

    # -- internals ---------------------------------------------------------

    def _qdir(self) -> str:
        return "?" + urllib.parse.urlencode({"directory": self.cwd})

    def _http(self) -> _Transport:
        if self._transport is not None:
            return self._transport
        if self._transport_factory is not None:
            self._transport = self._transport_factory(self.cwd)
            return self._transport
        if self._server_handle is None:
            self._server_handle = acquire_opencode_server(
                working_directory=self.cwd,
                ready_timeout=self._ready_timeout,
                stages=self._ready_stages,
            )
        self._transport = _UrllibTransport(self._server_handle.base_url)
        return self._transport

    def _request(
        self, method: str, path: str, body: Optional[dict] = None
    ) -> tuple[int, Any]:
        status, text = self._http().request(method, path, body)
        if status >= 400:
            raise RuntimeError(
                f"opencode server {method} {path} failed: HTTP {status}: {text[:500]}"
            )
        if not text:
            return status, None
        try:
            return status, json.loads(text)
        except ValueError:
            return status, text

    # -- backend surface ---------------------------------------------------

    def start(
        self, timeout: float = 30.0, stages: list[float] | None = None
    ) -> dict[str, Any]:
        # `stages` mirrors PiRPCClient's staged start handshake
        # (agent/delegate_start_budget.py): the opencode transport is an HTTP
        # readiness wait rather than an RPC handshake, so the ladder bounds
        # that wait — stage 1 keeps the fast wedge-fail probe, later stages
        # let a slow-but-alive `opencode serve` boot (40-160s under load)
        # instead of being killed and re-spawned (the A4 re-spawn herd).
        # Stashed BEFORE any request so both paths — fresh start and resume
        # of a persisted session in a new process — acquire the shared server
        # through _http() with the same ladder.
        self._ready_timeout = timeout
        self._ready_stages = list(stages) if stages is not None else None
        if self.native_session_id:
            # A persisted native identity is a recovery fence. A missing
            # session (404) or transient server failure (5xx) must NOT mint
            # a replacement: the old session may still have side effects,
            # and silently switching IDs defeats same-session adoption.
            # Surface the error so the existing owner can retry or explicitly
            # reconcile the original identity before any fresh admission.
            self._request("GET", f"/session/{self.native_session_id}")
            return {"sessionId": self.native_session_id}
        if self._server_handle is None and self._transport_factory is None:
            # Real transport: acquire the shared server NOW (not lazily in
            # _http()) so the readiness ladder governs the spawn. Injected
            # transport factories (hermetic tests, custom servers) never
            # spawn anything.
            ready_stages = self._ready_stages
            if ready_stages is None and self._ready_timeout:
                ready_stages = bootstrap_stage_budgets(self._ready_timeout)
            self._server_handle = acquire_opencode_server(
                working_directory=self.cwd,
                ready_timeout=self._ready_timeout or _DEFAULT_READY_TIMEOUT,
                stages=ready_stages,
            )
        _status, payload = self._request("POST", f"/session{self._qdir()}", {"title": self.session_name})
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError(
                f"opencode session create returned no id: {payload!r}"[:500]
            )
        self.native_session_id = str(payload["id"])
        return {"sessionId": self.native_session_id}

    def _message_sort_key(self, message: dict) -> tuple:
        info = message.get("info") or {}
        created = (info.get("time") or {}).get("created") or 0
        return (created, info.get("id") or "")

    def _assistant_text(self, message: dict) -> str:
        parts = message.get("parts") or []
        return "\n".join(
            str(p.get("text") or "") for p in parts if p.get("type") == "text"
        ).strip()

    def _baseline_messages(self) -> list[dict]:
        path = f"/session/{self.native_session_id}/message{self._qdir()}"
        _status, data = self._request("GET", path)
        messages = data if isinstance(data, list) else (data or {}).get("data") or []
        return sorted(messages, key=self._message_sort_key)

    def _pending_questions(self) -> list[dict]:
        # NOTE: /question requires the ?directory= scope; without it OpenCode
        # silently returns [] even when a question is pending for the session.
        _status, data = self._request("GET", f"/question{self._qdir()}")
        rows = data if isinstance(data, list) else (data or {}).get("data") or []
        return [row for row in rows if row.get("sessionID") == self.native_session_id]

    def _answer_pending_questions(self) -> int:
        """Answer pending questions; returns how many were answered/rejected.

        The count (not just a bool) lets the turn loop anchor its
        post-question continuation window on the LAST answer, including
        when an earlier question in the same turn was rejected.
        """
        answered = 0
        for request in self._pending_questions():
            request_id = str(request.get("id") or "")
            if not request_id or request_id in self._answered_questions:
                continue
            questions = request.get("questions") or []
            answers: list[list[str]] = []
            reject = False
            for question in questions:
                options = [
                    str(opt.get("label"))
                    for opt in (question.get("options") or [])
                    if opt.get("label")
                ]
                method = "select" if options else "ask"
                answer = None
                if self.question_answerer is not None:
                    answer = self.question_answerer(
                        method, str(question.get("question") or ""), options
                    )
                if answer is None:
                    reject = True
                    break
                if options:
                    answer = self._match_label(answer, options)
                    if answer is None:
                        reject = True
                        break
                answers.append([answer])
            try:
                if reject:
                    self._request(
                        "POST", f"/question/{request_id}/reject{self._qdir()}", {}
                    )
                    logger.info(
                        "Rejected unanswerable opencode question %s", request_id
                    )
                else:
                    self._request(
                        "POST",
                        f"/question/{request_id}/reply{self._qdir()}",
                        {"answers": answers},
                    )
                    logger.info(
                        "Replied to opencode question %s: %s", request_id, answers
                    )
            except RuntimeError as exc:
                # The SSE watcher and the poll loop can race on the same
                # question; whoever loses gets QuestionNotFoundError (404).
                if "QuestionNotFound" not in str(exc):
                    raise
                logger.debug(
                    "opencode question %s already answered elsewhere", request_id
                )
            self._answered_questions.add(request_id)
            answered += 1
        return answered

    @staticmethod
    def _match_label(answer: str, options: list[str]) -> Optional[str]:
        low = answer.strip().strip(" \"'`.,!\t\n").casefold()
        for option in options:
            if option.strip().casefold() == low:
                return option
        if low.isdigit():
            index = int(low)
            if 1 <= index <= len(options):
                return options[index - 1]
        return None

    def _event_stream_idle(self, timeout: float, idle_flag: threading.Event) -> None:
        """Watch the SSE ``/event`` stream; set ``idle_flag`` on ``session.idle``.

        Also answers questions immediately when a ``question.asked`` event for
        this session arrives (the REST ``/question`` listing lags by several
        seconds — often past the question's own expiry). Best-effort: transport
        errors simply stop the watcher (the polling fallback in
        ``run_session_prompt`` decides completion).
        """
        try:
            transport = self._http()
            url = f"{transport.base_url}/event{self._qdir()}"  # type: ignore[attr-defined]
            req = urllib.request.Request(url, headers={"accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=max(5.0, timeout)) as resp:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline and not idle_flag.is_set():
                    raw = resp.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    etype = event.get("type")
                    props = event.get("properties") or {}
                    if (
                        etype == "session.idle"
                        and str(props.get("sessionID") or "") == self.native_session_id
                    ):
                        idle_flag.set()
                        return
                    if (
                        etype in ("question.asked", "question.v2.asked")
                        and str(props.get("sessionID") or "") == self.native_session_id
                    ):
                        try:
                            self._answer_pending_questions()
                        except Exception:
                            logger.debug(
                                "SSE question auto-answer failed", exc_info=True
                            )
        except Exception:
            logger.debug(
                "opencode event stream failed; polling decides completion",
                exc_info=True,
            )

    def _final_reply_text(self, baseline_ids: set) -> str:
        """Fetch the transcript and join fresh assistant text parts.

        ``<system-reminder>`` blocks are injected scaffolding, not a model
        reply (e.g. the systematic-workflow guard's permission jail): a turn
        whose only text is a reminder has NOT been answered, so strip them
        before deciding whether a reply exists.
        """
        _status, data = self._request(
            "GET", f"/session/{self.native_session_id}/message{self._qdir()}"
        )
        messages = data if isinstance(data, list) else (data or {}).get("data") or []
        messages = sorted(messages, key=self._message_sort_key)
        fresh = [m for m in messages if m.get("info", {}).get("id") not in baseline_ids]
        text = "\n".join(
            self._assistant_text(m)
            for m in fresh
            if (m.get("info") or {}).get("role") == "assistant"
            and self._assistant_text(m)
        ).strip()
        return re.sub(
            r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL
        ).strip()

    @staticmethod
    def _open_message_age_seconds(fresh: list[dict]) -> Optional[float]:
        """Age of the newest still-open assistant message, in seconds.

        2026-10-24 live repro ses_e8fbd486bffeEijK4IE6BKLPDg: multi-step
        turns go QUIET BETWEEN STEPS — step N completes with its stamp,
        OpenCode creates step N+1's empty assistant row while the provider
        call (rate-limit recovery included) takes tens of seconds — and the
        stability window then lapses mid-turn. The open message IS the
        in-flight generation signal, and its age gates the bounded legacy
        fallback. ``time.created`` is a wall-clock epoch (ms), so the age is
        measured against ``time.time()``.
        """
        open_rows = [
            m
            for m in fresh
            if (m.get("info") or {}).get("role") == "assistant"
            and not ((m.get("info") or {}).get("time") or {}).get("completed")
        ]
        if not open_rows:
            return None
        newest_open = max(
            ((m.get("info") or {}).get("time") or {}).get("created") or 0
            for m in open_rows
        )
        return time.time() - (newest_open / 1000.0)

    def run_session_prompt(
        self,
        message: str,
        timeout_seconds: float = 900.0,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> dict[str, Any]:
        started = time.monotonic()
        if not self.native_session_id:
            self.start(timeout=min(30.0, timeout_seconds))
        baseline_ids = {m.get("info", {}).get("id") for m in self._baseline_messages()}
        path = f"/session/{self.native_session_id}/prompt_async{self._qdir()}"
        # The globally configured default `build` is a read-only coordinator
        # whose implementation delegate may not exist. Route Hermes coding
        # work orders to the installed, write-capable fixer agent instead.
        # A host can override this explicitly when its agent roster differs.
        delegate_agent = (
            os.environ.get("HERMES_OPENCODE_DELEGATE_AGENT", "fixer").strip() or "fixer"
        )
        self._request(
            "POST",
            path,
            {
                "agent": delegate_agent,
                "parts": [{"type": "text", "text": message}],
            },
        )
        deadline = time.monotonic() + timeout_seconds
        last_snapshot: Optional[tuple] = None
        stable_since: Optional[float] = None
        # Latest fresh assistant text seen while polling: classification
        # evidence if the turn times out (A1 sibling — provider errors the
        # model streamed are stronger than the bare timeout prose).
        evidence_text = ""
        # Completion signal, in order of reliability:
        #   1. SSE ``session.idle`` for this session (authoritative; watched on
        #      a background thread so question answering keeps running).
        #   2. Fallback heuristic: transcript (IDs + part payloads) unchanged
        #      for the stable window with a fresh assistant message, no tool
        #      part running, and no pending question. Snapshot polling alone is
        #      unreliable because /question registration lags the live turn by
        #      many seconds and empty assistant shells appear immediately.
        stable_window = min(
            max(5.0, poll_interval * 4), max(1.0, timeout_seconds / 3.0)
        )
        idle_flag = threading.Event()
        watcher = threading.Thread(
            target=self._event_stream_idle,
            args=(timeout_seconds, idle_flag),
            daemon=True,
        )
        watcher.start()
        # Post-question continuation window (msn-auto05 2026-10-23 17:26,
        # reproduced hermetically in test_opencode_wait_loop.py): OpenCode
        # fires ``session.idle`` at a question/step boundary AND the
        # transcript snapshot goes stable there, while the model — resumed
        # by the auto-answer — is still generating its real continuation.
        # Both completion signals are therefore premature for a grace
        # window after the LAST question this turn answered: hold the
        # "turn ended without a reply" verdict and keep polling until the
        # continuation lands or the caller's deadline expires. Pi has no
        # analogue because its questions are out-of-band to a single RPC.
        question_answered_at: Optional[float] = None
        try:
            while time.monotonic() < deadline:
                questions_now = self._answer_pending_questions()
                if questions_now:
                    question_answered_at = time.monotonic()
                    # The transcript may evolve past the boundary; reset the
                    # stability anchor so the stable-window cannot fire on
                    # the pre-answer snapshot.
                    stable_since = None
                    last_snapshot = None
                _status, data = self._request(
                    "GET", f"/session/{self.native_session_id}/message{self._qdir()}"
                )
                messages = (
                    data if isinstance(data, list) else (data or {}).get("data") or []
                )
                messages = sorted(messages, key=self._message_sort_key)
                fresh = [
                    m
                    for m in messages
                    if m.get("info", {}).get("id") not in baseline_ids
                ]
                if fresh:
                    for m in reversed(fresh):
                        if (m.get("info") or {}).get("role") == "assistant":
                            captured = self._assistant_text(m)
                            if captured:
                                evidence_text = captured[-2048:]
                                break
                snapshot = tuple(
                    (
                        (m.get("info") or {}).get("id"),
                        tuple(sorted(str(p) for p in (m.get("parts") or []))),
                    )
                    for m in messages
                )
                if snapshot == last_snapshot:
                    if stable_since is None:
                        stable_since = time.monotonic()
                else:
                    stable_since = None
                    last_snapshot = snapshot
                    self.last_turn_activity_at = time.time()
                tools_running = any(
                    (part or {}).get("type") == "tool"
                    and (part.get("state") or {}).get("status") == "running"
                    for m in fresh
                    for part in (m.get("parts") or [])
                )
                # A fresh assistant message with no info.time.completed yet is
                # still streaming: the model may sit in reasoning for tens of
                # seconds before its first visible part (text/tool) lands, so
                # the transcript LOOKS stable (bare step-start row, nothing
                # running) while generation is actually in flight. Waiting for
                # completion on every fresh assistant message closes that gap;
                # without it the poll loop declares the turn empty mid-stream.
                generating = any(
                    (m.get("info") or {}).get("role") == "assistant"
                    and not ((m.get("info") or {}).get("time") or {}).get("completed")
                    for m in fresh
                )
                open_since = self._open_message_age_seconds(fresh)
                # Only NON-EMPTY text (or a definitive end-of-turn) is a
                # reply: glm-5.3 creates the assistant text part EMPTY and
                # streams content into it seconds later (dev-002
                # 2026-10-24: part created 01:02:46.367Z empty, filled
                # 01:03:02.901Z — the old check counted the empty part as
                # content and raised 3.7s before the fill). An empty text
                # part is a streaming placeholder, not a reply.
                has_reply_text = any(
                    (m.get("info") or {}).get("role") == "assistant"
                    and any(
                        (p or {}).get("type") == "text"
                        and str(p.get("text") or "").strip()
                        for p in (m.get("parts") or [])
                    )
                    for m in fresh
                )
                # Definitive end-of-turn: every fresh assistant row carries
                # info.time.completed and nothing is running — the server has
                # stamped the step finished, so stability is real completion
                # even though no text was ever produced (tool-only turn).
                fresh_assistant = [
                    m for m in fresh if (m.get("info") or {}).get("role") == "assistant"
                ]
                all_steps_completed = bool(fresh_assistant) and all(
                    ((m.get("info") or {}).get("time") or {}).get("completed")
                    for m in fresh_assistant
                )
                # Idle events can be observed before the transcript fetch
                # below reflects them; give the message endpoint a short
                # grace period after the flag trips so the final text lands.
                # The stable window alone is NOT evidence the turn ended:
                # between tool steps the transcript sits unchanged while the
                # provider call for the next step is in flight (rate-limit
                # recovery can hold it for a minute or more), so stability
                # routinely lapses mid-turn with an assistant message still
                # open. When any fresh assistant message lacks its completion
                # stamp the turn is still generating: veto the stable exit.
                # The veto releases the moment the stamp lands (verified on
                # glmplus/OpenCode 1.19.4 — finished messages carry it) or,
                # for transports that never stamp, after
                # _STAMPLESS_GENERATION_FALLBACK_SECONDS of full stability so
                # a stamp-less legacy path still terminates.
                stable = (
                    stable_since is not None
                    and time.monotonic() - stable_since >= stable_window
                )
                # Fallback only for a genuinely stamp-less transport. Once
                # this turn has any stamped assistant step, its NEXT open
                # step is evidence generation is in flight, not a legacy
                # endpoint that omits completion stamps. The old fallback
                # ghost-completed real GLM-5.3 development turns after 120s.
                any_stamped_step = any(
                    ((m.get("info") or {}).get("time") or {}).get("completed")
                    for m in fresh_assistant
                )
                generating_veto = generating and not (
                    not any_stamped_step
                    and open_since is not None
                    and stable
                    and open_since >= _STAMPLESS_GENERATION_FALLBACK_SECONDS
                )
                # Idle events can be observed before the transcript fetch
                # below reflects them; give the message endpoint a short
                # grace period after the flag trips so the final text lands.
                # The inter-step veto also gates the idle path: a mid-turn
                # session.idle (observed live at step boundaries) must not
                # complete the turn while a fresh assistant message is open.
                completed = (
                    idle_flag.is_set()
                    and (
                        not tools_running
                        or time.monotonic() - started > timeout_seconds
                    )
                    and not generating_veto
                )
                # Premature-idle guard: within the post-question grace
                # window an idle/stable signal without reply text is NOT
                # turn-end — the continuation is still streaming. Clear
                # the flag and keep polling (the watcher thread has exited
                # by construction, so the transcript-stability fallback
                # decides completion once the window lapses).
                in_question_grace = (
                    question_answered_at is not None
                    and time.monotonic() - question_answered_at
                    < _POST_QUESTION_GRACE_SECONDS
                )
                if completed or (
                    stable
                    and fresh
                    and (has_reply_text or all_steps_completed)
                    and not tools_running
                    and not generating_veto
                    and not self._pending_questions()
                ):
                    if idle_flag.is_set() and tools_running:
                        # Idle raced a still-running tool part: keep waiting.
                        idle_flag.clear()
                        continue
                    text = self._final_reply_text(baseline_ids)
                    if text:
                        return {
                            "text": text,
                            "state": {"sessionId": self.native_session_id},
                            "duration_s": time.monotonic() - started,
                        }
                    if in_question_grace:
                        # Premature completion signal: idle/stability fired
                        # at the question boundary while the resumed model
                        # has not produced its continuation yet. Keep
                        # polling — the alternative is the exact
                        # "turn ended without an assistant text reply"
                        # failure that killed every question-bearing
                        # OpenCode mission turn (msn-m3-opencode-dev-001
                        # through -005, msn-auto05 2026-10-23).
                        idle_flag.clear()
                        continue
                    if idle_flag.is_set():
                        # Authoritative idle but no assistant text yet: one
                        # short re-check before declaring the turn empty.
                        time.sleep(min(2.0, poll_interval * 2))
                        text = self._final_reply_text(baseline_ids)
                        if text:
                            return {
                                "text": text,
                                "state": {"sessionId": self.native_session_id},
                                "duration_s": time.monotonic() - started,
                            }
                    # Genuinely empty turn. Abort the native session BEFORE
                    # detaching: dev-002 (2026-10-24) kept generating for 12+
                    # minutes and finally asked a native question nobody would
                    # ever answer, because the bare raise left the server-side
                    # agent running on a session no client was watching.
                    try:
                        self.abort(timeout=10.0)
                    except Exception:
                        logger.debug(
                            "opencode abort on empty reply failed", exc_info=True
                        )
                    raise RuntimeError(
                        "OpenCode turn ended without an assistant text reply "
                        "(a pending question may have been rejected)"
                    )
                time.sleep(poll_interval)
        finally:
            idle_flag.set()  # stop the SSE watcher
            watcher.join(timeout=5)
        # Timed out: best-effort abort, then surface the timeout.
        try:
            self.abort(timeout=10.0)
        except Exception:
            logger.debug("opencode abort after timeout failed", exc_info=True)
        # Typed stall for the shared delegate vocabulary (A1/D2 sibling):
        # the supervisor reads error_class instead of re-parsing prose, and
        # the provider breaker (A2) records it. This timeout is an absolute
        # wall budget (deliberate, unlike pi's inactivity window), so
        # zero_activity is not a structural signal here; classify from the
        # text the turn actually streamed, else fall back to agent_stall.
        error_class, provider_signal, retry_after = classify_delegate_failure(
            evidence_text, zero_activity=False
        )
        if not evidence_text.strip():
            error_class = "agent_stall"
        raise DelegateTurnStalled(
            f"OpenCode turn timed out after {timeout_seconds:.0f}s",
            error_class=error_class,
            provider_signal=provider_signal,
            retry_after=retry_after,
        )

    def steer(
        self, message: str, timeout: float = 30.0, stages: list[float] | None = None
    ) -> dict[str, Any]:
        # OpenCode prompt_async has no native live-steer injection; the tool
        # layer degrades steer to a queued follow-up turn when no turn is
        # running.  Reaching this method means the caller chose to send anyway.
        # `timeout`/`stages`: call-shape parity with PiRPCClient's staged
        # handshake (tools/delegate_session_tool passes both to every client);
        # accepted and ignored — this path returns an immediate queued note,
        # never waits.
        return {
            "text": "",
            "note": "opencode has no live steer; message queued",
            "queued": True,
        }

    def abort(self, timeout: float = 10.0) -> None:
        if not self.native_session_id:
            return
        self._request("POST", f"/session/{self.native_session_id}/abort{self._qdir()}")

    def get_messages(
        self, timeout: float = 30.0, stages: list[float] | None = None
    ) -> list[dict]:
        # `stages`: accepted-and-ignored, see start().
        _status, data = self._request(
            "GET", f"/session/{self.native_session_id}/message{self._qdir()}"
        )
        messages = data if isinstance(data, list) else (data or {}).get("data") or []
        return sorted(messages, key=self._message_sort_key)

    def _pending_payload_for(self, session_id: str) -> dict[str, Any] | None:
        _status, data = self._request("GET", f"/question{self._qdir()}")
        rows = data if isinstance(data, list) else (data or {}).get("data") or []
        for row in rows:
            if row.get("sessionID") != session_id:
                continue
            first = (row.get("questions") or [{}])[0]
            options = [
                str(opt.get("label"))
                for opt in (first.get("options") or [])
                if opt.get("label")
            ]
            return {
                "method": "select" if options else "ask",
                "question": str(first.get("question") or ""),
                "options": options[:50],
                "created_at": time.time(),
            }
        return None

    def pending_question_payload(self) -> dict[str, Any] | None:
        if not self.native_session_id:
            return None
        return self._pending_payload_for(self.native_session_id)

    def is_dead(self) -> bool:
        handle = self._server_handle
        if handle is None or handle.proc is None:
            return False
        return handle.proc.poll() is not None

    def close(self) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        handle = self._server_handle
        self._transport = None
        self._server_handle = None
        if handle is not None:
            try:
                release_opencode_server(handle)
            except Exception:
                logger.debug("opencode server release failed", exc_info=True)
