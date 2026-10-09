"""Managed Node zip staging integrity: SHASUMS-verified, zip-slip-safe extraction.

Regression for the cycle-2 assess finding (hermes_constants.py:596-632): the
portable Node zip was fetched over HTTPS and extracted with a bare
``extractall`` — no SHASUMS verification, no member vetting — so a compromised
mirror (or a MITM on the fetch) could plant bytes that the next heal swaps into
``~/.hermes/node``. The fix verifies the zip against nodejs.org's SHASUMS.txt
from the same pinned dist root, then extracts via
``hermes_cli.update_cmd_zip._extract_zip_safely`` (zip-slip + symlink
rejection).
"""

import hashlib
import io
import zipfile

import hermes_constants as hc

NODE_MAJOR = hc._HERMES_NODE_TARGET_MAJOR
ZIP_NAME = f"node-v{NODE_MAJOR}.9.9-win-x64.zip"
TOP_DIR = f"node-v{NODE_MAJOR}.9.9-win-x64/"


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _stage_with(zip_bytes: bytes, sums_bytes: bytes, tmp_path, monkeypatch):
    """Drive ``_stage_windows_node_zip`` with a fully faked dist root.

    Stages into a dedicated home subdir: the conftest isolation fixture also
    writes into ``tmp_path`` (HERMES_HOME), so the parent is not a clean stage.
    """
    home = tmp_path / "home"
    home.mkdir()

    def _fake_fetch(url, timeout):  # noqa: ARG001
        if url.endswith("SHASUMS.txt"):
            return sums_bytes
        if url.endswith(".zip"):
            return zip_bytes
        return f'<a href="{ZIP_NAME}">zip</a>'.encode()

    monkeypatch.setattr(hc, "_fetch_url", _fake_fetch)
    return hc._stage_windows_node_zip(home, "x64"), home


def _home_entries(home):
    return [p.name for p in home.iterdir()]


def test_stage_verifies_sums_and_stages_tree(tmp_path, monkeypatch):
    """Happy path: a zip matching its SHASUMS entry stages a node tree under node.new-*."""
    good = _make_zip({TOP_DIR + "node.exe": b"NODE"})
    staged, home = _stage_with(good, f"{hashlib.sha256(good).hexdigest()}  {ZIP_NAME}\n".encode(),
                              tmp_path, monkeypatch)

    assert staged is not None and staged.is_dir()
    assert (staged / "node.exe").read_bytes() == b"NODE"
    assert staged.name.startswith("node.new-")
    assert _home_entries(home) == [staged.name], "no scratch left beside the staged tree"


def test_stage_rejects_sha256_mismatch(tmp_path, monkeypatch):
    """A zip whose bytes do not match the SHASUMS digest is refused, nothing staged."""
    tampered = _make_zip({TOP_DIR + "node.exe": b"EVIL"})
    wrong_sums = ("0" * 64 + f"  {ZIP_NAME}\n").encode()

    staged, home = _stage_with(tampered, wrong_sums, tmp_path, monkeypatch)
    assert staged is None
    assert _home_entries(home) == []


def test_stage_rejects_missing_sums_entry(tmp_path, monkeypatch):
    """Fail closed: a SHASUMS.txt that does not mention our zip refuses the stage."""
    good = _make_zip({TOP_DIR + "node.exe": b"NODE"})
    other_only = ("0" * 64 + "  node-v0.0.1-win-x64.zip\n").encode()

    staged, home = _stage_with(good, other_only, tmp_path, monkeypatch)
    assert staged is None
    assert _home_entries(home) == []


def test_stage_refuses_unfetchable_sums(tmp_path, monkeypatch):
    """A SHASUMS fetch failure fails closed too (None verdict, nothing staged)."""
    good = _make_zip({TOP_DIR + "node.exe": b"NODE"})

    def _fake_fetch(url, timeout):  # noqa: ARG001
        if url.endswith("SHASUMS.txt"):
            return None  # network blip on the sums fetch
        if url.endswith(".zip"):
            return good
        return f'<a href="{ZIP_NAME}">zip</a>'.encode()

    monkeypatch.setattr(hc, "_fetch_url", _fake_fetch)
    home = tmp_path / "home"
    home.mkdir()
    assert hc._stage_windows_node_zip(home, "x64") is None
    assert _home_entries(home) == []


def test_stage_rejects_zip_slip_even_with_valid_sums(tmp_path, monkeypatch):
    """A zip-slip member is refused by extraction even when the digest verifies."""
    slipped = _make_zip({
        TOP_DIR + "node.exe": b"NODE",
        "../../evil.txt": b"ESCAPED",
    })
    staged, home = _stage_with(slipped, f"{hashlib.sha256(slipped).hexdigest()}  {ZIP_NAME}\n".encode(),
                              tmp_path, monkeypatch)

    assert staged is None, "zip-slip must abort the stage"
    assert _home_entries(home) == []
    assert not (tmp_path.parent / "evil.txt").exists(), "no escapee may land outside home"


def test_stage_rejects_symlink_member_even_with_valid_sums(tmp_path, monkeypatch):
    """A symlink member is refused by extraction even when the digest verifies."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(TOP_DIR + "link")
        info.create_system = 3  # unix, so external_attr mode bits are honored
        info.external_attr = 0o120777 << 16  # S_IFLNK | rwxrwxrwx
        zf.writestr(info, "/etc/passwd")
    symlink_zip = buf.getvalue()

    staged, home = _stage_with(symlink_zip, f"{hashlib.sha256(symlink_zip).hexdigest()}  {ZIP_NAME}\n".encode(),
                               tmp_path, monkeypatch)
    assert staged is None
    assert _home_entries(home) == []


def test_verify_node_zip_sha256_tolerates_uppercase_and_star():
    """The parser accepts the forms SHASUMS.txt actually ships (upper hex, binary '*')."""
    good = _make_zip({TOP_DIR + "node.exe": b"NODE"})
    digest = hashlib.sha256(good).hexdigest()

    assert hc._verify_node_zip_sha256(f"{digest.upper()}  {ZIP_NAME}\n".encode(), ZIP_NAME, good)
    assert hc._verify_node_zip_sha256(f"{digest} *{ZIP_NAME}\n".encode(), ZIP_NAME, good)
    assert not hc._verify_node_zip_sha256(b"", ZIP_NAME, good)
    assert not hc._verify_node_zip_sha256(f"{digest}  other.zip\n".encode(), ZIP_NAME, good)
