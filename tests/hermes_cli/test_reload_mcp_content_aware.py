"""The CLI /reload-mcp must republish same-name tool changes (#132857).

``CLIInfoMixin._reload_mcp`` rebuilds the agent's tool snapshot after an explicit MCP reload.
The rebuild used the name-set gate alone, so a server that changed a tool's DEFINITION under the
same name kept the model on the stale schema until a history-destroying /new. This asserts the
CLI's explicit reload asks for a content-aware republish.
"""

import threading
import types
from unittest.mock import patch

from hermes_cli.cli_info_mixin import CLIInfoMixin


def _stub_self():
    agent = types.SimpleNamespace(
        tools=[{"type": "function", "function": {"name": "read_file", "description": "v1", "parameters": {}}}],
        valid_tool_names={"read_file"},
    )
    self = types.SimpleNamespace(
        _command_running=True,  # suppress the progress prints
        agent=agent,
        enabled_toolsets=None,
        conversation_history=[],
    )
    return self


def _record_refresh():
    import tools.mcp_tool_agent as mcp_tool_agent

    recorded = {}

    def _record(a, **kwargs):
        recorded.update(kwargs)
        return set()

    return mcp_tool_agent, recorded, _record


def test_cli_reload_mcp_requests_content_aware_republish():
    """/reload-mcp (CLI) must pass content_aware=True — same-name definition changes republish
    through it; without the flag the name-set gate keeps them stale."""
    mcp_tool_agent, recorded, record = _record_refresh()
    self = _stub_self()

    with (
        patch("tools.mcp_tool_lifecycle.shutdown_mcp_servers", lambda: None),
        patch("tools.mcp_tool_discovery.discover_mcp_tools", return_value=[]),
        patch("tools.mcp_tool_agent.reprobe_tool_availability", lambda: None),
        patch("tools.mcp_tool._servers", {}, create=True),
        patch("tools.mcp_tool._lock", threading.Lock(), create=True),
        patch.object(mcp_tool_agent, "refresh_agent_mcp_tools", record),
    ):
        CLIInfoMixin._reload_mcp(self)

    assert recorded.get("content_aware") is True
    assert recorded.get("quiet_mode") is True
