"""Review-fork compression regressions moved to a package module (item 509).

``test_compression_concurrent_fork.py`` crossed the repo's FILE_LINES=2000
health cap; per ``scripts/code_health/config.py`` the sanctioned offset is a
package: moved code keeps its cap and its existing violations.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.agent.test_compression_concurrent_fork import _build_agent_with_db, _count_children
from tests.fixtures.storage_holder import raw_holder
from tests.fixtures.storage_read import transcript_rows
from tests.fixtures.storage_seed import seed_messages, seed_session
from tests.gateway.fixtures.storage_handles import storage_handle


def test_review_fork_compacts_oversized_snapshot_in_memory(tmp_path: Path) -> None:
    """An oversized review snapshot replays warm on the first request, then
    compacts in memory before further requests — without mutating the parent.

    Regression for #93057: the fork historically pinned ``compression_enabled =
    False`` because it shares the parent's session_id (issue #38727). That
    left the review's private snapshot unbounded — every follow-up request in
    the review tool loop replayed the whole snapshot (350k-384k input tokens
    per request in production). The fix detaches the fork's compressor from
    the parent's store/session_id and enables in-memory-only compaction.

    This test drives the REAL ``_run_review_in_thread`` + ``run_conversation``
    with a threshold-crossing snapshot across two provider requests and
    asserts:
      • the FIRST request replays the full snapshot untouched (warm
        prompt-cache parity) — no compaction summary, middle turns present;
      • compression actually fired before the SECOND request (a real
        threshold crossing, not just setup-time binding state), and that
        request carries the compaction summary and none of the middle
        snapshot turns;
      • the fork keeps the parent's session_id (prompt-cache parity) but its
        agent-level AND compressor-level session bindings are detached;
      • the parent's durable transcript, session row, and child-session graph
        are byte-for-byte unchanged after the compaction ran.
    """
    import agent.background_review as br

    parent_sid = "REVIEW_FORK_IN_MEMORY_COMPACTION_93057"

    db = storage_handle(tmp_path)
    seed_session(db, parent_sid, "discord")
    seed_messages(db, parent_sid, {"role": "user", "content": "durable parent turn"})
    durable_before = transcript_rows(db, parent_sid)
    with raw_holder(db)._read_ctx() as conn:
        session_row_before = tuple(
            conn.execute(
                "SELECT id, parent_session_id, ended_at, end_reason FROM sessions WHERE id = ?",
                (parent_sid,),
            ).fetchone()
        )
    parent = _build_agent_with_db(db, parent_sid)
    parent._cached_system_prompt = "stable parent prompt"

    snapshot = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"review turn {i} " + "x" * 200,
        }
        for i in range(24)
    ]

    captured = {}

    def _tool_response(prompt_tokens: int) -> SimpleNamespace:
        message = SimpleNamespace(
            content=None,
            reasoning_content=None,
            reasoning=None,
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    type="function",
                    function=SimpleNamespace(
                        name="web_search", arguments='{"query": "x"}'
                    ),
                )
            ],
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
            model="test/model",
            usage=SimpleNamespace(
                prompt_tokens=prompt_tokens,
                completion_tokens=1,
                total_tokens=prompt_tokens + 1,
            ),
        )

    def _final_response():
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    index=0,
                    message=SimpleNamespace(
                        role="assistant",
                        content="review complete",
                        tool_calls=None,
                        reasoning_content=None,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100, completion_tokens=10, total_tokens=110
            ),
            model="test/model",
        )

    # The worker does a local ``from run_agent import AIAgent``; patching the
    # class method covers that import path.
    from run_agent import AIAgent

    real_run_conversation = AIAgent.run_conversation

    def _run_threshold_crossing_review(self, *args, **kwargs):
        captured["compression_enabled"] = self.compression_enabled
        captured["compression_in_place"] = self.compression_in_place
        captured["session_id"] = self.session_id
        captured["session_db"] = self._session_db
        captured["input_budget"] = getattr(
            self, "_review_input_token_budget", "missing"
        )
        captured["defer_first_request"] = getattr(
            self, "_review_defer_compaction_before_first_response", "missing"
        )
        captured["compressor_session_db"] = getattr(
            self.context_compressor, "_session_db", "missing"
        )
        captured["compressor_session_id"] = getattr(
            self.context_compressor, "_session_id", "missing"
        )
        # Stub the fork's compressor so compaction output is deterministic
        # and no aux-LLM call happens; the trigger/commit paths stay real.
        self.context_compressor.threshold_tokens = 1
        self.context_compressor.protect_first_n = 1
        self.context_compressor.protect_last_n = 1
        self.context_compressor.compress = MagicMock(
            return_value=[
                {"role": "user", "content": "[CONTEXT COMPACTION] review summary"},
                {"role": "assistant", "content": "summary acknowledged"},
            ]
        )
        # Compress on the first pressure check after the first response, then
        # stand down so the compacted request proceeds instead of looping.
        _should_compress_calls = {"count": 0}

        def _should_compress(_tokens):
            _should_compress_calls["count"] += 1
            return _should_compress_calls["count"] == 1

        self.context_compressor.should_compress = MagicMock(
            side_effect=_should_compress
        )
        self.context_compressor.should_compress_info = MagicMock(
            return_value=(True, "over threshold")
        )
        self.context_compressor.should_compress_preflight = MagicMock(
            return_value=True
        )
        self.context_compressor.should_defer_preflight_to_real_usage = MagicMock(
            return_value=False
        )
        self.context_compressor.get_active_compression_failure_cooldown = MagicMock(
            return_value=None
        )
        self.context_compressor.select_context = MagicMock(return_value=None)
        self._compression_feasibility_checked = True
        self.client = MagicMock()
        self.client.chat.completions.create.side_effect = [
            _tool_response(100),
            _final_response(),
        ]
        self._disable_streaming = True
        self._use_prompt_caching = False

        def _fake_execute_tool_calls(assistant_message, messages, *_args):
            tool_call = assistant_message.tool_calls[0]
            messages.append(
                {
                    "role": "tool",
                    "name": tool_call.function.name,
                    "tool_call_id": tool_call.id,
                    "content": "ok",
                }
            )

        self._execute_tool_calls = _fake_execute_tool_calls

        result = real_run_conversation(self, *args, **kwargs)
        captured["compression_calls"] = self.context_compressor.compress.call_count
        create = self.client.chat.completions.create
        captured["create_calls"] = create.call_count
        captured["outbound"] = [
            call.kwargs.get("messages") for call in create.call_args_list
        ]
        return result

    try:
        with patch.object(AIAgent, "run_conversation", _run_threshold_crossing_review):
            br._run_review_in_thread(parent, snapshot, "review this conversation")

        assert captured["compression_calls"] >= 1, (
            "FIX REGRESSION: the review fork did not compact its oversized "
            "snapshot. compression_enabled was historically set False on the "
            "fork, which removed the only bound on the replayed snapshot "
            "(issue #93057)."
        )
        assert captured["create_calls"] == 2, (
            f"expected a 2-request review (tool call + final), "
            f"got {captured['create_calls']}"
        )
        first_outbound, second_outbound = captured["outbound"]
        first_contents = [str(m.get("content", "")) for m in first_outbound]
        second_contents = [str(m.get("content", "")) for m in second_outbound]
        # Warm-cache parity: the first request replays the full snapshot
        # untouched — middle turns present, no compaction summary yet.
        assert any("review turn 12" in text for text in first_contents), (
            "the review fork's FIRST request must replay the full snapshot "
            "(warm prompt-cache read) — compaction must not rewrite it before "
            "the first provider call"
        )
        assert not any(
            "[CONTEXT COMPACTION]" in text for text in first_contents
        ), f"first request was compacted prematurely: {first_contents!r}"
        # The SECOND request carries the compaction summary and none of the
        # middle snapshot turns.
        assert any(
            "[CONTEXT COMPACTION] review summary" in text
            for text in second_contents
        ), f"outbound request did not contain the compaction summary: {second_contents!r}"
        assert not any("review turn 12" in text for text in second_contents), (
            "outbound request still replays the middle of the snapshot — "
            "the review replayed an unbounded transcript despite compaction"
        )
        assert captured["session_id"] == parent_sid, (
            "Review fork should inherit the parent's session_id for "
            "prompt-cache parity."
        )
        assert captured["session_db"] is None, (
            "Review fork must keep its agent-level store detached "
            "(_session_db=None) so compaction can never persist."
        )
        assert captured["compressor_session_db"] is None, (
            "Review fork's compressor must be detached from the parent "
            "store, otherwise durable cooldown/streak writes land on "
            "the parent's row (issue #93057)."
        )
        assert captured["compressor_session_id"] == ""
        assert captured["compression_enabled"] is True
        assert captured["compression_in_place"] is True
        assert captured["defer_first_request"] is True
        assert isinstance(captured["input_budget"], int) and captured["input_budget"] > 0

        # Parent session must be byte-for-byte unchanged after the review
        # compacted its private snapshot.
        assert parent.session_id == parent_sid
        assert transcript_rows(db, parent_sid) == durable_before
        with raw_holder(db)._read_ctx() as conn:
            session_row_after = tuple(
                conn.execute(
                    "SELECT id, parent_session_id, ended_at, end_reason FROM sessions WHERE id = ?",
                    (parent_sid,),
                ).fetchone()
            )
        assert session_row_after == session_row_before
        assert _count_children(db, parent_sid) == 0
    finally:
        db.close()

def test_review_fork_fails_closed_when_compressor_rebind_raises(
    tmp_path: Path,
) -> None:
    """A failed compressor detachment must keep the fork's compression OFF.

    Regression for the #93057 adversarial review: if ``bind_session_state``
    cannot sever the engine's binding to the parent's store/session_id,
    enabling compression would run it against the parent's live session
    binding — durable cooldown/streak/ineffective-count writes on the
    parent's row and the sibling-session race behind #38727 re-opened. The
    fork must fail CLOSED: keep the historical ``compression_enabled = False``
    behavior. The review still runs (the iteration cap and the
    aggregate input budget still bound it).
    """
    import agent.background_review as br
    from agent.context_compressor import ContextCompressor

    parent_sid = "REVIEW_FORK_REBIND_FAIL_CLOSED_93057"

    db = storage_handle(tmp_path)
    seed_session(db, parent_sid, "discord")
    parent = _build_agent_with_db(db, parent_sid)
    parent._cached_system_prompt = "stable parent prompt"

    snapshot = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"review turn {i}",
        }
        for i in range(8)
    ]

    captured = {}

    def _capture_fork_flags(self, *args, **kwargs):
        captured["compression_enabled"] = self.compression_enabled
        captured["compression_in_place"] = self.compression_in_place
        captured["input_budget"] = getattr(
            self, "_review_input_token_budget", "missing"
        )
        return {
            "completed": True,
            "final_response": "review complete",
            "api_call_count": 0,
        }

    # The worker does a local ``from run_agent import AIAgent``; patching the
    # class method covers that import path.
    from run_agent import AIAgent

    _real_bind = ContextCompressor.bind_session_state

    def _failing_bind(self, session_db=None, session_id=""):
        # Only the detachment rebind may fail; any other binding passes
        # through so the fork's construction path stays intact.
        if session_db is None:
            raise RuntimeError("detachment boom")
        return _real_bind(self, session_db, session_id)

    try:
        with (
            patch.object(AIAgent, "run_conversation", _capture_fork_flags),
            patch.object(
                ContextCompressor, "bind_session_state", _failing_bind
            ),
        ):
            br._run_review_in_thread(parent, snapshot, "review this conversation")

        assert captured["compression_enabled"] is False, (
            "FIX REGRESSION: a failed compressor rebind must leave "
            "compression_enabled False on the review fork (fail-closed). "
            "Enabling compression with the engine still bound to the "
            "parent's session re-opens the #38727 race (issue #93057)."
        )
        assert (
            isinstance(captured["input_budget"], int) and captured["input_budget"] > 0
        ), (
            "the aggregate input budget must still be armed on the fail-closed "
            "path — it bounds the review even when compaction stays off"
        )
    finally:
        db.close()

# ── Lease-refresher bounded-failure tolerance (salvage follow-up, #54465) ────
# A single falsy refresh (transient DB blip) must NOT permanently kill the
# lease — only a *persistent* failure (genuine lost-ownership) should stop the
# refresher after a bounded number of consecutive failures. Without this, one
# escaped lock-contention error silently reintroduces the TTL-expiry wedge the
# PR set out to fix.
