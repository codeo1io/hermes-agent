"""Durable abort-salvage for dying delegated turns.

Root cause family: ``cognitive-continuity.prevention.6c3867f4ffd9`` (Maestro
A4, finding a2235ba78b24). When a delegated turn died mid-flight — provider
abort, flat-timeout stall kill, transport death — the v4 durable metadata
banked WHY the turn died (``error``, ``error_class``, ``retry_after``,
``last_turn_triage``) but never WHAT the delegate had produced. The work
product survived only inside the child session store that nothing on the
supervisor side reads. The 2026-10-07/08 abort specimens (delegate attempts
7befc774 and 6ae29ca9: 25 heartbeat progress events, then death) each lost
a half-finished phase with no recoverable tail.

``bank_turn_salvage`` is the one-call seam for that gap: fetch a bounded
tail of the client's transcript at turn-death time and shape it for the
durable metadata record. Everything is argument-driven — no module state, no
environment variables, no I/O of its own beyond the caller-supplied client
call — so it is pure/DI-testable like its sibling modules
(``delegate_errors``, ``delegate_health``, ``delegate_start_budget``). It
never raises and never exceeds its size bounds: a salvage path that can fail
is worse than no salvage path, because it runs on the turn-death path where
the failure evidence itself is being banked.
"""

from __future__ import annotations

import json
import time
from typing import Any

__all__ = [
    "DEFAULT_MAX_MESSAGES",
    "DEFAULT_MAX_MESSAGE_CHARS",
    "DEFAULT_MAX_TOTAL_CHARS",
    "SALVAGE_RPC_TIMEOUT_S",
    "bank_turn_salvage",
]

# Tail bounds. The salvage envelope is a bounded excerpt, not a transcript
# archive: large enough to carry the final work product of a turn (what the
# delegate last concluded, plus its last tool calls), small enough that the
# durable metadata file stays cheap to write on the failure path and cheap
# to read at resume time.
DEFAULT_MAX_MESSAGES = 8
DEFAULT_MAX_MESSAGE_CHARS = 4000
DEFAULT_MAX_TOTAL_CHARS = 24000

# The fetch rides a SHORT RPC budget, not the client's 30s default: it runs
# on the turn-death path, where the child is often wedged or dead, and must
# not delay the terminal metadata persist (bounded waits on death paths are
# the whole lesson of this finding family — see delegate_start_budget).
SALVAGE_RPC_TIMEOUT_S = 5.0

# Tool-call excerpt bounds: names plus bounded argument excerpts, never
# payloads.
_MAX_TOOL_CALLS = 8
_MAX_TOOL_CALL_CHARS = 400

# Text-bearing keys of native message rows, in preference order. Mirrors
# ``_message_text`` in tools/delegate_session_tool (pi text/content shapes,
# opencode ``parts`` rows, tool output/result rows).
_TEXT_KEYS = ("text", "content", "output", "result", "parts")


def _text_of(value: Any) -> str:
    """Best-effort text extraction from a native message value."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_text_of(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            if key in value:
                text = _text_of(value.get(key))
                if text:
                    return text
    return ""


def _role_of(message: Any) -> str:
    if isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
        return role or "message"
    return "message"


def _tool_args_excerpt(entry: Any) -> str:
    """Bounded string form of one tool call's arguments, if any."""
    if not isinstance(entry, dict):
        return ""
    function = entry.get("function")
    if not isinstance(function, dict):
        function = {}
    for source in (
        entry.get("arguments"),
        entry.get("parameters"),
        entry.get("input"),
        entry.get("args"),
        function.get("arguments"),
        function.get("parameters"),
    ):
        if source is None:
            continue
        if not isinstance(source, str):
            try:
                source = json.dumps(source, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                source = str(source)
        return source[:_MAX_TOOL_CALL_CHARS]
    return ""


def _tool_calls_of(message: Any) -> list[dict[str, str]]:
    """Tool-call entries carried by one message row, as {name, args}."""
    found: list[dict[str, str]] = []
    if not isinstance(message, dict):
        return found

    def _add(entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        name = str(entry.get("name") or "").strip()
        if not name and isinstance(entry.get("function"), dict):
            name = str(entry["function"].get("name") or "").strip()
        if name:
            found.append({"name": name, "args": _tool_args_excerpt(entry)})

    calls = message.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            _add(call)
        return found
    # A message row that IS a tool call (assistant tool_use / opencode row).
    if "name" in message and any(
        key in message for key in ("arguments", "parameters", "input", "args")
    ):
        _add(message)
    return found


def bank_turn_salvage(
    client: Any,
    *,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
    rpc_timeout: float = SALVAGE_RPC_TIMEOUT_S,
) -> dict[str, Any] | None:
    """Bank a bounded transcript tail from a delegate client at turn death.

    Best-effort and total: any failure — client without ``get_messages``,
    RPC error, junk shape, degenerate bounds — returns ``None``. On success
    returns::

        {
            "captured_at": <float epoch>,
            "truncated": <bool — excerpt, not the full transcript>,
            "messages": [{"role": str, "text": str}, ...],   # last N, bounded
            "last_tool_calls": [{"name": str, "args": str}, ...],
        }

    or ``None`` when the transcript holds nothing salvageable (no text, no
    tool calls). Never raises.
    """
    try:
        if max_messages < 1 or max_message_chars < 1 or max_total_chars < 1:
            return None
        fetch = getattr(client, "get_messages", None)
        if not callable(fetch):
            return None
        raw = fetch(timeout=rpc_timeout)
        if not isinstance(raw, list) or not raw:
            return None

        truncated = len(raw) > max_messages
        tail = raw[-max_messages:]

        messages: list[dict[str, str]] = []
        used = 0
        for message in tail:
            text = _text_of(message).strip()
            if len(text) > max_message_chars:
                text = text[:max_message_chars]
                truncated = True
            if used + len(text) > max_total_chars:
                room = max_total_chars - used
                if room > 0:
                    messages.append({"role": _role_of(message), "text": text[:room]})
                truncated = True  # budget exhausted: remaining tail dropped
                break
            messages.append({"role": _role_of(message), "text": text})
            used += len(text)

        tool_calls: list[dict[str, str]] = []
        for message in tail:
            tool_calls.extend(_tool_calls_of(message))
            if len(tool_calls) >= _MAX_TOOL_CALLS:
                if len(tool_calls) > _MAX_TOOL_CALLS:
                    tool_calls = tool_calls[:_MAX_TOOL_CALLS]
                    truncated = True
                break

        if not any(entry["text"] for entry in messages) and not tool_calls:
            return None
        return {
            "captured_at": time.time(),
            "truncated": truncated,
            "messages": messages,
            "last_tool_calls": tool_calls,
        }
    except Exception:  # noqa: BLE001 - salvage must never mask the failure path
        return None
