"""The CI workflow gate replay must implement GitHub Actions startsWith()."""
import pytest

from tests.ci._gha_expr import Unsupported, evaluate


@pytest.mark.parametrize(("value", "prefix", "expected"), [
    ("conductor/ci-23", "conductor/ci-", True),
    ("CONDUCTOR/CI-23", "conductor/ci-", True),
    ("feature/ci-23", "conductor/ci-", False),
    (None, "conductor/ci-", False),
    ("Conductor CI validation #25", "Conductor CI validation", True),
])
def test_actions_startswith(value, prefix, expected):
    assert evaluate("startsWith(github.head_ref, 'conductor/ci-')", {
        "github": {"head_ref": value}
    }) is (str(value or "").lower().startswith("conductor/ci-"))
    assert evaluate("startsWith(github.head_ref, github.prefix)", {
        "github": {"head_ref": value, "prefix": prefix}
    }) is expected


def test_actions_startswith_rejects_unsupported_arity():
    with pytest.raises(Unsupported):
        evaluate("startsWith('a')", {})
