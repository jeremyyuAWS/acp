"""The edition guard over HTTP — the way in, and the route that tells the UI what is offered.

The unit-level reasoning is in test_acr_editions.py. This file is about the wiring: that an
author typing a 508 edition into the metadata form is refused at the PATCH they actually make,
that creation cannot smuggle one in, and that GET /acr/editions is not swallowed by the
`/acr/{report_id}` wildcard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@acp.test"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e == OWNER)

    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {OWNER}"})
    return c


def test_the_editions_route_is_not_shadowed_by_the_report_wildcard(client):
    """`/acr/editions` must be DECLARED before `/acr/{report_id}` — FastAPI matches in order.

    Declared after, the wildcard takes "editions" as a report id and answers 404. That is a silent
    break: no syntax error, no import failure, just a route that stops existing. It has already
    happened in this repo once, to role assignment. Asserting the status code is what catches a
    later edit that moves this route down the file.
    """
    r = client.get("/acr/editions")
    assert r.status_code == 200, r.text
    assert [e["edition"] for e in r.json()["editions"]] == [
        "VPAT 2.5Rev WCAG", "VPAT 2.5Rev 508", "VPAT 2.5Rev EU", "VPAT 2.5Rev INT"]


def test_the_editions_route_says_which_are_offered_and_what_is_missing(client):
    by_name = {e["edition"]: e for e in client.get("/acr/editions").json()["editions"]}
    assert by_name["VPAT 2.5Rev WCAG"]["offered"] is True
    assert by_name["VPAT 2.5Rev WCAG"]["missing"] == []
    assert by_name["VPAT 2.5Rev 508"]["offered"] is True
    assert by_name["VPAT 2.5Rev 508"]["missing"] == []
    assert by_name["VPAT 2.5Rev EU"]["offered"] is False
    assert by_name["VPAT 2.5Rev EU"]["missing"] == ["en-301-549"]
    # INT obliges all three sets; only the one genuinely absent is named.
    assert by_name["VPAT 2.5Rev INT"]["missing"] == ["en-301-549"]


def test_a_new_report_defaults_to_the_wcag_edition(client):
    rid = client.post("/acr", json={"product_version": "1.4.0"}).json()["report_id"]
    assert client.get(f"/acr/{rid}").json()["report"]["vpat_edition"] == "VPAT 2.5Rev WCAG"


def test_creating_a_508_report_is_allowed_and_carries_the_508_rows(client):
    """The other side of #1532: it refused this edition because the rows did not exist. They do.

    Asserted through HTTP and by COUNT rather than by the edition string, because the string is
    the claim and the rows are what make it true — 55 WCAG criteria plus 120 Section 508
    requirements from 36 CFR 1194 Appendix C.
    """
    r = client.post("/acr", json={"product_version": "1.4.0",
                                  "metadata": {"vpat_edition": "VPAT 2.5Rev 508"}})
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]
    rows = client.get(f"/acr/{rid}/criteria").json()["criteria"]
    by_set = {}
    for row in rows:
        by_set[row["requirement_set"]] = by_set.get(row["requirement_set"], 0) + 1
    assert by_set == {"wcag-2.2-aa": 55, "section-508": 120}


def test_creating_an_eu_report_is_refused_and_says_what_is_absent(client):
    r = client.post("/acr", json={"product_version": "1.4.0",
                                  "metadata": {"vpat_edition": "VPAT 2.5Rev EU"}})
    assert r.status_code == 400, r.text
    assert "EN 301 549" in r.json()["detail"]
    assert "VPAT 2.5Rev WCAG" in r.json()["detail"]   # what they CAN pick


def test_the_metadata_form_cannot_patch_an_unoffered_edition(client):
    """The path an author actually takes. Guarding creation alone would leave this open."""
    rid = client.post("/acr", json={"product_version": "1.4.0"}).json()["report_id"]
    r = client.patch(f"/acr/{rid}", json={"fields": {"vpat_edition": "VPAT 2.5Rev EU"}})
    assert r.status_code == 400, r.text
    # And the stored value is untouched — a refused write must not half-apply.
    assert client.get(f"/acr/{rid}").json()["report"]["vpat_edition"] == "VPAT 2.5Rev WCAG"


def test_a_misspelled_edition_is_refused_as_a_typo(client):
    rid = client.post("/acr", json={"product_version": "1.4.0"}).json()["report_id"]
    r = client.patch(f"/acr/{rid}", json={"fields": {"vpat_edition": "VPAT 2.5Rev Section 508"}})
    assert r.status_code == 400, r.text
    assert "is not a VPAT 2.5Rev edition" in r.json()["detail"]


def test_patching_other_metadata_is_unaffected(client):
    rid = client.post("/acr", json={"product_version": "1.4.0"}).json()["report_id"]
    r = client.patch(f"/acr/{rid}", json={"fields": {"vendor_name": "Lyzr"}})
    assert r.status_code == 200, r.text
    assert client.get(f"/acr/{rid}").json()["report"]["vendor_name"] == "Lyzr"


def test_re_setting_the_wcag_edition_is_allowed(client):
    rid = client.post("/acr", json={"product_version": "1.4.0"}).json()["report_id"]
    r = client.patch(f"/acr/{rid}", json={"fields": {"vpat_edition": "VPAT 2.5Rev WCAG"}})
    assert r.status_code == 200, r.text
