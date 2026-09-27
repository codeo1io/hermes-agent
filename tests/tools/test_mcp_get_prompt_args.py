"""Regression tests for MCP ``prompts/get`` argument coercion.

Background
==========
``prompts/get`` arguments are ``dict[str, string]`` in the MCP spec, but the
model can send JSON scalars (``{\"count\": 3}``, ``{\"flag\": true}``). The
python-sdk's pydantic validation rejected those with a raw ``ValidationError``
surfacing as ``MCP call failed: ValidationError`` — the model gets a stack
trace instead of a usable tool result (upstream #124454).

``tools.mcp_tool_handlers._coerce_prompt_arguments`` now coerces scalars to
their string form (bools JSON-style: ``true``/``false``) before the call, and
raises a ``ValueError`` naming the offending key for structured values, which
``_dispatch`` converts into the normal model-facing tool-error string.

Contract tested here (behavior, not shape):
- scalars (str/int/float/bool) arrive at ``session.get_prompt`` as strings
- absent/None ``arguments`` stays an empty dict
- structured values (list/dict) and non-object ``arguments`` fail with an
  error naming the problem, not an SDK stack trace
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tools.mcp_tool_handlers import _coerce_prompt_arguments, _make_get_prompt_handler


class _FakeSession:
    """Records the arguments it was called with; stands in for mcp.ClientSession."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def get_prompt(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        return SimpleNamespace(messages=[], description=None)


def _invoke(rpc, args):
    """Run the bound rpc lambda (session, args, server_name) to completion."""
    return asyncio.new_event_loop().run_until_complete(rpc(_FakeSession(), args, "srv"))


def test_scalar_arguments_are_coerced_to_strings():
    coerced = _coerce_prompt_arguments({"topic": "agents", "count": 3, "ratio": 0.5, "flag": True, "off": False})
    assert coerced == {"topic": "agents", "count": "3", "ratio": "0.5", "flag": "true", "off": "false"}


def test_none_and_missing_arguments_become_empty_dict():
    assert _coerce_prompt_arguments(None) == {}
    assert _coerce_prompt_arguments({}) == {}


def test_structured_argument_values_are_rejected_with_key_name():
    with pytest.raises(ValueError, match="'items'"):
        _coerce_prompt_arguments({"items": ["a", "b"]})
    with pytest.raises(ValueError, match="'nested'"):
        _coerce_prompt_arguments({"nested": {"k": 1}})


def test_non_object_arguments_are_rejected():
    with pytest.raises(ValueError, match="object of string values"):
        _coerce_prompt_arguments(["not", "an", "object"])


def test_production_handler_coerces_before_the_call(monkeypatch):
    """The real ``_make_get_prompt_handler`` binding feeds coerced string arguments to
    ``session.get_prompt`` (patched at the seams production reads: discovery lookup and
    the MCP-loop runner — the pattern used by tests/tools/test_mcp_tool.py)."""
    import contextlib
    import json

    import tools.mcp_tool_discovery as discovery
    import tools.mcp_tool_loop
    from tools.mcp_tool_handlers import _make_get_prompt_handler

    session = _FakeSession()
    monkeypatch.setattr(
        discovery, "_get_connected_server_for_call",
        lambda name: SimpleNamespace(session=session, _rpc_lock=contextlib.nullcontext()))
    monkeypatch.setattr(
        tools.mcp_tool_loop, "_run_on_mcp_loop",
        lambda factory, timeout=None: asyncio.new_event_loop().run_until_complete(factory()))

    payload = json.loads(_make_get_prompt_handler("srv", 5.0)({"name": "summarize", "arguments": {"count": 7}}))

    assert session.calls == [("summarize", {"count": "7"})]
    assert payload == {"messages": []}
