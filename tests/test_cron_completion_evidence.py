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
