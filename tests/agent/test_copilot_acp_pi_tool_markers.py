"""[pi-tool] marker parsing — the ACP delegate tool-activity contract.

The pi-acp bridge surfaces each tool execution that runs INSIDE the
delegate's own runtime as thought-chunk markers (``[pi-tool] name {args}``
start, ``[pi-tool:ok|FAILED] name -> result N bytes`` end). They ride the
assistant message's reasoning field into hermes, where
``conversation_loop`` turns them into tool.started/tool.completed progress
events and ``delegate_tool`` derives ``tool_trace`` entries. These tests
pin the parsing contract those consumers rely on.
"""

import pytest

from agent.copilot_acp_client import parse_pi_result_footer, parse_pi_tool_markers


def test_parses_start_end_pair():
    text = (
        "thinking about it\n"
        '[pi-tool] aft_outline {"target": "/tmp/x.py"}\n'
        "[pi-tool:ok] aft_outline -> result 586 bytes\n"
        "more thinking\n"
    )
    assert parse_pi_tool_markers(text) == [
        {
            "name": "aft_outline",
            "args": '{"target": "/tmp/x.py"}',
            "status": "ok",
            "result_bytes": 586,
        }
    ]


def test_failed_status_and_end_without_start():
    text = (
        '[pi-tool] bash {"cmd": "ls"}\n'
        "[pi-tool:FAILED] bash -> result 12 bytes\n"
        "[pi-tool:ok] read -> result 40 bytes\n"
    )
    events = parse_pi_tool_markers(text)
    assert [e["name"] for e in events] == ["bash", "read"]
    assert [e["status"] for e in events] == ["FAILED", "ok"]
    assert events[0]["result_bytes"] == 12
    # An end marker with no matching start still yields an entry, with no args.
    assert events[1]["args"] == ""


def test_repeated_calls_to_same_tool_pair_fifo():
    text = (
        "[pi-tool] read a\n"
        "[pi-tool] read b\n"
        "[pi-tool:ok] read -> result 1 bytes\n"
        "[pi-tool:ok] read -> result 2 bytes\n"
    )
    events = parse_pi_tool_markers(text)
    assert [(e["args"], e["result_bytes"]) for e in events] == [("a", 1), ("b", 2)]


def test_start_without_end_kept_open():
    text = '[pi-tool] grep {"pattern": "x"}\n'
    assert parse_pi_tool_markers(text) == [
        {"name": "grep", "args": '{"pattern": "x"}', "status": "", "result_bytes": None}
    ]


def test_plain_thinking_yields_nothing():
    assert parse_pi_tool_markers("just model thinking, no markers") == []
    assert parse_pi_tool_markers("") == []
    assert parse_pi_tool_markers(None) == []


@pytest.mark.parametrize(
    "end_line,status,size",
    [
        ("[pi-tool:ok] edit -> result 586 bytes", "ok", 586),
        ("[pi-tool:FAILED] edit -> result 0 bytes", "FAILED", 0),
        # Bridge truncates long lines at 400 chars; a cut-off tail must not
        # break the size parse (falls back to None), only the status is kept.
        ("[pi-tool:ok] edit -> result 1", "ok", None),
    ],
)
def test_end_marker_variants(end_line, status, size):
    text = "[pi-tool] edit {}\n" + end_line
    events = parse_pi_tool_markers(text)
    assert len(events) == 1
    assert events[0]["status"] == status
    assert events[0]["result_bytes"] == size


# -- pi-delegation-result footer parsing ---------------------------------
#
# The pi-acp bridge appends this fenced JSON block to the delegate's final
# response text after every run. delegate_tool extracts touched_files from
# the last one to give the parent an objective change record.


def test_footer_parses_full_contract():
    text = (
        "I edited base.py and added added.py.\n"
        "\n```pi-delegation-result\n"
        '{"status": "end_turn", "duration_s": 62.4, "git_repo": true, '
        '"touched_files": [" M base.py", "?? added.py"]}\n'
        "```\n"
    )
    assert parse_pi_result_footer(text) == {
        "status": "end_turn",
        "duration_s": 62.4,
        "git_repo": True,
        "touched_files": [" M base.py", "?? added.py"],
    }


def test_footer_absent_or_empty():
    assert parse_pi_result_footer("plain final report, no footer") is None
    assert parse_pi_result_footer("") is None
    assert parse_pi_result_footer(None) is None
    # A different fence label must not match.
    assert parse_pi_result_footer("```json\n{}\n```") is None


def test_footer_malformed_json_returns_none():
    text = "```pi-delegation-result\n{not json]\n```"
    assert parse_pi_result_footer(text) is None
    # Non-dict payload also rejected.
    assert parse_pi_result_footer("```pi-delegation-result\n[1, 2]\n```") is None


def test_footer_last_block_wins():
    first = '"status": "end_turn", "touched_files": ["?? old.txt"]'
    second = '"status": "end_turn", "touched_files": [" M new.py"]'
    text = (
        "```pi-delegation-result\n{" + first + "}\n```\n"
        "interim prose\n"
        "```pi-delegation-result\n{" + second + "}\n```\n"
    )
    footer = parse_pi_result_footer(text)
    assert footer is not None
    assert footer["touched_files"] == [" M new.py"]
