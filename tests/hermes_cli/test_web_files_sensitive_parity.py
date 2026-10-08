"""Contract: the managed-files sensitive-path predicate mirrors the canonical
credential guards so the dashboard Files tab never serves what the agent's own
file tools refuse for the same tree (#57505 exfil surface; cycle-3 parity gap
between ``hermes_cli/web_routers/files.py`` and the guards it claims to mirror).

The corpus is DERIVED at test time by calling the canonical guards / reading
their live tables — ``agent.file_safety`` (read denies + write denies) and the
gateway media-exfil superset ``gateway.platforms.base._ROOT_CREDENTIAL_PATHS``.
When a canonical table grows, this contract goes red until the files-router
predicate catches up; no frozen path list (change-detector shape is rejected by
house rules).
"""

from pathlib import Path

import pytest

from agent import file_safety
from hermes_cli.web_routers.files import _is_sensitive_path

# The register's 10-path acceptance corpus: the exact paths the live probe
# showed the old predicate missing (red-first receipt in the cycle-3 artifacts)
# plus the already-blocked ones, so both directions stay pinned.
REGISTER_PROBE_CORPUS = (
    ".ssh/authorized_keys",
    ".gnupg/pubring.kbx",
    ".kube/config",
    ".netrc",
    "vault/secrets.kdbx",
    "browser-profile/Default/Cookies",
    ".aws/credentials",
    "auth.json",
    ".env",
    "sessions/2026-10-08T00-00-00.jsonl",
)

# Ordinary user files that no canonical guard blocks — the Files tab must keep
# serving them (parity cuts both ways). No near-miss secrets here by design:
# the .env.<suffix> superset (e.g. ``.env.example``) is a deliberate
# files-router tightening over canonical, not a parity violation.
ORDINARY_PATHS = (
    "readme.md",
    "notes.txt",
    "src/main.py",
    "images/photo.png",
    "data/dump.csv",
)


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_register_probe_corpus_blocked():
    root = Path("/tmp/probe-root")
    for rel in REGISTER_PROBE_CORPUS:
        assert _is_sensitive_path(root / rel), f"register corpus path must be blocked: {rel}"


def test_read_denial_corpus_blocked(hermes_home):
    """Every path the canonical READ guard blocks, the files router must block
    too. Corpus = credential filenames + read-denied directory trees + the
    project-local .env variants, each self-checked against
    ``file_safety.get_read_block_error`` first so the corpus can never contain
    a path canonical actually allows."""
    corpus = [hermes_home / name for name in file_safety._CREDENTIAL_FILE_NAMES]
    for subdir, _docmatch, _filematch in file_safety._READ_DENIED_DIRS:
        corpus += [hermes_home / subdir, hermes_home / subdir / "x.bin"]
    corpus += [
        hermes_home / "project" / name
        for name in file_safety._BLOCKED_PROJECT_ENV_BASENAMES
    ]
    for path in corpus:
        assert file_safety.get_read_block_error(str(path)) is not None, (
            f"corpus self-check failed: canonical read guard does NOT block {path}"
        )
        assert _is_sensitive_path(path), f"files router must block what canonical blocks: {path}"


def test_write_denial_corpus_blocked(tmp_path, monkeypatch):
    """The write guard's home-anchored credential surface (.ssh keys, .netrc/
    .pgpass/.npmrc/.pypirc, .ssh/.aws/.gnupg/.kube trees, ...) is credential
    material the browser must not serve either. Corpus = the guard's own
    output. Absolute system paths (/etc/*) are excluded: they live outside any
    managed root, and the router already confines reads to the root."""
    home = tmp_path / "usrhome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    real_home = Path(home).resolve()

    for denied in file_safety.build_write_denied_paths(str(home)):
        path = Path(denied)
        if real_home not in path.parents:
            continue  # /etc/* system denies + ambient roots outside this corpus
        assert _is_sensitive_path(path), f"write-denied credential path must be blocked: {path}"

    for prefix in file_safety.build_write_denied_prefixes(str(home)):
        p = Path(prefix)
        if real_home not in p.parents:
            continue
        deep = p / "deeper" / "id_ecdsa"
        assert _is_sensitive_path(deep), f"write-denied tree must be blocked whole: {prefix}"


def test_gateway_root_credential_paths_blocked(hermes_home):
    """The gateway media-delivery exfil superset (the table the files router's
    original comment named as its mirror) must be fully blocked: state stores,
    transcripts, tokens, and pairing material are exactly what a browsable
    HERMES_HOME would leak."""
    from gateway.platforms.base import _ROOT_CREDENTIAL_PATHS

    assert len(_ROOT_CREDENTIAL_PATHS) > 10, "corpus self-check: superset table is non-trivial"
    for rel in _ROOT_CREDENTIAL_PATHS:
        assert _is_sensitive_path(hermes_home / rel), (
            f"gateway exfil-superset member must be blocked: {rel}"
        )


def test_protected_subpaths_corpus_blocked(hermes_home):
    """_HERMES_PROTECTED_SUBPATHS (state.db, sessions, mcp-tokens, pairing,
    vault, browser-profile) is the write-side protected-surface table; every
    entry is transcript/token material the browser must refuse wherever it
    sits under the managed root."""
    for name in file_safety._HERMES_PROTECTED_SUBPATHS:
        assert _is_sensitive_path(hermes_home / name), f"protected subpath must be blocked: {name}"
        nested = hermes_home / "sub" / name / "child"
        assert _is_sensitive_path(nested), f"protected subpath must block nested: {name}"


def test_ordinary_paths_stay_readable(hermes_home):
    """Parity in the other direction: nothing outside the canonical credential
    classes may be hidden from the Files tab (self-checked against the read
    guard so the negatives are real negatives)."""
    for rel in ORDINARY_PATHS:
        path = hermes_home / rel
        assert file_safety.get_read_block_error(str(path)) is None, (
            f"negative self-check failed: canonical read guard DOES block {path}"
        )
        assert not _is_sensitive_path(path), f"ordinary path must stay readable: {rel}"
