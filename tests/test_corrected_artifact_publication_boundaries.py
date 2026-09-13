"""Publication regressions for races after the corrected bytes have been assessed.

These use a real saved Office archive and the real owned Store. Engines are controlled
only where a concurrent writer or approval must be injected at a precise boundary.
No provider uploads, external model requests, or customer documents are involved.
"""
import hashlib
import io
import json

import pytest
from docx import Document

from release_artifacts import ReleaseArtifactError
from release_candidate_assessment import assess_candidate, saved_assessment


SID, OWNER, FILE = "publication-race", "publication-owner", "candidate.docx"


@pytest.fixture
def artifact(isolated_store, monkeypatch):
    import core
    import blob

    store = isolated_store
    store.init_scan_run(SID, "local", 1, "2026-09-12T00:00:00Z", "rubric", "hash", owner=OWNER)
    baseline = [{"ruleId": "office-alt", "wcag": "1.1.1", "severity": "serious",
                 "detail": "Original assessment finding"}]
    store.save_file_result(SID, {"file": FILE, "engine": "office", "status": "analysed",
        "score": 100, "compliant": 1, "issues": baseline, "errors": [], "skipped_rules": 0},
        "2026-09-12T00:00:00Z")
    document = Document()
    document.add_heading("Corrected candidate", level=1)
    document.add_paragraph("Candidate content differs from the immutable source baseline.")
    output = io.BytesIO()
    document.save(output)
    data = output.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    at = store.record_remediation(SID, FILE, blob_url="blob://candidate", corrected_sha256=digest)
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(blob, "download_remediated", lambda *args: data)
    monkeypatch.setattr(store, "get_scan_scope", lambda *args, **kwargs: {"1.1.1": ["docx"]})
    monkeypatch.setattr(store, "scope_for_file", lambda sid, name, scope: scope)
    return store, data, digest, at


def _clear():
    from proposals import Verification
    return Verification(True, assessment={"status": "analysed", "issues": [], "errors": [], "skipped_rules": 0})


def test_release_engine_receives_actual_corrected_archive_without_replacing_source_findings(artifact, monkeypatch):
    import proposals
    store, data, digest, at = artifact
    received = []
    def verify(candidate, filename, *, scan_id):
        received.append((candidate, filename, scan_id))
        assert Document(io.BytesIO(candidate)).paragraphs[-1].text.startswith("Candidate content")
        return _clear()
    monkeypatch.setattr(proposals, "verify_residual", verify)
    before = store.get_scan(SID, owner=OWNER)["files"][0]["issues"]
    evidence = assess_candidate(store, SID, FILE, OWNER, digest, at, release_id="batch-a")
    assert received == [(data, FILE, SID)]
    assert evidence["artifact_sha256"] == digest and evidence["release_id"] == "batch-a"
    assert store.get_scan(SID, owner=OWNER)["files"][0]["issues"] == before


@pytest.mark.parametrize("remaining", [False, True])
@pytest.mark.parametrize("race", ["bytes", "timestamp", "approval", "selection"])
def test_engine_success_cannot_admit_candidate_changed_during_assessment(artifact, monkeypatch, remaining, race):
    import proposals
    store, data, digest, at = artifact
    old_record = store.get_file_record
    old_decisions = store.get_decisions
    changed = {"value": False}
    def record(scan_id, filename):
        value = old_record(scan_id, filename)
        if changed["value"] and race == "bytes":
            return {**value, "corrected_sha256": "f" * 64}
        if changed["value"] and race == "timestamp":
            return {**value, "remediated_at": "2026-09-12T23:59:00Z"}
        return value
    def decisions(scan_id, owner=None):
        if changed["value"] and race == "selection":
            return {"other.docx": {"triage": "inscope"}}
        return old_decisions(scan_id, owner=owner)
    monkeypatch.setattr(store, "get_file_record", record)
    monkeypatch.setattr(store, "get_decisions", decisions)
    monkeypatch.setattr(store, "count_unapplied_approved_values",
        lambda *args: int(changed["value"] and race == "approval"))
    def verify(*args, **kwargs):
        changed["value"] = True
        return _clear()
    monkeypatch.setattr(proposals, "verify_residual", verify)
    with pytest.raises(ReleaseArtifactError) as error:
        assess_candidate(store, SID, FILE, OWNER, digest, at, data=data,
                         allow_remaining_issues=remaining)
    assert error.value.category == ("approved_changes_unapplied" if race == "approval"
                                    else "release_evidence_changed")


def test_changed_download_is_rejected_without_running_assessment_or_logging_attestation(artifact, monkeypatch):
    import blob
    import proposals
    store, _, digest, at = artifact
    monkeypatch.setattr(blob, "download_remediated", lambda *args: b"replacement bytes")
    engine_calls, decisions = [], []
    monkeypatch.setattr(proposals, "verify_residual", lambda *args, **kwargs: engine_calls.append(args))
    monkeypatch.setattr(store, "log_decision", lambda *args, **kwargs: decisions.append(args))
    with pytest.raises(ReleaseArtifactError, match="bytes changed"):
        assess_candidate(store, SID, FILE, OWNER, digest, at, allow_remaining_issues=True)
    assert engine_calls == decisions == []


def test_saved_assessment_cannot_reuse_other_owner_or_other_release_attestation(artifact, monkeypatch):
    import proposals
    store, data, digest, at = artifact
    monkeypatch.setattr(proposals, "verify_residual", lambda *args, **kwargs: _clear())
    expected = assess_candidate(store, SID, FILE, OWNER, digest, at, data=data, release_id="owned-batch")
    # A later row must not shadow the exact owned batch, even for identical bytes.
    other_batch = {**expected, "release_id": "other-batch", "reason": "different release"}
    store.log_decision(OWNER, "release.corrected_copy_assessed", scan_id=SID, file=FILE,
                       detail=json.dumps(other_batch))
    store.log_decision("other-owner", "release.corrected_copy_assessed", scan_id=SID, file=FILE,
                       detail=json.dumps({**expected, "reason": "foreign actor"}))
    assert saved_assessment(store, SID, OWNER, FILE, "sha256:" + digest,
                            release_id="owned-batch") == expected
    assert saved_assessment(store, SID, OWNER, FILE, digest, release_id="missing-batch") is None
    assert saved_assessment(store, SID, "other-owner", FILE, digest, release_id="owned-batch") is None
