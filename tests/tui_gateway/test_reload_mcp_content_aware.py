"""The TUI /reload-mcp broadcast must republish same-name tool changes (#132857).

``_refresh_live_sessions`` rebuilds every live session's cached tool snapshot after an explicit
MCP reload. The rebuild used the name-set gate alone, so a server that changed a tool's
DEFINITION under the same name left every session (TUI and desktop) on the stale schema until a
history-destroying /new. These assert the reload broadcast asks for a content-aware republish and
that ``preserve_prefix`` still travels through untouched (byte-stable prefix inside a live
conversation).
"""

import threading
import types

import tui_gateway.methods_tools as mt


class _null_scope:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_names(monkeypatch):
    """Bind the server-global names _refresh_live_sessions reads (module bodies reference them
    bare after bind_module; a test process may not have installed the module)."""
    agent = types.SimpleNamespace(tools=[], valid_tool_names=set(), platform=None)
    sessions = {"sess-1": {"agent": agent, "profile_home": None}}
    monkeypatch.setattr(mt, "_sessions", sessions, raising=False)
    monkeypatch.setattr(mt, "_sessions_lock", threading.RLock(), raising=False)
    monkeypatch.setattr(mt, "_session_profile_runtime_scope", lambda sess: _null_scope(), raising=False)
    monkeypatch.setattr(mt, "_load_enabled_toolsets", lambda platform=None: None, raising=False)
    monkeypatch.setattr(mt, "_emit", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(mt, "_session_info", lambda agent, sess=None: {}, raising=False)
    return agent, sessions


def _record_refresh(monkeypatch):
    import tools.mcp_tool_agent as mcp_tool_agent

    recorded = {}

    def _record(a, **kwargs):
        recorded.update(kwargs)
        return set()

    monkeypatch.setattr(mcp_tool_agent, "refresh_agent_mcp_tools", _record)
    return recorded


def test_reload_broadcast_requests_content_aware_republish(monkeypatch):
    """The explicit MCP reload path must pass content_aware=True — same-name definition changes
    republish through it; without the flag the name-set gate keeps them stale."""
    _install_names(monkeypatch)
    recorded = _record_refresh(monkeypatch)

    mt._refresh_live_sessions(note="reload")

    assert recorded.get("content_aware") is True


def test_reload_broadcast_preserves_prefix_flag(monkeypatch):
    """preserve_prefix travels through the broadcast unchanged: an in-conversation reload stays
    append-only so the cached request prefix survives."""
    _install_names(monkeypatch)
    recorded = _record_refresh(monkeypatch)

    mt._refresh_live_sessions(preserve_prefix=True, note="reload")

    assert recorded.get("preserve_prefix") is True
    assert recorded.get("content_aware") is True  # explicit reload — both contracts compose
