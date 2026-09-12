from types import SimpleNamespace

from api.routes import scans


class _Request:
    state = SimpleNamespace(user_email="owner@example.org")


def test_conformance_report_uses_the_same_immutable_snapshot_identity_as_release(monkeypatch):
    captured = {}

    class Store:
        def get_scan(self, sid, owner=None):
            return {"run": {"id": sid, "rubric_hash": "hash"}, "files": []}

        def stage_snapshot_id(self, sid):
            return "immutable-snapshot-digest"

        def get_decisions(self, sid): return []
        def get_remediation_evidence(self, sid): return []
        def get_certification_facts(self, sid, apply_document_selection=True): return {}
        def get_scan_scope(self, sid): return {'1.1.1': ['pdf']}
        def scope_for_file(self, sid, name, scope): return scope
        def list_hitl_queue(self, *, scan_id, owner):
            captured["queue_owner"] = owner
            return [
                {"file": "a.pdf", "rule_id": "SC_1_1_1", "proposals": [{"proposed_value": "Parking"}]},
                {"file": "a.pdf", "rule_id": "2.4.4", "proposals": [{"proposed_value": "Outside selected scope"}]},
            ]

    lineage = {"available": True, "integrity": {"ok": True},
               "workflow_id": "workflow-1", "workflow_revision": 7}
    monkeypatch.setattr(scans.core, "store", Store())
    monkeypatch.setattr(scans.core, "active_rubric", lambda: SimpleNamespace(
        cfg={"conformance_target": "WCAG 2.2 AA"}, version="2.2", hash="hash"))
    monkeypatch.setattr(scans, "_canonical_lineage_export", lambda sid, owner: {
        "lineage": lineage, "content_digest": {"value": "d" * 64}})

    def reconcile(scan_id, snapshot_id, stage_lineage):
        captured["identity"] = (scan_id, snapshot_id, stage_lineage)
        return {"identifiers": {"snapshot_id": snapshot_id}, "status": "reconciled"}

    monkeypatch.setattr(scans, "_release_finding_reconciliation", reconcile)
    def render(run, files, meta, **kw):
        captured["meta"] = meta
        captured["facts"] = kw["facts"]
        return b"pdf"

    monkeypatch.setattr(scans, "_render_report", render)

    response = scans.report_pdf("scan-1", _Request())

    assert captured["identity"] == ("scan-1", "immutable-snapshot-digest", lineage)
    assert captured["meta"]["finding_reconciliation"]["identifiers"]["snapshot_id"] == \
        "immutable-snapshot-digest"
    assert response.media_type == "application/pdf"

    assert captured["queue_owner"] == "owner@example.org"
    tasks = captured["facts"]["audit_review_tasks"]
    assert len(tasks) == 1
    assert tasks[0]["proposals"][0]["proposed_value"] == "Parking"
