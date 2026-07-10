"""The write-back that closes remediate → review → publish.

Approving an alt-text value used to store the text as evidence and stop. Nothing wrote it into
the document, so store.mark_file_compliant_if_reviewed correctly refused to certify the file —
and, having no applier, it refused forever. The file was approved and permanently unpublishable.

These tests pin the loop end to end: per-image approvals reach the right images, the values are
credited only when a re-scan of the WRITTEN bytes shows the criterion cleared, and the file
certifies off that re-scan rather than off the approval.
"""
from __future__ import annotations
import io
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

SLIDE = "ppt/slides/slide1.xml"
FILE = "deck.pptx"
SID = "s1"


def _deck(*names: str) -> bytes:
    pics = "".join(f'<p:pic><p:cNvPr id="{i+2}" name="{n}"/></p:pic>' for i, n in enumerate(names))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(SLIDE, f"<p:sld>{pics}</p:sld>")
        z.writestr("docProps/core.xml", "<cp:coreProperties/>")
    return buf.getvalue()


def _slide_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(SLIDE).decode("utf-8")


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "apply.db")
    return store_mod.Store()


def _seed(store, *, names=("Picture 1", "Chart 2")):
    """A remediated deck with one 1.1.1 HITL row carrying one proposal per image."""
    store.init_scan_run(SID, "drive", 1, "2026-07-10T00:00:00Z", "rubric", "hash")
    store.save_file_result(SID, {
        "file": FILE, "engine": "office", "status": "pass", "score": 40, "compliant": 0,
        "skipped_rules": 0, "drive_file_id": "drv1",
        "issues": [{"ruleId": "PPTX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"}],
    }, "2026-07-10T00:00:00Z")
    store.record_remediation(SID, FILE, drive_write_url="http://d/1", blob_url="http://b/1")
    item_id = store.enqueue_proposals(SID, FILE, "1.1.1", [
        {"locator": f"{SLIDE}#{n}", "before": "(no alt text)",
         "proposed_value": f"AI draft for {n}", "rationale": "r", "source": "llava"}
        for n in names
    ], rule_name="Non-text Content")
    return item_id


class _Blob:
    """Stands in for Azure Blob: the remediated copy lives here and the applier rewrites it."""
    def __init__(self, data): self.data, self.uploads = data, []
    def download_remediated(self, owner, sid, f): return self.data
    def upload_remediated(self, owner, sid, f, data, mime):
        self.data = data; self.uploads.append((f, mime)); return "http://b/2"


def _run_handler(monkeypatch, store, blob, *, residual):
    """Drive the handler with Blob and the residual re-scan stubbed."""
    import core, handlers
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setitem(sys.modules, "blob", blob)
    monkeypatch.setattr(handlers, "_verify_residual_scs", lambda b, f: residual)
    handlers._apply_approved_values({"scan_id": SID, "file": FILE}, {})


# ── the gate, before anything is written ──────────────────────────────────────

def test_approval_alone_leaves_the_file_uncertified(store):
    item_id = _seed(store)
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, [])          # accept both drafts unedited

    assert store.count_unapplied_approved_values(SID, FILE) == 1
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is False


# ── the write ─────────────────────────────────────────────────────────────────

def test_each_image_receives_its_own_approved_description(store, monkeypatch):
    item_id = _seed(store)
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, ["A clinician at a desk.", None])   # edit 1st, accept 2nd

    blob = _Blob(_deck("Picture 1", "Chart 2"))
    _run_handler(monkeypatch, store, blob, residual=set())

    xml = _slide_xml(blob.data)
    assert 'name="Picture 1" descr="A clinician at a desk."' in xml
    assert 'name="Chart 2" descr="AI draft for Chart 2"' in xml     # unedited draft accepted
    assert blob.uploads == [(FILE, "application/vnd.openxmlformats-officedocument.presentationml.presentation")]


def test_written_values_are_credited_and_the_file_certifies_off_the_rescan(store, monkeypatch):
    item_id = _seed(store)
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, [])

    _run_handler(monkeypatch, store, _Blob(_deck("Picture 1", "Chart 2")), residual=set())

    assert store.count_unapplied_approved_values(SID, FILE) == 0     # promise kept
    rec = store.get_file_record(SID, FILE)
    assert rec["compliant"] == 1                                     # certified by the apply job
    diffs = store.get_remediation_diffs(SID, FILE)
    assert [d["after"] for d in diffs] == ["AI draft for Picture 1", "AI draft for Chart 2"]
    assert all("approved by a reviewer" in d["note"] for d in diffs)


# ── the honesty gates ─────────────────────────────────────────────────────────

def test_a_write_that_does_not_clear_the_criterion_credits_nothing(store, monkeypatch):
    """The text went in but 1.1.1 still fails — an image nobody reviewed, say. Crediting the
    approval here would certify a document that still fails, which is the original bug."""
    item_id = _seed(store)
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, [])

    blob = _Blob(_deck("Picture 1", "Chart 2"))
    _run_handler(monkeypatch, store, blob, residual={"1.1.1"})       # still failing

    assert store.count_unapplied_approved_values(SID, FILE) == 1     # row stays unapplied
    assert store.get_file_record(SID, FILE)["compliant"] == 0
    assert blob.uploads == []                                        # nothing stored
    assert store.get_remediation_diffs(SID, FILE) == []


