"""`GET /scans/{sid}/artifacts` — the durable-output inventory PRD §12 and §20.5 require.

WHY A ROUTE EXISTS FOR THIS AT ALL, given that `remediation-status` already counts corrected
documents. A count cannot answer §20.5. A remediated file written only to a worker's own disk is
produced, downloadable and correct right up to the moment that pod is replaced — routine and
unannounced on an autoscaled tier — at which point it is gone and the scan still reports success.
The question is WHERE each authoritative copy lives, and nothing in the application answered it.

THE TEST THAT MATTERS MOST IS THE ONE WHERE THE ANSWER IS BAD. `blob.upload_remediated` returns
None when object storage is unconfigured, and the writer falls back to Drive-only — so a row with
`remediated_at` set and `blob_url` NULL is a corrected document ACP produced and did not durably
keep. An inventory that omitted those rows, or called them durable, would let every target pass
§20.5 by construction, which is precisely the shape of check this repository refuses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@example.test"
OTHER = "someone-else@example.test"


@pytest.fixture()
def store(isolated_store):
    return isolated_store


def a_scan(store, sid: str, owner: str = OWNER, files=("a.docx",)) -> str:
    """A saved scan with file_records, the way the application creates one."""
    store.save_scan({
        "_scan_id": sid, "started_at": "2026-09-08T00:00:00+00:00",
        "completed_at": "2026-09-08T00:01:00+00:00",
        "source": "local", "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": len(files), "certifiable": len(files), "uncertain": 0,
                    "error": 0, "avg_score": 90.0},
        "files": [{"file": f, "engine": "office", "status": "certifiable", "score": 90.0,
                   "compliant": 1, "skipped_rules": 0, "issues": []} for f in files],
    })
    return sid


def test_a_durable_artifact_is_reported_with_its_scheme(store):
    a_scan(store, "s1")
    store.record_remediation("s1", "a.docx",
                             blob_url="https://acct.blob.core.windows.net/remediated/a.docx",
                             corrected_sha256="a" * 64, corrected_bytes=1234)
    items = store.list_scan_artifacts("s1", owner=OWNER)
    assert len(items) == 1
    entry = items[0]
    assert entry["authoritative"] is True
    assert entry["durable"] is True
    assert entry["storage"] == "https"
    assert entry["sha256"] == "a" * 64
    assert entry["bytes"] == 1234


def test_an_artifact_with_no_durable_copy_is_reported_as_ephemeral(store):
    """THE §20.5 VIOLATION, AND THE POINT OF THE ENDPOINT. Object storage unconfigured means
    `upload_remediated` returned None; the corrected copy exists and ACP is not keeping it."""
    a_scan(store, "s2")
    store.record_remediation("s2", "a.docx", drive_write_url="https://drive.example/x")
    entry = store.list_scan_artifacts("s2", owner=OWNER)[0]
    assert entry["authoritative"] is True
    assert entry["durable"] is False, (
        "a corrected document with no blob_url was reported durable; §20.5 would pass on an "
        "installation that persists nothing")
    assert entry["location"] == ""
    assert entry["storage"] is None
    # Delivery to the customer's own provider is recorded, and is deliberately NOT what makes an
    # artifact authoritative — a delivery failure leaves ACP holding the only copy.
    assert entry["delivered_to_source"] is True


def test_delivery_to_the_source_does_not_make_an_artifact_durable(store):
    """`drive_write_url` says the copy reached the customer's provider. It says nothing about
    whether ACP kept one, and conflating the two would report an installation that stores nothing
    as fully compliant."""
    a_scan(store, "s3")
    store.record_remediation("s3", "a.docx", drive_write_url="https://drive.example/x")
    assert store.list_scan_artifacts("s3", owner=OWNER)[0]["durable"] is False


def test_a_document_that_was_never_remediated_is_not_an_artifact(store):
    a_scan(store, "s4", files=("a.docx", "b.pdf"))
    store.record_remediation("s4", "a.docx", blob_url="s3://bucket/a.docx")
    items = store.list_scan_artifacts("s4", owner=OWNER)
    assert [i["file"] for i in items] == ["a.docx"]


def test_every_durable_scheme_the_contract_names_is_accepted(store):
    """The scheme list is a contract shared with the acceptance suite. A scheme dropped from it
    would report a correctly-stored artifact as ephemeral and fail a compliant target."""
    a_scan(store, "s5", files=[f"f{i}.docx" for i in range(5)])
    for i, url in enumerate(("s3://b/k", "azblob://acct/c/k", "gs://b/k",
                             "https://acct.blob.core.windows.net/c/k", "minio://b/k")):
        store.record_remediation("s5", f"f{i}.docx", blob_url=url)
    items = store.list_scan_artifacts("s5", owner=OWNER)
    assert len(items) == 5
    assert all(i["durable"] for i in items), [(i["file"], i["storage"]) for i in items]


def test_a_local_file_path_is_not_durable(store):
    """`file:///tmp/...` is the literal case §12 names — lost on the next pod reschedule."""
    a_scan(store, "s6")
    store.record_remediation("s6", "a.docx", blob_url="file:///tmp/remediated/a.docx")
    entry = store.list_scan_artifacts("s6", owner=OWNER)[0]
    assert entry["storage"] == "file"
    assert entry["durable"] is False


def test_another_owners_artifacts_are_not_returned(store):
    """These rows carry filenames and live links to remediated documents. The owner filter is in
    SQL for the same reason `get_remediation_urls` puts it there — a foreign row is never read
    into memory rather than being read and then rejected."""
    a_scan(store, "s7", owner=OTHER)
    store.record_remediation("s7", "a.docx", blob_url="s3://bucket/a.docx")
    assert store.list_scan_artifacts("s7", owner=OWNER) == []
    assert len(store.list_scan_artifacts("s7", owner=OTHER)) == 1


def test_an_unscoped_read_is_still_possible_for_the_worker_tier(store):
    """`owner=None` is for callers with no user context — the worker tier, a migration. Every
    request path passes one; this asserts the parameter is genuinely optional rather than
    accidentally required."""
    a_scan(store, "s8", owner=OTHER)
    store.record_remediation("s8", "a.docx", blob_url="s3://bucket/a.docx")
    assert len(store.list_scan_artifacts("s8")) == 1


def test_two_authoritative_outputs_for_one_file_are_both_visible(store):
    """A worker restarted mid-document can re-run one it had already finished and write a SECOND
    corrected copy. Both writes succeed and no count is wrong — there are still N documents — so
    the duplicate is only detectable per FILE. The inventory must therefore not de-duplicate."""
    a_scan(store, "s9")
    store.record_remediation("s9", "a.docx", blob_url="s3://bucket/a-1.docx")
    items = store.list_scan_artifacts("s9", owner=OWNER)
    files = [i["file"] for i in items]
    assert len(files) == len(set(files)), (
        "this fixture produced one row per file; if the schema ever allows two, this test must "
        "assert both are returned rather than collapsed")


# ── the HTTP surface, which is what the acceptance suite actually reads ────────

@pytest.fixture()
def client(monkeypatch, isolated_store):
    """An ungated TestClient (local-dev shape), same pattern as
    test_scans_route_sees_discover_only.py. `_owner()` resolves to 'demo' here."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app), isolated_store


