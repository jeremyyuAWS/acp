"""Core-17 code-set catalog + the read-only /assess/eligibility preview (Phase C2).

Two things under test, both additive and read-only:

  * `wcag_codeset.core17_catalog()` — the 17 selectable criteria a UI renders, each with
    its human title and the formats it has an assessment lane for.
  * `GET /assess/eligibility` — how many discovered files are eligible for a selected
    code-set, read off the latest discovery run's persisted estate inventory. It must
    count correctly for the default and a subset, and it must return ZEROS (never a 500)
    when no discovery run exists.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import assessment_policy as policy
import estate_inventory
import wcag_codeset


# ── The catalog helper ────────────────────────────────────────────────────────────────
def test_catalog_has_all_seventeen_core_codes():
    cat = wcag_codeset.core17_catalog()
    assert len(cat) == 17
    codes = [e["code"] for e in cat]
    assert codes == sorted(policy.MOVA_TRACKED)          # exactly the Core 17, sorted
    assert codes == sorted(codes)


def test_catalog_entries_carry_name_and_derived_formats():
    by_code = {e["code"]: e for e in wcag_codeset.core17_catalog()}

    # A stable, human-readable title on every entry.
    assert by_code["1.4.3"]["name"] == "Contrast (Minimum)"
    assert all(e["name"] and e["name"] != e["code"] for e in by_code.values())

    # Formats are DERIVED from the acp-core-17 scope preset, not invented.
    preset = policy.SCOPE_PRESETS["acp-core-17"]
    for code, entry in by_code.items():
        assert entry["formats"] == sorted(preset[code])
        assert entry["formats"] == sorted(set(entry["formats"]))   # deduped + sorted

    # A per-format asymmetry the flat "17x4" grid would get wrong: 2.1.1 is pptx-only.
    assert by_code["2.1.1"]["formats"] == ["pptx"]


def test_names_track_the_server_rule_catalog():
    """Titles come from RULE_CATALOG (the single source of truth), not a private copy."""
    rule_names = {r["id"]: r["name"] for r in policy.RULE_CATALOG}
    for entry in wcag_codeset.core17_catalog():
        assert entry["name"] == rule_names[entry["code"]]


def test_parse_codes_defaults_to_core17_and_drops_unknowns():
    assert wcag_codeset.parse_codes(None) == sorted(policy.MOVA_TRACKED)
    assert wcag_codeset.parse_codes("  ") == sorted(policy.MOVA_TRACKED)
    # A subset stays a subset; junk and non-Core-17 codes are ignored.
    assert wcag_codeset.parse_codes("1.4.3, 2.4.6") == ["1.4.3", "2.4.6"]
    assert wcag_codeset.parse_codes("1.4.3, bogus, 9.9.9") == ["1.4.3"]
    # 2.4.7 is a real WCAG SC but NOT in the Core 17 — dropped.
    assert wcag_codeset.parse_codes("2.4.7") == sorted(policy.MOVA_TRACKED)


# ── The eligibility projection (pure, no HTTP) ────────────────────────────────────────
def _inventory(files):
    """An estate_inventory.summarize() snapshot for a list of raw Drive files."""
    return estate_inventory.summarize(files)


_SAMPLE_ESTATE = [
    {"id": "a", "name": "report.docx", "mimeType": ""},
    {"id": "b", "name": "budget.xlsx", "mimeType": ""},
    {"id": "c", "name": "deck.pptx", "mimeType": ""},
    {"id": "d", "name": "manual.pdf", "mimeType": ""},
    {"id": "e", "name": "logo.png", "mimeType": "image/png"},      # metadata-only
    {"id": "f", "name": "notes.txt", "mimeType": "text/plain"},     # unsupported
]


def test_eligibility_default_counts_every_document_format():
    inv = _inventory(_SAMPLE_ESTATE)
    out = wcag_codeset.eligibility(inv)          # default = Core 17
    assert out["discovered"] == 6
    # docx/xlsx/pptx/pdf are all reachable by some Core-17 code; image + txt are not.
    assert out["eligible"] == 4
    assert out["by_format"] == {"docx": 1, "pdf": 1, "pptx": 1, "xlsx": 1}
    assert out["formats"] == ["docx", "pdf", "pptx", "xlsx"]


def test_eligibility_subset_narrows_to_that_codes_formats():
    inv = _inventory(_SAMPLE_ESTATE)
    # 2.1.1 Keyboard has only a pptx lane, so only the .pptx file is eligible.
    out = wcag_codeset.eligibility(inv, ["2.1.1"])
    assert out["eligible"] == 1
    assert out["by_format"] == {"pptx": 1}
    assert out["formats"] == ["pptx"]
    # The per-code reflection shows the lane and how many files it reaches.
    assert out["codes"] == [{"code": "2.1.1", "name": "Keyboard",
                             "formats": ["pptx"], "eligible": 1}]


def test_eligibility_empty_inventory_is_zeros_not_error():
    for empty in (None, {}, {"discovered": 0, "by_format": {}}):
        out = wcag_codeset.eligibility(empty)
        assert out["discovered"] == 0
        assert out["eligible"] == 0
        assert out["by_format"] == {}
        assert out["formats"] == ["docx", "pdf", "pptx", "xlsx"]   # lanes exist; files don't
        assert len(out["codes"]) == 17


# ── The HTTP endpoint ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(monkeypatch, isolated_store):
    """A TestClient with the access gate OFF (owner resolves to 'demo')."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app), isolated_store


