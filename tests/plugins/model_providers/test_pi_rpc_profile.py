"""pi-rpc provider profile: registration + client construction.

The profile must supply its own client via ``ProviderProfile.create_client`` —
the same three lines copilot-acp uses. Without the override the base class's
``create_client`` returns ``None`` and provider-mode resolution dead-ends at
"not directly supported": the alias is registered, credentials are stored, and
no pi-rpc request can ever construct a client.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(scope="module")
def pi_rpc_profile():
    import model_tools  # discovery: registers built-in + plugin providers

    from providers import get_provider_profile

    profile = get_provider_profile("pi-rpc")
    assert profile is not None, "pi-rpc profile must be registered after discovery"
    return profile


class TestPiRPCProfileIdentity:
    def test_profile_is_registered_with_pi_alias(self, pi_rpc_profile):
        assert pi_rpc_profile.name == "pi-rpc"
        assert "pi" in (pi_rpc_profile.aliases or ())
        assert pi_rpc_profile.auth_type == "external_process"
        assert pi_rpc_profile.base_url == "pi://rpc"

    def test_fetch_models_defers_to_the_subprocess(self, pi_rpc_profile):
        assert pi_rpc_profile.fetch_models() is None


class TestPiRPCCreateClient:
    def test_create_client_builds_the_jsonl_rpc_client(self, pi_rpc_profile):
        from agent.pi_rpc_client import PiRPCClient

        client = pi_rpc_profile.create_client(
            api_key="stored", base_url="pi://rpc",
            command=sys.executable, args=["--mode", "rpc"],
        )
        assert isinstance(client, PiRPCClient)
        assert client.api_key == "stored"
        assert client.base_url == "pi://rpc"
        assert client._pi_bin == sys.executable
        assert client._extra_args == ["--mode", "rpc"]

    def test_create_client_applies_pi_rpc_defaults(self, pi_rpc_profile):
        from agent.pi_rpc_client import PI_RPC_MARKER_BASE_URL, PiRPCClient

        client = pi_rpc_profile.create_client(api_key="pi-rpc", base_url="pi://rpc", command=sys.executable, args=[])
        assert isinstance(client, PiRPCClient)
        # The marker scheme is what routes this client away from HTTP transports.
        assert client.base_url == PI_RPC_MARKER_BASE_URL


class TestPiRPCProviderModeResolution:
    def test_external_process_branch_returns_a_client(self, pi_rpc_profile):
        """The acceptance leg: provider-mode resolution must not dead-end.

        ``_resolve_external_process_branch`` looks the profile up in the registry
        and calls its ``create_client`` with the stored credentials. Before the
        override this returned ``(None, None)`` ("not directly supported") for
        every pi-rpc request.
        """
        from agent.auxiliary_client import _ResolveRequest, _resolve_external_process_branch
        from agent.pi_rpc_client import PiRPCClient

        req = _ResolveRequest(
            provider="pi-rpc", original_provider="pi-rpc", model="test-model",
            async_mode=False, raw_codex=False, explicit_base_url=None,
            explicit_api_key=None, api_mode=None, main_runtime=None,
            is_vision=False, task=None,
        )
        client, model = _resolve_external_process_branch(req, {
            "api_key": "pi-rpc", "base_url": "pi://rpc",
            "command": sys.executable, "args": [],
        })
        assert isinstance(client, PiRPCClient)
        assert model == "test-model"
