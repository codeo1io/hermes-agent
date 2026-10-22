"""Approval detection: shell variable indirection must not mask hardline commands.

Assignments in earlier top-level segments expand into later command words before
pattern matching, so ``X=rm; "$X" -rf /`` reads as its expansion and the approval
gate prompts exactly as it would for the direct spelling. Quoted prose stays data:
an unrelated assignment never changes a verdict, and ``echo "$X"`` of a
dangerous-looking *value* keeps the direct-spelling verdict (no new prompt class).
"""

import pytest

from tools.approval_detection import detect_dangerous_command, detect_hardline_command

# (command, expected dangerous pattern key, expected hardline description-or-None).
# Every case mirrors the verdict of the direct spelling at HEAD df1be2b908:
#   rm -rf /            -> ("delete in root path", "recursive delete of root filesystem")
#   find . -delete      -> ("find -delete", None)
#   find . -exec rm {} ;-> ("find -exec/-execdir rm", None)
#   chmod -R 777 /      -> ("world/other-writable permissions", None)
INDIRECT_DESTRUCTIVE = [
    ("X=rm; \"$X\" -rf /", "delete in root path", "recursive delete of root filesystem"),
    ("X=rm; $X -rf /", "delete in root path", "recursive delete of root filesystem"),
    ("X=rm; ${X} -rf /", "delete in root path", "recursive delete of root filesystem"),
    ("X=rm && \"$X\" -rf /", "delete in root path", "recursive delete of root filesystem"),
    ("A=rm; B=-rf; \"$A\" \"$B\" /", "delete in root path", "recursive delete of root filesystem"),
    ("F=-delete; find . $F", "find -delete", None),
    ("E=exec; find . -$E rm {} \\;", "find -exec/-execdir rm", None),
    ("P=chmod; Q=-R; \"$P\" \"$Q\" 777 /", "world/other-writable permissions", None),
    ("export X=rm; \"$X\" -rf /", "delete in root path", "recursive delete of root filesystem"),
]


@pytest.mark.parametrize("command,expected_pattern,expected_hardline", INDIRECT_DESTRUCTIVE)
def test_indirection_prompts_like_the_direct_spelling(command, expected_pattern, expected_hardline):
    dangerous, pattern, _ = detect_dangerous_command(command)
    assert dangerous, f"variable indirection bypassed the approval gate: {command!r}"
    assert pattern == expected_pattern
    hardline, hardline_description = detect_hardline_command(command)
    assert hardline is (expected_hardline is not None)
    if expected_hardline is not None:
        assert hardline_description == expected_hardline


BENIGN_ASSIGNMENTS = [
    "X=rm",  # a bare assignment runs nothing
    "X=rm; echo \"$X\"",  # echoing a value is not executing it
    "X=echo; \"$X\" hello world",
    "X=ls -la; \"$X\" .",
    "NAME=Hermes; echo \"hello $NAME\"",
    "ls $HOME",
    "X=rm; echo '$X'",  # single quotes suppress expansion in a real shell
]
# NOTE: ``X=rm "$X" -rf /`` (same-segment prefix assignment) already prompts via the
# flags-after-operands rule — kept out of the benign list on purpose.


@pytest.mark.parametrize("command", BENIGN_ASSIGNMENTS)
def test_benign_assignments_stay_clean(command):
    dangerous, _, _ = detect_dangerous_command(command)
    hardline, _ = detect_hardline_command(command)
    assert not dangerous, f"false positive on benign assignment shape: {command!r}"
    assert not hardline


@pytest.mark.parametrize(
    "prefix",
    ["", "X=ls; ", "FLAG=--quiet && "],
)
def test_unrelated_assignment_never_changes_a_verdict(prefix):
    """Prose and normal commands must keep byte-identical verdicts alongside assignments."""
    for command in ('git commit -m "rm -rf /"', "find . -name '*.log' -delete", "echo hi"):
        assert detect_dangerous_command(prefix + command) == detect_dangerous_command(command)
        assert detect_hardline_command(prefix + command) == detect_hardline_command(command)


def test_dangerous_value_echoed_keeps_direct_spelling_verdict():
    """``echo "$X"`` of a destructive-looking value equals the verdict of ``echo "rm -rf /"``."""
    direct = detect_dangerous_command('X=rm -rf /; echo "$X"')
    assert direct == detect_dangerous_command('echo "rm -rf /"')
    assert detect_hardline_command('X=rm -rf /; echo "$X"') == detect_hardline_command('echo "rm -rf /"')