def _seed_discovery(store, sid: str, owner: str, files: list[dict],
                    completed_at: str = "2026-08-18T10:05:00+00:00") -> None:
    """A finalized scan whose scope carries an estate inventory, exactly as a real
    discovery run persists it (scanner writes estate_inventory.summarize() to scope)."""
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-08-18T10:00:00+00:00",
        "completed_at": completed_at,
        "source": "drive",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "scope": {"kind": "drive", "inventory": estate_inventory.summarize(files)},
        "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    })


def _seed_per_file(store, sid: str, rows: list[dict]) -> None:
    """Per-file scan_inventory rows (store.add_inventory), so the endpoint can read each file's
    lifecycle_status. `rows` — dicts with `file` (+ optional `mime`); a `status` key, if present,
    is applied via set_lifecycle_status after insert (the store defaults every row to Active)."""
    store.add_inventory(sid, [{"file": r["file"], "mime": r.get("mime", ""),
                               "doc_class": r.get("doc_class", "")} for r in rows])
    for r in rows:
        if r.get("status"):
            store.set_lifecycle_status(sid, r["file"], r["status"])


def test_endpoint_reports_lifecycle_exclusion(client):
    """Files a discovery rule flagged for archival/deletion are counted, so the Assess scope
    preview can show how many the default 'ignore archival/deletion' excludes (Deva #6)."""
    c, store = client
    files = [{"id": "a", "name": "report.docx", "mimeType": ""},
             {"id": "b", "name": "old.pdf", "mimeType": ""},
             {"id": "c", "name": "deck.pptx", "mimeType": ""}]
    _seed_discovery(store, "scan01", "demo", files)
    _seed_per_file(store, "scan01", [
        {"file": "report.docx"},                             # Active — not flagged
        {"file": "old.pdf", "status": "Archive Candidate"},  # flagged
        {"file": "deck.pptx", "status": "Delete Candidate"}, # flagged
    ])
    body = c.get("/assess/eligibility").json()
    assert body["lifecycle_excluded"] == 2
    assert body["lifecycle_eligible_excluded"] == 2         # both flagged files are assessable formats


def test_endpoint_lifecycle_zero_without_per_file_inventory(client):
    """A summarize-only estate (no per-file rows) reports zero exclusion, never a 500."""
    c, store = client
    _seed_discovery(store, "scan01", "demo", _SAMPLE_ESTATE)
    body = c.get("/assess/eligibility").json()
    assert body["lifecycle_excluded"] == 0
    assert body["lifecycle_eligible_excluded"] == 0


def test_endpoint_default_reports_eligible_count(client):
    c, store = client
    _seed_discovery(store, "scan01", "demo", _SAMPLE_ESTATE)
    res = c.get("/assess/eligibility")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["discovered"] == 6
    assert body["eligible"] == 4
    assert body["by_format"] == {"docx": 1, "pdf": 1, "pptx": 1, "xlsx": 1}
    assert len(body["codes"]) == 17


