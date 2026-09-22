"""agent_init ↔ anthropic_credentials integration (restored release-line state).

Supersedes the 2026-09-22 00:53Z hot-patch compat test, which asserted the
LEAN anthropic_credentials state (no anthropic_route_is_oauth, no-arg-only
resolver) that 29f06d3b shipped. The release-tag module is restored, so these
tests pin the real contract: the model-aware resolver is called for native
Anthropic routes only, and the OAuth route classifier decides identity
headers with third-party Anthropic-protocol endpoints never qualifying.
"""

from types import SimpleNamespace

import agent.agent_init as agent_init
import agent.anthropic_credentials as anthropic_credentials
import agent.anthropic_adapter as anthropic_adapter


def _agent(provider="anthropic"):
    return SimpleNamespace(provider=provider, quiet_mode=True, model="claude-sonnet-4-6")


def test_resolver_module_exposes_release_line_api():
    assert callable(anthropic_credentials.anthropic_route_is_oauth)
    # Both call shapes the call sites use keep working.
    anthropic_credentials.resolve_anthropic_token()
    anthropic_credentials.resolve_anthropic_token(model="claude-sonnet-4-6")


def test_native_anthropic_uses_model_aware_resolver(monkeypatch):
    seen = {}

    def fake_resolve(*, model=None):
        seen["model"] = model
        return "marker"

    monkeypatch.setattr(anthropic_credentials, "resolve_anthropic_token", fake_resolve)
    monkeypatch.setattr(anthropic_adapter, "build_anthropic_client", lambda *a, **k: object())

    agent = _agent()
    agent_init._init_anthropic_client(agent, "", "https://api.anthropic.com", 1)

    assert seen["model"] == "claude-sonnet-4-6"
    assert agent.api_key == "marker"
    assert agent._anthropic_client is not None


def test_third_party_never_resolves_anthropic_token(monkeypatch):
    # #1739: resolving Anthropic credentials for a non-Anthropic provider
    # would leak them to third-party endpoints.
    def boom(*, model=None):
        raise AssertionError("resolver must not be called for third-party providers")

    monkeypatch.setattr(anthropic_credentials, "resolve_anthropic_token", boom)
    monkeypatch.setattr(anthropic_adapter, "build_anthropic_client", lambda *a, **k: object())

    agent = _agent(provider="custom")
    agent_init._init_anthropic_client(agent, "", "https://example.invalid/v1", 1)

    assert agent.api_key == ""


def test_oauth_route_classifier_semantics_through_init(monkeypatch):
    monkeypatch.setattr(anthropic_adapter, "build_anthropic_client", lambda *a, **k: object())

    native = _agent()
    agent_init._init_anthropic_client(native, "sk-ant-oat-marker", "https://api.anthropic.com", 1)
    assert native._is_anthropic_oauth is True

    third_party = _agent(provider="custom")
    agent_init._init_anthropic_client(third_party, "sk-ant-oat-marker", "https://example.invalid/v1", 1)
    assert third_party._is_anthropic_oauth is False
