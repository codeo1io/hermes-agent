"""Pi RPC provider profile.

pi-rpc drives the local ``pi`` coding agent over its native JSONL RPC
protocol (``pi --mode rpc``) — no ACP bridge. The native protocol exposes
``extension_ui_request``, so delegated pi agents can ask the parent
questions and receive real free-text answers.

The profile captures auth + endpoint metadata and supplies its own client via
:meth:`ProviderProfile.create_client` (the same three lines copilot-acp uses).
With the override, the registered profile alone reaches the auxiliary resolver
and the main loop's external-process branch; without it the base class's
``create_client`` returns ``None`` and provider-mode resolution dead-ends at
"not directly supported". Interactive dialogs stay a delegate-session concern:
provider-mode clients are built WITHOUT a ``question_answerer``, so free-text
answering remains opt-in at the one construction site that owns a parent agent
(``tools/delegate_session_tool.py``).
"""

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class PiRPCProfile(ProviderProfile):
    """Pi coding agent — external JSONL RPC process, no REST endpoint."""

    def create_client(self, **client_kwargs: Any) -> Any:
        """Build the pi JSONL RPC client rather than an HTTP client.

        The resolver passes ``api_key`` / ``base_url`` / ``command`` / ``args``
        from the stored pi-rpc credentials. No process is spawned here —
        construction only resolves the ``pi`` binary; the subprocess starts
        at ``start()``.
        """
        from agent.pi_rpc_client import PiRPCClient

        return PiRPCClient(**client_kwargs)

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Model listing is owned by the pi subprocess config."""
        return None


pi_rpc = PiRPCProfile(
    name="pi-rpc",
    aliases=("pi", "pi-agent"),
    api_mode="chat_completions",  # JSONL RPC is routed via chat_completions plumbing
    env_vars=(),  # Managed by the pi subprocess
    base_url="pi://rpc",  # internal marker scheme
    auth_type="external_process",
)

register_provider(pi_rpc)
