"""An escalation that isn't written down didn't happen.

THE DEFECT. `_escalate_low_confidence_findings` (handlers.py) renders a document's first page,
sends it to a cloud vision provider for every LOW-confidence finding, and annotates each of those
findings in place with an `hf_provenance` dict. Both `issue_records` INSERTs then wrote
(scan_id,file,rule_id,wcag,severity,detail,page,location) — no provenance column existed and no
reader looked for one — so the annotation was dropped at the database boundary. The escalation
still cost a cloud call per file; what it bought was discarded microseconds later, and the
reviewer reading the finding was never told the flag had been checked a second time.

WHAT IS STORED, AND WHAT IS NOT. Four bounded fields: provider, zone, escalated, cost_usd. The
model's free-text answer is not stored and not rendered — it is about a page of a customer's
document, and a column is the wrong place for it. The encoder is a whitelist rather than a dump
precisely so a key added upstream (by handlers, or by a provider response passing through it)
cannot reach the column by default.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "provenance.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


PROV = {"provider": "huggingface", "zone": "cloud", "escalated": True, "cost_usd": 0.00042}


def _file(name="a.pdf", *, checksum=None, provenance=PROV):
    issue = {"ruleId": "PDF_INPUT_PURPOSE", "wcag": "1.3.5 Identify Input Purpose",
             "severity": "MINOR", "detail": "field 'addr1' may collect personal data", "page": 1}
    if provenance is not None:
        issue["hf_provenance"] = dict(provenance)
    plain = {"ruleId": "PDF_LINK_PURPOSE", "wcag": "2.4.4 Link Purpose", "severity": "MINOR",
             "detail": "raw URL as link text", "page": 2}
    return {"file": name, "engine": "pdf", "status": "uncertain", "score": 70, "compliant": False,
            "skipped_rules": 0, "checksum": checksum, "issues": [issue, plain]}


def _scan(store, sid="s1", files=1):
    store.init_scan_run(sid, "drive", files, "2026-09-05T00:00:00Z", "rubric", "hash",
                        owner="demo")
    store.set_scan_files(sid, files)
    return sid


def _issues(store, sid, name="a.pdf"):
    files = store.get_scan(sid)["files"]
    return next(f for f in files if f["file"] == name)["issues"]


# ── the encoder: bounded, and bounded on purpose ─────────────────────────────

def test_only_the_four_declared_fields_are_encoded():
    import store as store_mod
    raw = store_mod._issue_provenance({"hf_provenance": {
        **PROV,
        # The two things that must never reach a column, both plausible additions upstream: the
        # model's answer about the page, and the prompt that produced it.
        "text": "The image at the top of page 1 appears to be decorative.",
        "prompt": "You are an accessibility reviewer…",
    }})
    assert json.loads(raw) == PROV, "a key added upstream must not reach the column by default"


def test_a_finding_that_never_escalated_encodes_to_null():
    import store as store_mod
    assert store_mod._issue_provenance({"wcag": "2.4.4"}) is None
    assert store_mod._issue_provenance({"hf_provenance": None}) is None
    assert store_mod._issue_provenance({"hf_provenance": {}}) is None
    # Not a dict — a value shaped wrong is "nothing escalated", never an exception on a save path.
    assert store_mod._issue_provenance({"hf_provenance": "huggingface"}) is None


def test_a_column_value_that_will_not_decode_reads_as_no_escalation():
    import store as store_mod
    assert store_mod._decode_provenance(None) is None
    assert store_mod._decode_provenance("") is None
    assert store_mod._decode_provenance("{not json") is None
    assert store_mod._decode_provenance("[1,2]") is None, "a non-dict is not a provenance record"
    assert store_mod._decode_provenance('{"provider":"openai"}') == {"provider": "openai"}


# ── the round trip, which is the whole point ─────────────────────────────────

def test_save_file_result_round_trips_the_provenance_to_the_card(store):
    sid = _scan(store)
    store.save_file_result(sid, _file(), "2026-09-05T00:01:00Z")
    issues = _issues(store, sid)
    escalated = [i for i in issues if i.get("hf_provenance")]
    assert len(escalated) == 1, "the escalated finding must come back carrying its provenance"
    assert escalated[0]["hf_provenance"] == PROV
    assert escalated[0]["wcag"].startswith("1.3.5")


def test_the_un_escalated_finding_carries_no_key_at_all(store):
    # Not a null — a key on every issue of a several-thousand-file scan to say nothing.
    sid = _scan(store)
    store.save_file_result(sid, _file(), "2026-09-05T00:01:00Z")
    plain = next(i for i in _issues(store, sid) if i["wcag"].startswith("2.4.4"))
    assert "hf_provenance" not in plain


def test_save_scan_the_other_insert_site_persists_it_too(store):
    # TWO INSERT sites write issue_records — the monolithic save_scan and the per-file
    # save_file_result. Wiring one and not the other is exactly how `location` was lost.
    report = {"_scan_id": "s2",
              "started_at": "2026-09-05T00:00:00Z", "completed_at": "2026-09-05T00:02:00Z",
              "source": "drive", "rubric": {"name": "rubric", "hash": "hash"},
              "owner": "demo", "files": [_file()],
              "summary": {"files": 1, "certifiable": 0, "uncertain": 1, "error": 0,
                          "avg_score": 70}}
    assert store.save_scan(report) == "s2"
    escalated = [i for i in _issues(store, "s2") if i.get("hf_provenance")]
    assert len(escalated) == 1 and escalated[0]["hf_provenance"] == PROV


def test_a_deduplicated_copy_keeps_saying_it_was_escalated(store):
    """find_by_checksum copies an analysis forward under a second file's name instead of
    re-running the engine. Dropping the provenance there would silently un-escalate the copy —
    the same finding, on identical bytes, reading as an un-checked heuristic hit on one card and
    a cloud-confirmed one on the other."""
    sid = _scan(store, files=2)
    store.save_file_result(sid, _file("a.pdf", checksum="ck1"), "2026-09-05T00:01:00Z")
    carried = store.find_by_checksum(sid, "ck1")
    assert carried is not None and carried["dedup_of"] == "a.pdf"
    assert [i for i in carried["issues"] if i.get("hf_provenance") == PROV]
    # …and it survives being written back out under the new name, which is what the caller does.
    store.save_file_result(sid, {**carried, "file": "b.pdf", "checksum": "ck1"},
                           "2026-09-05T00:02:00Z")
    assert [i for i in _issues(store, sid, "b.pdf") if i.get("hf_provenance") == PROV]


def test_no_model_answer_is_persisted_even_when_the_finding_carries_one(store):
    """The bite check for the privacy rule, at the boundary that actually enforces it. A finding
    annotated with the provider's own text must reach the database with the text gone — not
    merely un-rendered."""
    sid = _scan(store)
    f = _file()
    f["issues"][0]["hf_provenance"] = {**PROV, "text": "SECRET-PAGE-CONTENT"}
    store.save_file_result(sid, f, "2026-09-05T00:01:00Z")
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT hf_provenance FROM issue_records WHERE scan_id=%s", (sid,))
        stored = [r["hf_provenance"] for r in store._db.fetchall(cur)]
    assert any(stored), "the escalated row must have stored something"
    assert not any("SECRET-PAGE-CONTENT" in (v or "") for v in stored)
