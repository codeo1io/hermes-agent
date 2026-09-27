"""Truncated-tool-call retry must actually raise the output cap (#72770).

Contracts:
  * When ``max_tokens`` is unset, the retry boost ladders from the budget the
    request actually used (``_requested_output_cap_from_api_kwargs``), not a
    hardcoded 4096 — a long tool call made against a 200k request cap must not
    retry at 4×4096.
  * The ceiling is 2× the requested cap: a request already at the cap used to
    get ``min(boost, max(32768, cap)) == cap`` — the same request re-sent
    unchanged, guaranteeing another truncation.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.turn_truncation import _Trunc, _retry_truncated_tool_call


def _agent(max_tokens, requested_cap):
    agent = MagicMock()
    agent.max_tokens = max_tokens
    agent._requested_output_cap_from_api_kwargs = lambda kwargs: requested_cap
    return agent


def _st(agent, retries=0):
    return _Trunc(
        agent=agent,
        response=SimpleNamespace(),
        finish_reason="length",
        conversation_history=None,
        api_call_count=0,
        effective_task_id=None,
        current_turn_user_idx=0,
        messages=[],
        length_continue_retries=0,
        truncated_response_parts=[],
        truncated_tool_call_retries=retries,
        retry_count=0,
        compression_attempts=0,
    )


class TestBoostLaddersFromRequestedCap:
    def test_unset_max_tokens_ladders_from_requested_cap(self):
        agent = _agent(max_tokens=None, requested_cap=200_000)
        verdict = _retry_truncated_tool_call(_st(agent), api_kwargs={})
        assert verdict.action == "continue"
        # first retry: 2^1 × the 200k budget actually in use
        assert agent._ephemeral_max_output_tokens == 400_000

    def test_ceiling_is_double_the_requested_cap(self):
        """A cap at the requested budget must not bound the retry to the same size."""
        agent = _agent(max_tokens=None, requested_cap=65_536)
        _retry_truncated_tool_call(_st(agent), api_kwargs={})
        first = agent._ephemeral_max_output_tokens
        # ladder climbs on subsequent retries and stays capped at 2× the cap
        _retry_truncated_tool_call(_st(agent, retries=1), api_kwargs={})
        _retry_truncated_tool_call(_st(agent, retries=2), api_kwargs={})
        last = agent._ephemeral_max_output_tokens
        assert first == 131_072  # min(2×65536, max(32768, 2×65536))
        assert last == 131_072
        # the invariant: a retried request always asks for strictly more than
        # the cap that just truncated
        assert last > 65_536

    def test_explicit_max_tokens_still_ladders(self):
        agent = _agent(max_tokens=8_192, requested_cap=None)
        _retry_truncated_tool_call(_st(agent), api_kwargs={})
        assert agent._ephemeral_max_output_tokens == 16_384
