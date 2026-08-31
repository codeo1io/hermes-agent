"""The product tree must not enforce host-specific provider policy.

``HERMES_CLIPROXY_ONLY`` was a deployment concern encoded in the product: a
21-key credential blocklist in ``env_loader`` plus provider/model allowlists in
``auth`` and ``model_switch``. It was half-implemented -- the blocklist omitted
``CUSTOM_API_KEY`` while ``auth`` allowlisted the ``custom`` provider -- so it
behaved as a false security boundary, and it has been extracted to the
deployment layer (hermes-infra ``hosts/agent-runner/hermes-agent/``).

These tests are the regression guard for that extraction: setting the variable
must have no effect on the product. Every assertion fails on the
pre-extraction tree, so reintroducing host policy on any of the three surfaces
fails loudly here.
"""

from __future__ import annotations

import os


def test_cliproxy_only_does_not_strip_provider_credentials(monkeypatch, tmp_path):
    """The env loader must not remove provider credentials under the flag.

    Pre-extraction this popped OPENAI_API_KEY (and 20 siblings) from
    os.environ whenever the flag was set.
    """
    monkeypatch.setenv("HERMES_CLIPROXY_ONLY", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-guard-not-a-real-key")

    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=tmp_path, load_external_secrets=False)

    assert os.environ.get("OPENAI_API_KEY") == "sk-guard-not-a-real-key"


def test_cliproxy_only_does_not_block_provider_resolution(monkeypatch):
    """Provider resolution must behave identically with/without the flag.

    Pre-extraction resolve_provider("openai") raised
    AuthError(code="provider_blocked") whenever the flag was set. A provider
    that is not installed/configured may legitimately raise
    AuthError("invalid_provider") -- what must never happen is the host-policy
    error, or any difference between the flag-on and flag-off outcomes.
    """
    from hermes_cli.auth import AuthError, resolve_provider

    def _outcome():
        try:
            return ("ok", resolve_provider("openai"))
        except AuthError as exc:
            return ("error", exc.code)

    monkeypatch.setenv("HERMES_CLIPROXY_ONLY", "1")
    with_flag = _outcome()
    assert resolve_provider("custom") == "custom"
    monkeypatch.delenv("HERMES_CLIPROXY_ONLY", raising=False)
    without_flag = _outcome()

    assert with_flag == without_flag
    assert with_flag != ("error", "provider_blocked")


def test_cliproxy_only_does_not_block_model_switch(monkeypatch):
    """Switching to a non-GLM model must behave identically with/without the flag.

    Pre-extraction switch_model() refused any model not starting with "glm-"
    under the flag. The guard compares the flag-on and flag-off results
    directly: the endpoint is deliberately unreachable (closed local port),
    so switch_model may legitimately report a reachability note -- what must
    never happen is the two calls differing because of the flag.
    """
    from hermes_cli.model_switch import switch_model

    def _switch():
        return switch_model(
            "gpt-5.5",
            current_provider="custom",
            current_model="glm-5.3",
            current_base_url="http://127.0.0.1:9/v1",
            current_api_key="dummy",
            explicit_provider="custom",
        )

    monkeypatch.setenv("HERMES_CLIPROXY_ONLY", "1")
    with_flag = _switch()
    monkeypatch.delenv("HERMES_CLIPROXY_ONLY", raising=False)
    without_flag = _switch()

    assert with_flag.success == without_flag.success
    assert with_flag.error_message == without_flag.error_message
    assert "HERMES_CLIPROXY_ONLY" not in (with_flag.error_message or "")
