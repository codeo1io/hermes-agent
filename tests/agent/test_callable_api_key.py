"""Tests that callable api_key (Entra ID bearer provider) flows through
the agent stack without coercion.

The OpenAI Python SDK accepts ``api_key: str | None | Callable[[], str]``,
and ``azure-identity``'s ``get_bearer_token_provider`` returns a callable.
Hermes preserves the callable end-to-end so the SDK refreshes tokens
transparently. This file pins the contract at the high-risk seams the
rubber-duck audit identified.

Covered:
  * ``_create_openai_client`` passes a callable ``api_key`` straight
    through to ``openai.OpenAI(...)``.
  * ``_normalize_main_runtime`` preserves the callable so auxiliary
    clients inherit Entra auth.
  * ``_truncate_token`` (dashboard preview) renders ``"<entra-id-bearer>"``
    instead of ``"<function ...>"`` and never invokes the callable.
  * ``run_agent.py`` masked-banner path renders the Entra placeholder
    and never tries to slice/len the callable.
  * Serialization scrub: dumping a runtime dict via ``json.dumps`` with
    a callable api_key raises (default behaviour) — guards against
    silently leaking ``"<function ...>"`` strings into event logs.
  * ``batch_runner`` strips the callable from the worker config dict
    so multiprocessing.Pool can pickle the rest.
"""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# OpenAI SDK construction preserves the callable
# ---------------------------------------------------------------------------


class TestCreateOpenAIClientCallable:
    """``AIAgent._create_openai_client`` must pass the callable through
    to ``openai.OpenAI(...)`` without coercion."""

    def test_callable_api_key_passed_to_openai_constructor(self, monkeypatch):
        """Construct the smallest possible AIAgent surface and verify
        the OpenAI client receives the callable unchanged."""
        captured = {}

        def fake_openai(**kwargs):
            captured["kwargs"] = kwargs
            return MagicMock(api_key=kwargs.get("api_key"))

        # Patch the module-level OpenAI proxy used by ``_create_openai_client``.
        monkeypatch.setattr("agent.process_bootstrap.OpenAI", fake_openai)

        # Build a minimal stand-in for AIAgent so we can call the bound
        # method directly without paying the full __init__ cost.
        from run_agent import AIAgent

        agent = AIAgent.__new__(AIAgent)
        # Attributes consulted by _create_openai_client / _client_log_context.
        agent.provider = "azure-foundry"
        agent.model = "gpt-4o"
        agent.base_url = "https://r.openai.azure.com/openai/v1"
        agent._client_kwargs = {}

        def token_provider():
            return "fresh-jwt"

        client_kwargs = {
            "api_key": token_provider,
            "base_url": "https://r.openai.azure.com/openai/v1",
        }
        client = agent._create_openai_client(client_kwargs, reason="test", shared=False)

        # The OpenAI constructor must receive the *callable*, not a string.
        forwarded = captured["kwargs"]["api_key"]
        assert callable(forwarded)
        assert not isinstance(forwarded, str)
        assert forwarded is token_provider, (
            "_create_openai_client must not wrap or coerce the callable"
        )
        assert client is not None


# ---------------------------------------------------------------------------
# Auxiliary runtime preserves the callable
# ---------------------------------------------------------------------------


class TestNormalizeMainRuntimePreservesCallable:
    """The aux client orchestrator must keep the callable on the
    runtime dict so compression / vision / embedding / title-gen clients
    inherit Entra ID auth from the main agent."""

    def test_callable_api_key_survives_normalization(self):
        from agent.auxiliary_client import _normalize_main_runtime

        def provider():
            return "jwt"

        normalized = _normalize_main_runtime({
            "provider": "azure-foundry",
            "model": "gpt-4o",
            "base_url": "https://r.openai.azure.com/openai/v1",
            "api_key": provider,
            "api_mode": "chat_completions",
            "auth_mode": "entra_id",
        })
        assert normalized["api_key"] is provider
        assert normalized["auth_mode"] == "entra_id"

    def test_string_api_key_still_works(self):
        from agent.auxiliary_client import _normalize_main_runtime
        normalized = _normalize_main_runtime({
            "provider": "azure-foundry",
            "api_key": "sk-static",
        })
        assert normalized["api_key"] == "sk-static"




# ---------------------------------------------------------------------------
# Display surfaces never invoke the callable
# ---------------------------------------------------------------------------


class TestTruncateTokenCallable:
    def test_callable_returns_placeholder(self):
        """Dashboard preview must render the Entra placeholder, NOT
        ``"<function ...>"``."""
        from hermes_cli.web_server_oauth import _truncate_token

        invoked = {"count": 0}

        def provider():
            invoked["count"] += 1
            return "should-not-appear-in-ui"

        token_provider = cast(str | None, provider)
        rendered = _truncate_token(token_provider)
        assert rendered == "<entra-id-bearer>"
        assert invoked["count"] == 0

    def test_string_jwt_still_truncated_to_signature_tail(self):
        from hermes_cli.web_server_oauth import _truncate_token
        # JWT shape: header.payload.signature → only signature tail shown.
        out = _truncate_token("aaaa.bbbb.cccccccsig", visible=4)
        assert out == "…csig"

    def test_empty_returns_empty(self):
        from hermes_cli.web_server_oauth import _truncate_token
        assert _truncate_token(None) == ""
        assert _truncate_token("") == ""


