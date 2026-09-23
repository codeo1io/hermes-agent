"""Release-line source-consistency smoke guard (fix-queue item 80).

The 2026-09-21 fork-main port left SOURCE files reverted while the callers
that import from them stayed on the new API, killing conversation turns at
import time. Collection-time CI never saw it because every broken import is
FUNCTION-LOCAL (resolved at call time, not collection time). This guard
resolves every function-local import made by the ported call sites at test
time, so an over-reverted source file fails CI instead of production.
"""

import ast
import importlib
import inspect
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Call sites whose function-local imports were broken by the over-revert,
# plus the libraries they import from.
GUARDED_MODULES = [
    "agent/conversation_loop.py",
    "agent/agent_init.py",
    "agent/auxiliary_client.py",
    "agent/client_lifecycle.py",
    "agent/anthropic_adapter.py",
    "agent/agent_runtime_helpers.py",
    "tools/vision_tools.py",
    "tools/browser_tool_vision.py",
    "tools/browser_use_cli.py",
]

# Imports of these library modules are the ones the release line owns.
GUARDED_IMPORT_ROOTS = ("tools.vision_tools_history_budget", "agent.anthropic_credentials")


def _function_local_import_froms(rel_path):
    """Yield (module_name, [imported names]) for every nested ImportFrom."""
    tree = ast.parse((ROOT / rel_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.col_offset > 0:
            yield node.module, [alias.name for alias in node.names]


def test_every_ported_function_local_import_resolves():
    checked = 0
    for rel_path in GUARDED_MODULES:
        for module_name, names in _function_local_import_froms(rel_path):
            if not module_name.startswith(GUARDED_IMPORT_ROOTS):
                continue
            target = importlib.import_module(module_name)
            for name in names:
                assert hasattr(target, name), (
                    f"{rel_path} does `from {module_name} import {name}` at call "
                    f"time, but {module_name} does not define it — conversation "
                    "turns will crash with ImportError"
                )
                checked += 1
    assert checked >= 6, f"guard degenerate: only {checked} imports checked"


def test_conversation_loop_imports_at_module_scope():
    """The exact import that killed driver fires 23:06Z/23:52Z/00:24Z.

    Fork note (rm-020 port, 2026-09-23): origin-main's restore carries the richer
    embed-lifecycle budget (``native_turn_images`` + record/release/refusal caps);
    this line keeps its own fork budget (cycle-1 rm-007, "vision budget") whose
    only public surface is ``resolve_embed_target_bytes``. Guard what THIS line's
    callers import, not origin's.
    """
    from tools.vision_tools_history_budget import resolve_embed_target_bytes

    assert callable(resolve_embed_target_bytes)


def test_vision_history_budget_api_surface():
    import tools.vision_tools_history_budget as budget

    for name in (
        "resolve_embed_target_bytes",
    ):
        assert callable(getattr(budget, name)), f"vision history budget lost {name}"


def test_anthropic_credentials_api_surface():
    import agent.anthropic_credentials as credentials

    assert callable(credentials.anthropic_route_is_oauth), (
        "anthropic_route_is_oauth missing — agent_init, auxiliary_client, "
        "client_lifecycle, anthropic_adapter and agent_runtime_helpers all "
        "import it function-locally"
    )
    signature = inspect.signature(credentials.resolve_anthropic_token)
    assert "model" in signature.parameters, (
        "resolve_anthropic_token lost the model-aware signature that "
        "agent_init._init_anthropic_client calls"
    )
    assert signature.parameters["model"].default is None
    # The legacy no-argument call shape must keep working.
    assert callable(credentials.resolve_anthropic_token)


def test_anthropic_route_classifier_semantics():
    from agent.anthropic_credentials import anthropic_route_is_oauth

    sentinel = "sk-ant-oat-marker"
    assert anthropic_route_is_oauth("https://api.anthropic.com", sentinel, provider="anthropic") is True
    assert anthropic_route_is_oauth("", sentinel, provider="anthropic") is True
    # Third-party Anthropic-protocol endpoints never qualify (#1739).
    assert anthropic_route_is_oauth("https://example.invalid/v1", sentinel, provider="custom") is False
    # Callable credential materializes once.
    assert anthropic_route_is_oauth("https://api.anthropic.com", lambda: sentinel, provider="anthropic") is True
    assert anthropic_route_is_oauth("https://api.anthropic.com", lambda: (_ for _ in ()).throw(RuntimeError()), provider="anthropic") is False