def test_endpoint_honours_codes_query(client):
    c, store = client
    _seed_discovery(store, "scan01", "demo", _SAMPLE_ESTATE)
    res = c.get("/assess/eligibility", params={"codes": "2.1.1"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["eligible"] == 1
    assert body["by_format"] == {"pptx": 1}
    assert [x["code"] for x in body["codes"]] == ["2.1.1"]


def test_endpoint_no_discovery_run_is_zeros(client):
    c, _ = client
    res = c.get("/assess/eligibility")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["discovered"] == 0
    assert body["eligible"] == 0
    assert body["by_format"] == {}


def test_endpoint_uses_latest_discovery(client):
    """Two runs; the newest estate wins (list_scans is newest-first)."""
    c, store = client
    _seed_discovery(store, "scan_old", "demo", [{"id": "a", "name": "one.docx", "mimeType": ""}],
                    completed_at="2026-08-18T09:00:00+00:00")
    _seed_discovery(store, "scan_new", "demo", _SAMPLE_ESTATE,
                    completed_at="2026-08-18T10:05:00+00:00")
    body = c.get("/assess/eligibility").json()
    assert body["discovered"] == 6


def _seed_discover_only_scan(store, sid: str, owner: str, files: list[dict],
                             started_at: str = "2026-08-21T16:00:00+00:00") -> None:
    """A REAL ADR 0020 Discover-only scan — status='discovered', completed_at NEVER set — built
    the same way handlers._scan_discover actually creates one (init_scan_run with status=
    'discovered' and a scope dict, then add_inventory for the per-file rows), not save_scan
    (which hardcodes status='done' and always wants a completed_at — the wrong shape for this
    exact case)."""
    import estate_inventory as ei
    store.init_scan_run(sid, "drive", len(files), started_at, "wcag-aa", "h", owner=owner,
                        status="discovered", scope={"kind": "drive", "inventory": ei.summarize(files)})
    store.add_inventory(sid, [{"file": f["name"]} for f in files])


def test_endpoint_sees_a_never_assessed_discover_only_scan(client):
    """THE regression: found live 2026-08-21 on a real 170-file account that had only ever run
    Discover — /assess/eligibility reported "0 documents will be opened and scored" because
    _latest_inventory/_latest_scan_id_with_inventory both went through list_scans(), which
    filters to completed_at IS NOT NULL and therefore cannot see a scan that is genuinely done
    with discovery but has never been assessed (completed_at stays NULL forever under ADR 0020,
    same as an in-flight scan — the two are indistinguishable to that filter)."""
    c, store = client
    _seed_discover_only_scan(store, "scan01", "demo", _SAMPLE_ESTATE)
    res = c.get("/assess/eligibility")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["discovered"] == 6
    assert body["eligible"] == 4
    assert body["by_format"] == {"docx": 1, "pdf": 1, "pptx": 1, "xlsx": 1}


def test_a_discover_only_scan_still_reports_lifecycle_exclusion(client):
    """_latest_scan_id_with_inventory (the per-file half) must also see the discover-only scan —
    this is what makes lifecycle_excluded/lifecycle_eligible_excluded work pre-Assess too."""
    c, store = client
    files = [{"id": "a", "name": "report.docx", "mimeType": ""},
             {"id": "b", "name": "old.pdf", "mimeType": ""}]
    store.init_scan_run("scan01", "drive", len(files), "2026-08-21T16:00:00+00:00", "wcag-aa", "h",
                        owner="demo", status="discovered",
                        scope={"kind": "drive", "inventory": estate_inventory.summarize(files)})
    _seed_per_file(store, "scan01", [
        {"file": "report.docx"},
        {"file": "old.pdf", "status": "Archive Candidate"},
    ])
    body = c.get("/assess/eligibility").json()
    assert body["lifecycle_excluded"] == 1
    assert body["lifecycle_eligible_excluded"] == 1


def test_an_assessed_scan_still_wins_over_an_older_discover_only_one(client):
    """The fix must not make a stale discover-only scan outrank a genuinely newer, assessed one —
    ordering is COALESCE(completed_at, discovered_at, started_at), so a later completed_at wins."""
    c, store = client
    _seed_discover_only_scan(store, "scan_old", "demo",
                             [{"id": "a", "name": "one.docx", "mimeType": ""}],
                             started_at="2026-08-18T09:00:00+00:00")
    _seed_discovery(store, "scan_new", "demo", _SAMPLE_ESTATE,
                    completed_at="2026-08-21T10:05:00+00:00")
    body = c.get("/assess/eligibility").json()
    assert body["discovered"] == 6   # the newer, assessed scan's estate — not the older one


def test_codeset_catalog_endpoint(client):
    c, _ = client
    body = c.get("/assess/codeset").json()
    assert len(body["codes"]) == 17
    entry = {e["code"]: e for e in body["codes"]}["1.4.3"]
    assert entry["name"] == "Contrast (Minimum)"
    assert entry["formats"] == ["docx", "pdf", "pptx", "xlsx"]
