"""transform_tool_result fires exactly once per tool call on every dispatch path.

Regression (adoption of upstream #275 into run a8d584606572): #275 restored the
inline ``apply_transform_tool_result`` call inside
``agent_runtime_helpers.invoke_tool``'s inline ``_execute`` (the "transform
exactly-once" upstream contract). The concurrent batch path still carried a
second application in ``tool_executor._append_batch_results`` — compensation
for the pre-#275 gap where the inline ``_execute`` returned the raw result —
so every inline-table tool dispatched inside a parallel batch
(``session_search``, ``todo_list``, ``memory``, ``delegate_task``,
``delegate_session``, memory-provider tools, ...) had plugin
``transform_tool_result`` hooks applied to its result TWICE: double-wrapped
formatting, double-counted metrics.

The contract under test: one hook application per tool call on both the
concurrent and the sequential path, and the committed tool message carries the
once-transformed payload.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


def _tc(name, arguments="{}", call_id=None):
    return SimpleNamespace(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _make_tool_defs(*names: str) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": f"{n} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for n in names
    ]


@pytest.fixture()
def agent():
    with (
        patch(
            "model_tools.get_tool_definitions",
            return_value=_make_tool_defs("session_search"),
        ),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI"),
    ):
        a = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        a.client = MagicMock()
        return a


class TestTransformToolResultExactlyOnce:
    def _install_probe(self):
        """Replace the session_search inline executor and the model_tools transform
        hook; return (runs, applications) collectors."""

        def fake_inline_executor(agent, args, ctx):
            return json.dumps({"hits": args.get("query")})

        applications = []

        def counting_transform(function_name, function_args, result, duration_ms, ids):
            applications.append(function_name)
            return f"T<{result}>"

        return fake_inline_executor, applications, counting_transform

    def test_concurrent_inline_tool_result_is_transformed_once(self, agent):
        """Two parallel-safe session_search calls ride the concurrent batch path;
        the hook must see each call exactly once and never double-wrap."""
        executor, applications, counting_transform = self._install_probe()
        calls = [
            _tc("session_search", '{"query":"a"}', call_id="s1"),
            _tc("session_search", '{"query":"b"}', call_id="s2"),
        ]
        msg = SimpleNamespace(content="", tool_calls=calls)
        messages = []

        with (
            patch.dict(
                "agent.inline_tool_executors.INLINE_TOOL_EXECUTORS",
                {"session_search": executor},
            ),
            patch(
                "model_tools._apply_transform_tool_result_hook",
                side_effect=counting_transform,
            ),
        ):
            agent._execute_tool_calls(msg, messages, "task-1")

        # Both calls dispatched and one result per call, in emission order.
        assert [m["tool_call_id"] for m in messages] == ["s1", "s2"]
        assert all(m["role"] == "tool" for m in messages)
        # Exactly one transform application per tool call — not two.
        assert applications.count("session_search") == 2, applications
        # The committed payload is wrapped exactly once, never T<T<...>>.
        for m in messages:
            assert m["content"].startswith("T<"), m["content"][:80]
            assert "T<T<" not in m["content"], m["content"][:80]

    def test_sequential_inline_tool_result_is_transformed_once(self, agent):
        """A single call rides the sequential path; same exactly-once contract."""
        executor, applications, counting_transform = self._install_probe()
        msg = SimpleNamespace(
            content="", tool_calls=[_tc("session_search", '{"query":"a"}', call_id="q1")]
        )
        messages = []

        with (
            patch.dict(
                "agent.inline_tool_executors.INLINE_TOOL_EXECUTORS",
                {"session_search": executor},
            ),
            patch(
                "model_tools._apply_transform_tool_result_hook",
                side_effect=counting_transform,
            ),
        ):
            agent._execute_tool_calls(msg, messages, "task-1")

        assert [m["tool_call_id"] for m in messages] == ["q1"]
        assert applications.count("session_search") == 1, applications
        assert messages[0]["content"].startswith("T<"), messages[0]["content"][:80]
        assert "T<T<" not in messages[0]["content"], messages[0]["content"][:80]
