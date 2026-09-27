"""Shared-URL credential isolation for custom providers (#124527).

A base_url is not an owner boundary: a bare ``provider: custom`` model and a named provider
may live on the same endpoint with different keys. Contracts asserted here:

* a named provider on a shared URL resolves with its own credential (``key_env``/``api_key``),
  never the main model's key seeded across by the URL-only pool match;
* a bare custom model with a configured key resolves with that key, never a same-URL
  provider's literal key riding the URL-only pool match back to it;
* a bare custom model on an openrouter.ai base_url uses the key configured beside its
  base_url instead of raising ``AuthError`` when no env key is set;
* a keyless same-URL sibling entry still shares the pool with the main model (#100413) —
  the shared-pool feature the seeding exists for.
"""

import json

import yaml


BASE = "https://openrouter.ai/api/v1"


def _home_with_config(tmp_path, monkeypatch, config):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "SECOND_KEY", "CUSTOM_BASE_URL",
                "OPENROUTER_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    (hermes_home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (hermes_home / "auth.json").write_text(
        json.dumps({"version": 1, "providers": {}, "credential_pool": {}}), encoding="utf-8"
    )
    return hermes_home


def _resolve(requested, **kwargs):
    from hermes_cli.runtime_provider import resolve_runtime_provider

    return resolve_runtime_provider(requested=requested, **kwargs)


def test_named_provider_on_shared_url_keeps_own_key(tmp_path, monkeypatch):
    """The main model's key must not be seeded into — and served by — the named sibling's pool."""
    _home_with_config(
        tmp_path, monkeypatch,
        {
            "model": {"default": "m", "provider": "custom", "base_url": BASE, "api_key": "main-key-1234"},
            "providers": {"second": {"name": "Second account", "base_url": BASE, "key_env": "SECOND_KEY"}},
        },
    )
    monkeypatch.setenv("SECOND_KEY", "second-key-1234")

    runtime = _resolve("second")

    assert runtime["api_key"] == "second-key-1234", (
        f"named provider must use its own credential, got {runtime['api_key']!r} "
        f"(source={runtime.get('source')!r})"
    )
    assert "main-key" not in str(runtime["api_key"])


def test_bare_custom_on_shared_url_keeps_configured_key(tmp_path, monkeypatch):
    """A sibling's literal key must not ride the URL-only pool match back to the main model."""
    _home_with_config(
        tmp_path, monkeypatch,
        {
            "model": {"default": "m", "provider": "custom", "base_url": BASE, "api_key": "main-key-1234"},
            "providers": {"second": {"name": "Second account", "base_url": BASE, "api_key": "second-key-1234"}},
        },
    )

    runtime = _resolve("custom")

    assert runtime["api_key"] == "main-key-1234", (
        f"bare custom must keep its configured key, got {runtime['api_key']!r} "
        f"(source={runtime.get('source')!r})"
    )


def test_openrouter_bare_custom_uses_configured_model_key(tmp_path, monkeypatch):
    """A trusted openrouter.ai base_url carries its own key rung before the env fallbacks."""
    _home_with_config(
        tmp_path, monkeypatch,
        {"model": {"default": "m", "provider": "custom", "base_url": BASE, "api_key": "main-key-1234"}},
    )

    runtime = _resolve("custom")

    assert runtime["api_key"] == "main-key-1234", (
        f"configured key must resolve without any env key, got {runtime['api_key']!r}"
    )


def test_keyless_sibling_still_shares_pool(tmp_path, monkeypatch):
    """#100413 contract: an entry with no credential of its own shares the main model's pool."""
    endpoint = "https://api.together.xyz/v1"
    _home_with_config(
        tmp_path, monkeypatch,
        {
            "model": {"default": "m", "provider": "custom", "base_url": endpoint, "api_key": "main-key-1234"},
            "providers": {"sib": {"name": "Sib", "base_url": endpoint}},
        },
    )

    runtime = _resolve("custom")

    assert runtime["api_key"] == "main-key-1234"
    assert str(runtime.get("source") or "").startswith("pool:"), (
        "keyless sibling entry must still be served through the shared pool"
    )