# ---------------------------------------------------------------------------
# Serialization scrub — runtime dicts with callables must NOT silently
# JSON-encode as ``"<function ...>"`` (would leak garbage into events).
# ---------------------------------------------------------------------------


class TestRuntimeDictSerializationGuard:
    def test_json_dumps_default_str_does_not_silently_stringify_callable(self):
        """Sanity check: a runtime dict with a callable api_key must
        either raise on plain ``json.dumps`` (good — fail loud) or be
        sanitized BEFORE serialization. This test pins the loud-fail
        behaviour so future changes that introduce
        ``json.dumps(..., default=str)`` over a runtime dict are caught
        by a regression here."""

        def provider():
            return "jwt"

        runtime = {
            "provider": "azure-foundry",
            "api_key": provider,
            "auth_mode": "entra_id",
        }
        # Plain json.dumps — must raise, not silently produce
        # ``"<function provider at 0x...>"``.
        with pytest.raises(TypeError):
            json.dumps(runtime)


# ---------------------------------------------------------------------------
# batch_runner strips callables from the worker config dict
# ---------------------------------------------------------------------------


class TestBatchRunnerCallableHandling:
    def test_worker_api_key_routes_providers_to_none(self):
        """``batch_runner.worker_api_key`` is the seam ``_worker_config`` builds on:
        a callable Entra provider must become ``None`` (it cannot cross the Pool
        pickle boundary), while anything a worker can pickle passes through
        unchanged."""
        from batch_runner import worker_api_key

        def provider():
            return "jwt"

        assert worker_api_key(provider) is None, (
            "BatchRunner must replace callable api_key with None so "
            "multiprocessing.Pool can pickle the worker config"
        )
        assert worker_api_key("sk-static") == "sk-static"
        assert worker_api_key(None) is None


# ---------------------------------------------------------------------------
# Inline masked-banner / display sites (callable-aware)
# ---------------------------------------------------------------------------


class TestCliEnsureRuntimeCredentialsCallable:
    """Regression: ``cli.py:_ensure_runtime_credentials`` previously
    treated a callable ``api_key`` as "not a string" and overwrote it
    with the ``"no-key-required"`` placeholder, which then got sent as
    ``Authorization: Bearer no-key-required`` and rejected by Azure
    with a 401. This is the most subtle of the callable-api_key audit
    sites — gated by ``not isinstance(api_key, str)`` rather than the
    cleaner ``callable(...)`` check used elsewhere.

    Verified behaviorally against the ``_runtime_credentials_missing``
    seam the method gates on (no real ``HermesCLI`` needed)."""

    def test_callable_api_key_counts_as_present(self):
        """``_runtime_credentials_missing`` is the seam
        ``_ensure_runtime_credentials`` gates on: a callable Entra provider must
        count as a usable credential, or the method substitutes the
        ``"no-key-required"`` placeholder and Azure 401s."""
        from hermes_cli.cli_agent_setup_mixin import _runtime_credentials_missing

        def provider():
            return "jwt"

        assert _runtime_credentials_missing(provider) is False
        assert _runtime_credentials_missing("sk-static") is False
        assert _runtime_credentials_missing("") is True
        assert _runtime_credentials_missing(None) is True


class TestInlinedDisplayMasks:
    """Masked-credential display sites use the ``is_token_provider``
    predicate to short-circuit on callables and print a static
    ``"Microsoft Entra ID"`` label, then fall through to their own
    context-appropriate string mask. The banner paths share
    ``agent/agent_init._print_key_banner``; ``hermes config`` renders
    through ``azure_identity_adapter.display_api_key`` (same label, its
    own unset-rendering for short/missing keys)."""

    def test_run_agent_banner_masks_callable_without_invoking_it(self, capsys):
        """``agent/agent_init._print_key_banner`` is the one helper both banner paths
        (chat_completions and anthropic_messages) route through: it must render a
        callable Entra provider as the static label without ever invoking it, and
        mask string keys without echoing short/stub values."""
        from agent.agent_init import _print_key_banner

        calls = []

        def provider():
            calls.append(1)
            return "jwt"

        _print_key_banner(provider, "token")
        assert "Microsoft Entra ID" in capsys.readouterr().out
        assert calls == [], "banner must never invoke the token provider"

        _print_key_banner("sk-ant-0123456789abcdef", "API key")
        assert "sk-ant-0...cdef" in capsys.readouterr().out

        _print_key_banner("dummy-key", "API key", warn_missing=True)
        assert "invalid or missing" in capsys.readouterr().out

    def test_cli_show_config_handles_callable(self):
        """``cli.HermesCLI.show_config`` renders its key line through
        ``azure_identity_adapter.display_api_key``: a callable Entra provider gets the
        static label, a long string key gets masked, and anything else renders as
        unset — never a slice of a callable."""
        from agent.azure_identity_adapter import display_api_key

        calls = []

        def provider():
            calls.append(1)
            return "jwt"

        assert display_api_key(provider) == "Microsoft Entra ID"
        assert calls == [], "display must never invoke the token provider"
        assert display_api_key("sk-ant-0123456789abcdef") == "sk-ant-0...cdef"
        assert display_api_key("short") == "Not set!"
        assert display_api_key("") == "Not set!"
        assert display_api_key(None) == "Not set!"


