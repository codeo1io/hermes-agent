"""Opt-in, fail-closed artifact gate for cron jobs that must produce real work.

This gate is not a substitute for campaign-specific CI, deployment, or soak acceptance.
It prevents a truncated or planning-only agent turn from being recorded as successful
merely because its transport returned HTTP 200.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat


_MARKER = "[CRON_EVIDENCE]"
# Exact gateway final-response wrapper observed on a SHA-valid canonical execution.
# Only this bounded, literal prefix is permitted; arbitrary prose remains invalid.
_KNOWN_GATEWAY_PREAMBLE = "All work verified and checkpointed. Final response:"
# Exact, observed production wrapper from execution 0e4484a820dd4e77a58d146ef3241fb9.
# Do not accept arbitrary prose as a wrapper: identity and SHA checks are necessary
# but not a substitute for an explicit leading evidence marker.
_KNOWN_INCIDENT_PREAMBLE = (
    "All gates closed: merge ✅, post-merge main CI **SUCCESS** at "
    "`0639f3c847` ✅, deploy ✅, E2E verification ✅, receipts ✅, worktrees cleaned ✅."
)
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_ALLOWED_KINDS = frozenset({"code_change", "runtime_repair", "validated_recovery"})


def _safe_file(path: Path, root: Path, size_limit: int) -> bytes:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("evidence path must be absolute and not a symlink")
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir() or resolved_root == Path("/"):
        raise ValueError("invalid evidence root")
    resolved_path = path.resolve(strict=True)
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError("evidence path escapes configured root")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > size_limit:
        raise ValueError("evidence must be a bounded regular file")
    return path.read_bytes()


def _validate_artifacts(
    artifacts: list, roots: list[Path], receipt_path: Path, claimed_at_epoch: float,
) -> None:
    """Verify every scoped artifact independently; never accept a receipt as its own proof."""
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("malformed artifact entry")
        path = Path(item["path"])
        if path == receipt_path:
            raise ValueError("receipt cannot verify itself")
        data = None
        for allowed_root in roots:
            try:
                data = _safe_file(path, allowed_root, _MAX_ARTIFACT_BYTES)
                break
            except (OSError, ValueError):
                continue
        if data is None or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise ValueError("artifact missing, out of scope, or digest mismatch")
        if path.stat().st_mtime + 1 < claimed_at_epoch:
            raise ValueError("artifact predates this execution")


def _canonical_pair(path: Path) -> str | None:
    """Machine-authored marker carrier published by the completion-stamp tool.

    Bound to the exact execution by filename and written atomically at
    receipt-mint time, so its position guarantee is structural rather than
    model-authored: the stamp tool (nrm-executor-completion-stamp.py, deployed
    2026-10-31) emits ``<execution_id>.response.md`` with the marker+digest as
    lines 1-2. Returns the digest when the canonical file carries the pair.
    """
    try:
        raw = _safe_file(path, path.parent, _MAX_RECEIPT_BYTES)
<<<<<<< HEAD
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if len(lines) < 2 or lines[0].strip() != _MARKER:
        return None
    prefix = "sha256:"
    if not lines[1].startswith(prefix):
        return None
    digest = lines[1][len(prefix):].strip()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return None
    return digest
=======
    except (OSError, ValueError):
        return None
    # Byte-exact verification against the stamp tool's carrier format. The
    # stamp tool writes exactly b"[CRON_EVIDENCE]\nsha256:<64 hex>\n" with LF
    # line endings only. A text-level parse (decode + splitlines + strip)
    # normalizes CRLF/CR and recognizes Unicode line separators, admitting
    # carriers the stamp tool could never emit; those must fail closed.
    prefix = b"[CRON_EVIDENCE]\nsha256:"
    if not raw.startswith(prefix) or not raw.endswith(b"\n"):
        return None
    digest_line = raw[len(prefix):-1]
    if len(digest_line) != 64 or any(
        chr(b) not in "0123456789abcdef" for b in digest_line
    ):
        return None
    try:
        return digest_line.decode("ascii")
    except UnicodeDecodeError:
        return None
>>>>>>> conductor-run-c33f40ea6566-implement-1


def validate_completion_evidence(
    job: dict, response: str, execution_id: str, *, claimed_at_epoch: float | None = None,
) -> str | None:
    """Return a failure reason, or None if the opt-in receipt is identity-bound.

    The job's receipt directory and artifact roots are trusted operator configuration,
    not text supplied by the model. Every run has its own immutable receipt filename.
    """
    root_text = job.get("completion_evidence_root")
    if not root_text:
        return None
    try:
        if not execution_id or not isinstance(root_text, str):
            raise ValueError("missing execution identity or evidence root")
        if claimed_at_epoch is None or claimed_at_epoch <= 0:
            raise ValueError("missing durable run claim timestamp")
        root = Path(root_text)
        if not root.is_absolute() or root == Path("/"):
            raise ValueError("completion evidence root must be an absolute directory")
        lines = (response or "").splitlines()
        if lines and lines[0] in (_KNOWN_GATEWAY_PREAMBLE, _KNOWN_INCIDENT_PREAMBLE):
            lines = lines[1:]
            if lines and lines[0] == "":
                lines = lines[1:]
        claimed = None
        if len(lines) >= 2 and lines[0] == _MARKER:
            prefix = "sha256:"
            if lines[1].startswith(prefix):
                candidate = lines[1][len(prefix):].strip()
                if len(candidate) == 64 and all(
                    ch in "0123456789abcdef" for ch in candidate
                ):
                    claimed = candidate
        if claimed is None:
            # Structural carrier: the completion-stamp tool publishes a
            # machine-authored <execution_id>.response.md bound to this exact
            # execution. Prose shape in the model's response cannot break it,
            # and it cannot be minted for any other execution.
            claimed = _canonical_pair(root / f"{execution_id}.response.md")
        if claimed is None:
            raise ValueError("missing explicit completion evidence marker")
        if len(claimed) != 64 or any(ch not in "0123456789abcdef" for ch in claimed):
            raise ValueError("invalid receipt digest")
        receipt_path = root / f"{execution_id}.json"
        raw = _safe_file(receipt_path, root, _MAX_RECEIPT_BYTES)
        if receipt_path.stat().st_mtime + 1 < claimed_at_epoch:
            raise ValueError("receipt predates this execution")
        if hashlib.sha256(raw).hexdigest() != claimed:
            raise ValueError("receipt digest mismatch")
        receipt = json.loads(raw)
        if not isinstance(receipt, dict):
            raise ValueError("receipt must be a JSON object")
        if receipt.get("execution_id") != execution_id or receipt.get("job_id") != job.get("id"):
            raise ValueError("receipt identity mismatch")
        if receipt.get("kind") not in _ALLOWED_KINDS:
            raise ValueError("receipt lacks typed repair kind")
        artifacts = receipt.get("artifacts")
        roots = [Path(x) for x in job.get("completion_artifact_roots", []) if isinstance(x, str)]
        if not roots or not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 16:
            raise ValueError("receipt lacks bounded verifiable artifacts or configured roots")
        _validate_artifacts(artifacts, roots, receipt_path, claimed_at_epoch)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return f"Cron completion evidence gate failed: {exc}"
    return None
