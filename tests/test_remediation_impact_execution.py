"""A preview policy must govern real worker mutations, not merely label the job."""
from types import SimpleNamespace

import pytest

import handlers
from remediation_impact_execution import execution_controls
from worker import FatalJobError


def payload(rule_based=2, ai=0, rules=None, file="report.html"):
    return {"scan_id": "scan", "file": file, "source": "local",
            "remediation_impact_policy": {"rule_based": rule_based, "ai": ai},
            "remediation_impact_allowed_rules": rules if rules is not None else ["3.1.1"]}


@pytest.fixture
def worker(monkeypatch):
    calls = {"drafts": [], "decisions": []}
    store = SimpleNamespace(
        is_shadowed_output=lambda *_: False,
        get_ai_enabled=lambda: True,
        get_scan_traces=lambda *args, **kwargs: [{"rule_id": "3.1.1", "outcome": "FAIL", "finding_count": 1}],
        queue_hitl_review_for_file=lambda *args: calls.setdefault("queued", []).append(args),
        list_auto_fail_rules=lambda *_: ["3.1.1", "2.4.2"],
        log_decision=lambda *args, **kwargs: calls["decisions"].append(kwargs),
    )
    monkeypatch.setattr(handlers.core, "store", store)
    monkeypatch.setattr(handlers, "_phase", lambda *_: None)
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *_: None)
    monkeypatch.setattr(handlers, "_remediation_source_bytes",
                        lambda *_: (b"<html><body>Original</body></html>", None))
    monkeypatch.setattr(handlers, "_propose_text_findings",
                        lambda *args: calls["drafts"].append(args[-1]))
    import activity
    monkeypatch.setattr(activity, "record", lambda *args, **kwargs: None)
    return calls


def test_review_first_drafts_without_entering_mutation_or_publication(worker, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("review-first entered a mutating format writer")
    monkeypatch.setattr(handlers, "remediate_html", forbidden)
    handlers._remediate_file(payload(rule_based=0, ai=1), {})
    assert worker["drafts"] == [True]
    assert worker["queued"][0][2][0]["rule_id"] == "3.1.1"
    assert "no automatic mutations" in worker["decisions"][-1]["detail"]


def test_mutating_writer_gets_only_authorized_criteria_and_no_inline_ai(worker, monkeypatch):
    class ReachedWriter(Exception):
        pass

    def inspect_writer(source, **kwargs):
        assert kwargs["ai_enabled"] is False
        assert kwargs["in_scope"]("3.1.1") is True
        assert kwargs["in_scope"]("2.4.2") is False
        assert kwargs["in_scope"]("1.1.1") is False
        raise ReachedWriter()

    monkeypatch.setattr(handlers, "remediate_html", inspect_writer)
    with pytest.raises(ReachedWriter):
        handlers._remediate_file(payload(ai=1), {})
    assert worker["drafts"] == [True]


def test_ai_off_blocks_media_transcription_before_download(worker, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("AI-off entered the transcription path")
    monkeypatch.setattr(handlers, "_propose_media_captions", forbidden)
    handlers._remediate_file(payload(file="recording.mp4"), {})
    assert worker["drafts"] == []
    assert "AI drafting disabled" in worker["decisions"][-1]["detail"]


@pytest.mark.parametrize("ai", [2, 3])
def test_unsupported_ai_automatic_policy_fails_before_any_draft(worker, ai):
    with pytest.raises(FatalJobError, match="Automatic AI application"):
        handlers._remediate_file(payload(ai=ai), {})
    assert worker["drafts"] == []


def test_global_ai_kill_switch_overrides_sealed_drafting_permission():
    assert execution_controls(payload(ai=1), False)["draft_ai"] is False


def test_missing_authoritative_rule_scope_fails_closed():
    request = payload()
    del request["remediation_impact_allowed_rules"]
    with pytest.raises(ValueError, match="authoritative"):
        execution_controls(request, True)


def test_legacy_job_has_no_new_policy_override():
    assert execution_controls({}, True) is None


def test_ai_off_preserves_ocr_proposals_without_calling_vision(monkeypatch):
    import ai
    import ocr
    import proposals
    calls = []
    monkeypatch.setattr(ocr, "is_available", lambda: True)
    monkeypatch.setattr(ocr, "_embedded_images", lambda *_: [b"logo"])
    monkeypatch.setattr(ocr, "_ocr_words", lambda *_: ocr._MIN_WORDS_STRICT)
    monkeypatch.setattr(ocr, "ocr_text", lambda *_: "Example Company Name")
    monkeypatch.setattr(proposals, "thumb_b64", lambda *_: None)
    monkeypatch.setattr(ai, "looks_like_logotype", lambda *_: calls.append("vision") or True)
    result = proposals.propose_images_of_text("example.docx", ".docx", ai_enabled=False)
    assert len(result) == 1
    assert result[0]["proposed_value"] == "Example Company Name"
    assert calls == []
    proposals.propose_images_of_text("example.docx", ".docx", ai_enabled=True)
    assert calls == ["vision"]
