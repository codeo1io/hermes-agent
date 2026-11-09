"""Fail-closed evidence acceptance for cron jobs requiring real work."""
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

from cron.completion_evidence import validate_completion_evidence as _gate


def validate_completion_evidence(job, response, execution_id):
    return _gate(job, response, execution_id, claimed_at_epoch=time.time() - 10)


def _case(tmp_path, execution_id="exec-abc"):
    root = tmp_path / "receipts"
    root.mkdir()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    artifact = artifact_root / "code.diff"
    artifact.write_text("real change\n")
    job = {
        "id": "job-123",
        "completion_evidence_root": str(root),
        "completion_artifact_roots": [str(artifact_root)],
    }
    receipt = {
        "job_id": job["id"],
        "execution_id": execution_id,
        "kind": "code_change",
        "artifacts": [{"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}],
    }
    path = root / f"{execution_id}.json"
    path.write_text(json.dumps(receipt))
    response = "[CRON_EVIDENCE]\nsha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return job, receipt, path, artifact, response


def test_unconfigured_jobs_keep_original_semantics():
    assert validate_completion_evidence({"id": "normal"}, "short", "run-1") is None


def test_identity_bound_receipt_and_hashed_artifact_pass(tmp_path):
    job, _, _, _, response = _case(tmp_path)
    assert validate_completion_evidence(job, response, "exec-abc") is None


def test_truncated_or_planning_only_response_fails(tmp_path):
    job, _, _, _, _ = _case(tmp_path)
    assert "marker" in validate_completion_evidence(job, "I will investigate", "exec-abc")


def test_exact_gateway_final_response_preamble_preserves_valid_receipt(tmp_path):
    job, _, _, _, response = _case(tmp_path)
    prefix = "All work verified and checkpointed. Final response:"
    for separator in ("\n", "\n\n"):
        assert validate_completion_evidence(job, prefix + separator + response, "exec-abc") is None


def test_exact_incident_summary_before_marker_preserves_valid_receipt(tmp_path):
    # Production incident 0e4484a8: allow only the literal observed summary.
    job, _, _, _, response = _case(tmp_path)
    lead = (
        "All gates closed: merge ✅, post-merge main CI **SUCCESS** at "
        "`0639f3c847` ✅, deploy ✅, E2E verification ✅, receipts ✅, worktrees cleaned ✅.\n\n"
    )
    assert validate_completion_evidence(job, lead + response, "exec-abc") is None


def test_arbitrary_summary_or_whitespace_before_marker_fails_closed(tmp_path):
    job, _, _, _, response = _case(tmp_path)
    for lead in (
        "Short status line.\n",
        "All gates closed: merge, post-merge CI, deploy, E2E verification, receipts.\n\n",
        "\n",
        "  ",
        "All work verified and checkpointed. Final response:\nUnrecognized summary.\n",
    ):
        assert "marker" in validate_completion_evidence(job, lead + response, "exec-abc")


def test_second_prose_line_before_marker_remains_fail_closed(tmp_path):
    # Review feedback (issuecomment-6563745902): tolerance must not accept arbitrary
    # multi-line prose. Two prose lines before the marker = buried marker = rejected.
    job, _, _, _, response = _case(tmp_path)
    for lead in (
        "First summary line.\nSecond summary line.\n\n",
        "Line one.\nLine two.\nLine three.\n" + response,
    ):
        assert "marker" in validate_completion_evidence(job, lead + response, "exec-abc")


def test_prose_after_gateway_preamble_line_remains_fail_closed(tmp_path):
    # An exact gateway wrapper cannot be combined with arbitrary model prose.
    job, _, _, _, response = _case(tmp_path)
    prefix = "All work verified and checkpointed. Final response:"
    assert "marker" in validate_completion_evidence(
        job, prefix + "\nSummary line.\n" + response, "exec-abc")
    assert "marker" in validate_completion_evidence(
        job, prefix + "\nLine one.\nLine two.\n" + response, "exec-abc")


def test_marker_buried_deep_in_response_still_fails(tmp_path):
    # Tolerance is bounded: a marker buried under unbounded prose is not a preamble.
    job, _, _, _, response = _case(tmp_path)
    noise = "".join(f"line {i} of report\n" for i in range(12))
    assert "marker" in validate_completion_evidence(job, noise + response, "exec-abc")


def test_bounded_preamble_does_not_waive_receipt_digest(tmp_path):
    job, _, _, _, _ = _case(tmp_path)
    response = "All work verified and checkpointed. Final response:\n[CRON_EVIDENCE]\nsha256:" + "0" * 64
    assert "digest mismatch" in validate_completion_evidence(job, response, "exec-abc")


def test_receipt_digest_mismatch_fails(tmp_path):
    job, _, _, _, _ = _case(tmp_path)
    response = "[CRON_EVIDENCE]\nsha256:" + "0" * 64
    assert "digest mismatch" in validate_completion_evidence(job, response, "exec-abc")


def test_receipt_identity_mismatch_fails(tmp_path):
    job, receipt, path, _, _ = _case(tmp_path)
    receipt["execution_id"] = "other-run"
    path.write_text(json.dumps(receipt))
    response = "[CRON_EVIDENCE]\nsha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert "identity mismatch" in validate_completion_evidence(job, response, "exec-abc")


def test_receipt_without_typed_artifact_fails(tmp_path):
    job, receipt, path, _, _ = _case(tmp_path)
    receipt["artifacts"] = []
    path.write_text(json.dumps(receipt))
    response = "[CRON_EVIDENCE]\nsha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert "artifacts" in validate_completion_evidence(job, response, "exec-abc")


def test_artifact_content_change_fails(tmp_path):
    job, _, _, artifact, response = _case(tmp_path)
    artifact.write_text("tampered")
    assert "digest mismatch" in validate_completion_evidence(job, response, "exec-abc")


def test_symlinked_artifact_fails(tmp_path):
    job, receipt, path, artifact, _ = _case(tmp_path)
    link = artifact.parent / "link.diff"
    link.symlink_to(artifact)
    receipt["artifacts"][0]["path"] = str(link)
    path.write_text(json.dumps(receipt))
    response = "[CRON_EVIDENCE]\nsha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert "out of scope" in validate_completion_evidence(job, response, "exec-abc")


def test_receipt_outside_root_not_accepted(tmp_path):
    job, _, _, _, response = _case(tmp_path)
    job["completion_evidence_root"] = str(tmp_path / "absent")
    assert "failed" in validate_completion_evidence(job, response, "exec-abc")


def test_old_receipt_cannot_be_reused_for_new_execution(tmp_path):
    job, _, _, _, response = _case(tmp_path)
    assert "predates" in _gate(
        job, response, "exec-abc", claimed_at_epoch=time.time() + 60
    )


def test_scheduler_marks_truncated_gated_turn_failed(tmp_path, monkeypatch):
    from cron.scheduler import _apply_agent_failure_marker
    monkeypatch.setattr(
        "cron.scheduler.get_execution",
        lambda _id: {"claimed_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat()},
    )

    job, _, _, _, _ = _case(tmp_path)
    success, error, agent_declared = _apply_agent_failure_marker(
        job, True, None, "I will now inspect", execution_id="exec-abc"
    )
    assert success is False
    assert "completion evidence gate failed" in error
    assert agent_declared is False


def test_scheduler_accepts_identity_bound_receipt(tmp_path, monkeypatch):
    from cron.scheduler import _apply_agent_failure_marker
    monkeypatch.setattr(
        "cron.scheduler.get_execution",
        lambda _id: {"claimed_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat()},
    )

    job, _, _, _, response = _case(tmp_path)
    assert _apply_agent_failure_marker(
        job, True, None, response, execution_id="exec-abc"
    ) == (True, None, False)


def test_canonical_response_file_carries_pair_structurally(tmp_path):
    """The completion-stamp tool's machine-authored <execution_id>.response.md
    satisfies marker carriage when the model's response prose precedes the pair
    (position-flexible carrier; bound to this exact execution by filename)."""
    job, _, _, _, _ = _case(tmp_path)
    receipt_digest = hashlib.sha256(
        (tmp_path / "receipts" / "exec-abc.json").read_bytes()
    ).hexdigest()
    (tmp_path / "receipts" / "exec-abc.response.md").write_text(
        "[CRON_EVIDENCE]\nsha256:" + receipt_digest + "\n"
    )
    prose = "Repair landed end-to-end: PR merged, CI green, deployed.\n\nmore detail\n"
    assert validate_completion_evidence(job, prose, "exec-abc") is None


<<<<<<< HEAD
=======
def test_canonical_carrier_rejects_indented_marker_or_digest(tmp_path):
    """The stamp tool emits exact first/second lines, never whitespace-padded ones."""
    job, _, path, _, _ = _case(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    carrier = path.with_suffix(".response.md")
    for body in (
        " [CRON_EVIDENCE]\nsha256:" + digest + "\n",
        "[CRON_EVIDENCE]\n sha256:" + digest + "\n",
        "[CRON_EVIDENCE]\nsha256:" + digest + " \n",
        "[CRON_EVIDENCE]\nsha256:" + digest + "\nInjected third line\n",
    ):
        carrier.write_text(body)
        assert "marker" in validate_completion_evidence(
            job, "Planning only; no explicit marker", "exec-abc"
        )


def test_canonical_carrier_rejects_noncanonical_line_endings(tmp_path):
    """The stamp tool emits LF-only bytes; splitlines() normalization must not
    admit CRLF/CR/vertical-tab/Unicode-separator carriers it could never write."""
    job, _, path, _, _ = _case(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    carrier = path.with_suffix(".response.md")
    for body in (
        "[CRON_EVIDENCE]\r\nsha256:" + digest + "\r\n",
        "[CRON_EVIDENCE]\nsha256:" + digest + "\r\n",
        "[CRON_EVIDENCE]\vsha256:" + digest + "\v",
        "[CRON_EVIDENCE]sha256:" + digest + "",
        "[CRON_EVIDENCE]\nsha256:" + digest,
    ):
        carrier.write_bytes(body.encode("utf-8"))
        assert validate_completion_evidence(
            job, "Planning only; no explicit marker", "exec-abc"
        ) is not None


>>>>>>> conductor-run-c33f40ea6566-implement-1
def test_canonical_file_wrong_digest_fails_closed(tmp_path):
    job, _, _, _, _ = _case(tmp_path)
    (tmp_path / "receipts" / "exec-abc.response.md").write_text(
        "[CRON_EVIDENCE]\nsha256:" + "0" * 64 + "\n"
    )
    result = validate_completion_evidence(job, "no pair here", "exec-abc")
    assert result is not None and "digest mismatch" in result


def test_canonical_file_of_other_execution_cannot_vouch(tmp_path):
    """A canonical file named for a different execution must not satisfy this
    execution's marker carriage."""
    job, _, _, _, _ = _case(tmp_path)
    receipt_digest = hashlib.sha256(
        (tmp_path / "receipts" / "exec-abc.json").read_bytes()
    ).hexdigest()
    (tmp_path / "receipts" / "other-exec.response.md").write_text(
        "[CRON_EVIDENCE]\nsha256:" + receipt_digest + "\n"
    )
    assert "marker" in validate_completion_evidence(job, "prose only", "exec-abc")


def test_scheduler_accepts_canonical_carrier(tmp_path, monkeypatch):
    from cron.scheduler import _apply_agent_failure_marker
    monkeypatch.setattr(
        "cron.scheduler.get_execution",
        lambda _id: {"claimed_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat()},
    )
    job, _, _, _, _ = _case(tmp_path)
    receipt_digest = hashlib.sha256(
        (tmp_path / "receipts" / "exec-abc.json").read_bytes()
    ).hexdigest()
    (tmp_path / "receipts" / "exec-abc.response.md").write_text(
        "[CRON_EVIDENCE]\nsha256:" + receipt_digest + "\n"
    )
    assert _apply_agent_failure_marker(
        job, True, None, "Summary prose without the pair.", execution_id="exec-abc"
    ) == (True, None, False)