def test_an_unresolvable_locator_is_never_written_to_another_image(store, monkeypatch):
    """The reviewer approved text for an image this document no longer has."""
    item_id = _seed(store, names=("Picture 1", "Ghost 9"))
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, [])

    blob = _Blob(_deck("Picture 1"))                                 # Ghost 9 is gone
    _run_handler(monkeypatch, store, blob, residual=set())

    xml = _slide_xml(blob.data)
    assert 'name="Picture 1" descr="AI draft for Picture 1"' in xml
    assert "Ghost 9" not in xml
    notes = [d["detail"] for d in store.list_decisions(scan_id=SID) if d["action"] == "apply.unresolved"]
    assert notes and "Ghost 9" in notes[0]


def test_no_remediated_copy_means_nothing_is_written(store, monkeypatch):
    item_id = _seed(store)
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, [])

    blob = _Blob(None)                                               # never remediated
    _run_handler(monkeypatch, store, blob, residual=set())

    assert store.count_unapplied_approved_values(SID, FILE) == 1
    assert [d["action"] for d in store.list_decisions(scan_id=SID)].count("apply.no_remediated_copy") == 1


def test_a_format_with_no_applier_says_so_rather_than_succeeding(store, monkeypatch):
    import core, handlers
    store.init_scan_run(SID, "drive", 1, "t", "r", "h")
    monkeypatch.setattr(core, "store", store)
    handlers._apply_approved_values({"scan_id": SID, "file": "report.pdf"}, {})
    actions = [d["action"] for d in store.list_decisions(scan_id=SID)]
    assert "apply.unsupported" in actions


def test_applying_twice_is_idempotent(store, monkeypatch):
    item_id = _seed(store)
    store.update_hitl_item(item_id, "approved", None, None)
    store.approve_proposal_values(item_id, [])

    blob = _Blob(_deck("Picture 1", "Chart 2"))
    _run_handler(monkeypatch, store, blob, residual=set())
    first = blob.data
    _run_handler(monkeypatch, store, blob, residual=set())           # row is applied now

    assert blob.data == first                                        # no second write
    assert len(blob.uploads) == 1
    assert len(store.get_remediation_diffs(SID, FILE)) == 2          # diffs not duplicated


# ── unedited approval means "the drafts I was shown are correct" ──────────────

def test_approve_proposal_values_falls_back_to_each_draft(store):
    item_id = _seed(store)
    assert store.approve_proposal_values(item_id, [None, ""]) == 2
    vals = store.approved_alt_values(SID, FILE)
    assert vals == {}                                                # not approved yet
    store.update_hitl_item(item_id, "approved", None, None)
    assert store.approved_alt_values(SID, FILE) == {
        f"{SLIDE}#Picture 1": "AI draft for Picture 1",
        f"{SLIDE}#Chart 2": "AI draft for Chart 2",
    }


# ── the route seam: approving must actually schedule the write ────────────────

def _req(email="ada@movate.com"):
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


def test_the_approve_route_enqueues_the_write_and_records_the_values(store, monkeypatch):
    """Without this enqueue the values sit in the database forever — the original dead end."""
    import core
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "fire_webhook", lambda *a, **k: None)
    from routes.hitl import hitl_update, HitlUpdate

    item_id = _seed(store)
    res = hitl_update(item_id, HitlUpdate(status="approved",
                                          approved_values=["A clinician at a desk.", None]), _req())
    assert res["status"] == "approved"

    # the reviewer's per-image text was recorded, unedited entries falling back to the draft
    assert store.approved_alt_values(SID, FILE) == {
        f"{SLIDE}#Picture 1": "A clinician at a desk.",
        f"{SLIDE}#Chart 2": "AI draft for Chart 2",
    }
    # …and a write was scheduled
    job = store.claim_job("w1")
    assert job["type"] == "apply_approved_values"
    assert job["payload"] == {"scan_id": SID, "file": FILE}
    # the file does NOT certify on the approval itself — the document has no descriptions yet
    assert store.get_file_record(SID, FILE)["compliant"] == 0


def test_a_judgement_approval_schedules_no_write(store, monkeypatch):
    """A contrast sign-off resolves by approval alone; there is no content to write."""
    import core
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "fire_webhook", lambda *a, **k: None)
    from routes.hitl import hitl_update, HitlUpdate

    store.init_scan_run(SID, "drive", 1, "t", "r", "h")
    item = store.queue_hitl_deferral(SID, FILE, "contrast needs sign-off", 1, rule_id="1.4.3")
    hitl_update(item, HitlUpdate(status="approved"), _req())
    assert store.claim_job("w1") is None


def test_link_purpose_approvals_have_no_applier_and_keep_the_file_out_of_publish(store):
    """2.4.4 carries no alt-text applier. It must not be silently dropped: the file stays
    uncertified rather than certifying with the link text still unwritten."""
    _seed(store)
    item = store.enqueue_proposals(SID, FILE, "2.4.4", [
        {"locator": "slide1#rId3", "before": "click here",
         "proposed_value": "Download the intake form", "rationale": "r", "source": "llm"}],
        rule_name="Link Purpose")
    store.update_hitl_item(item, "approved", None, None)
    store.approve_proposal_values(item, [])

    assert store.approved_alt_values(SID, FILE) == {}                # not an alt-text value
    assert store.count_unapplied_approved_values(SID, FILE) >= 1     # still gates Publish