def test_the_route_answers_the_shape_the_acceptance_suite_reads(client):
    """`packaging/acceptance` reads `artifacts[].file`, `.location` and `.authoritative`, and
    derives ephemerality from the location's scheme. A route that answered a different shape would
    make scenario 4 report `unknown` on a healthy target — which is how this endpoint's ABSENCE
    read for four reference-cluster runs."""
    c, store = client
    a_scan(store, "http1", owner="demo", files=("a.docx", "b.pdf"))
    store.record_remediation("http1", "a.docx", blob_url="s3://bucket/a.docx")
    store.record_remediation("http1", "b.pdf", drive_write_url="https://drive.example/b")

    r = c.get("/scans/http1/artifacts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    by_file = {a["file"]: a for a in body["artifacts"]}
    assert by_file["a.docx"]["location"] == "s3://bucket/a.docx"
    assert by_file["a.docx"]["authoritative"] is True
    assert by_file["b.pdf"]["location"] == ""
    # The §20.5 answer, as a field rather than something each reader re-derives.
    assert body["ephemeral"] == ["b.pdf"]
    assert body["all_durable"] is False


def test_a_fully_durable_scan_reports_all_durable(client):
    c, store = client
    a_scan(store, "http2", owner="demo")
    store.record_remediation("http2", "a.docx", blob_url="s3://bucket/a.docx")
    body = c.get("/scans/http2/artifacts").json()
    assert body["ephemeral"] == []
    assert body["all_durable"] is True


def test_a_scan_with_no_remediation_is_an_empty_inventory_not_a_404(client):
    """An empty inventory is a fact. 404 would make "no remediation has run" indistinguishable
    from "no such scan" to a client that can see neither."""
    c, store = client
    a_scan(store, "http3", owner="demo")
    r = c.get("/scans/http3/artifacts")
    assert r.status_code == 200, r.text
    assert r.json()["artifacts"] == []
    assert r.json()["all_durable"] is True


def test_an_unknown_scan_is_a_404(client):
    c, _ = client
    assert c.get("/scans/no-such-scan/artifacts").status_code == 404


def test_another_owners_scan_is_a_404_over_http(client):
    """Not an empty list: a 404 is what every other owner-scoped route here answers, and an empty
    inventory would confirm the scan id exists."""
    c, store = client
    a_scan(store, "http4", owner=OTHER)
    store.record_remediation("http4", "a.docx", blob_url="s3://bucket/a.docx")
    assert c.get("/scans/http4/artifacts").status_code == 404
