"""Readiness must be observable BEFORE a scan, not discovered by one failing.

Both conditions here were found the hard way. A worker tier died and the only symptom was a
scan refusing to start, hours later, with a message aimed at an older single-tier topology.
The PDF engine is loaded at runtime from ACP_PDF_ENGINE and, when absent, raised a bare
ModuleNotFoundError partway through analysing a file — which reads as "the scan broke" rather
than "an engine was never installed here".

The shared failure is that neither state was visible until something tried to use it. /readyz
makes both answerable on demand, with enough structure to alert on one without pattern-matching
prose.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store as store_mod  # noqa: E402


class FakeStore:
    """Just enough Store to exercise the heartbeat reader."""

    def __init__(self, beat: str | None):
        self._beat = beat

    def get_setting(self, key, default=None):
        return self._beat if key == "worker_tier_heartbeat" else default

    worker_tier_status = store_mod.Store.worker_tier_status
    worker_tier_alive = store_mod.Store.worker_tier_alive


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def test_a_fresh_heartbeat_is_alive_with_a_small_age():
    st = FakeStore(_iso(seconds=5))
    s = st.worker_tier_status()
    assert s["alive"] is True
    assert s["age_s"] < 60
    assert s["ever_seen"] is True


def test_age_distinguishes_just_died_from_long_gone():
    """The reason a boolean was not enough.

    `worker_tier_alive` answers the scan guard's yes/no and is right to. For alerting it is
    useless: a worker that stopped thirty seconds ago and one gone for a fortnight both read
    "false", and those warrant very different responses.
    """
    recent, ancient = FakeStore(_iso(minutes=3)), FakeStore(_iso(days=14))
    assert recent.worker_tier_alive() is False
    assert ancient.worker_tier_alive() is False          # identical, and unhelpful
    assert recent.worker_tier_status()["age_s"] < ancient.worker_tier_status()["age_s"] / 100


def test_never_started_is_not_the_same_as_stopped():
    """A deploy whose worker tier never came up is a different fault from one that died, and
    an alert should be able to say which."""
    never = FakeStore(None).worker_tier_status()
    assert never["ever_seen"] is False and never["age_s"] is None and never["alive"] is False

    stopped = FakeStore(_iso(hours=2)).worker_tier_status()
    assert stopped["ever_seen"] is True and stopped["age_s"] is not None


def test_a_malformed_heartbeat_is_reported_not_swallowed():
    """A corrupt timestamp is a real fault; it must not read as 'no heartbeat'."""
    s = FakeStore("not-a-timestamp").worker_tier_status()
    assert s["alive"] is False
    assert "unparseable" in s["heartbeat_at"]


def test_naive_timestamps_are_treated_as_utc():
    """The writer stores UTC; a naive value must not be read as local and go wildly stale."""
    naive = (datetime.now(timezone.utc) - timedelta(seconds=10)).replace(tzinfo=None).isoformat()
    assert FakeStore(naive).worker_tier_status()["alive"] is True


def test_pool_size_is_none_for_a_bare_timestamp_and_present_for_a_json_envelope():
    """worker_tier_status()'s new `pool_size` field: None for the old bare-ISO format (a
    worker container that hasn't redeployed onto the JSON envelope yet), and the real
    `core.WORKERS` figure once it has — read straight through this class-level borrow, the
    same path /readyz and GET /jobs both go through."""
    import json as _json
    bare = FakeStore(_iso(seconds=5)).worker_tier_status()
    assert bare["alive"] is True and bare["pool_size"] is None

    enveloped = FakeStore(_json.dumps({"at": _iso(seconds=5), "pool_size": 12})).worker_tier_status()
    assert enveloped["alive"] is True and enveloped["pool_size"] == 12


# ── /readyz ────────────────────────────────────────────────────────────────────────────
def _readyz(monkeypatch, *, beat, local_pool, pdf_ok):
    import core
    from routes import system

    monkeypatch.setattr(core, "WORKERS", local_pool, raising=False)
    monkeypatch.setattr(core, "store", FakeStore(beat), raising=False)
    monkeypatch.setattr(system, "pdf_engine_status",
                        lambda: {"available": pdf_ok, "path": "/x",
                                 "reason": None if pdf_ok else "not importable"})
    return system.readyz()


def test_ready_when_the_worker_tier_beats_and_the_engine_is_present(monkeypatch):
    r = _readyz(monkeypatch, beat=_iso(seconds=5), local_pool=0, pdf_ok=True)
    assert r["ready"] is True and r["degraded"] == []
    assert r["workers"]["can_run_scans"] is True


def test_an_in_process_pool_satisfies_readiness_without_a_heartbeat(monkeypatch):
    """Single-tier deployments run the pool in the API process and never write a heartbeat.
    Readiness is the OR of both tiers — the same call the scan-start guard makes."""
    r = _readyz(monkeypatch, beat=None, local_pool=4, pdf_ok=True)
    assert r["ready"] is True
    assert r["workers"]["can_run_scans"] is True


def test_the_reported_outage_is_visible_before_a_scan_is_attempted(monkeypatch):
    """The incident this exists for: API up, worker tier down, nothing watching."""
    r = _readyz(monkeypatch, beat=_iso(hours=6), local_pool=0, pdf_ok=True)
    assert r["ready"] is False
    assert "no_workers" in r["degraded"]
    assert r["workers"]["age_s"] > 120


def test_a_tier_that_never_started_says_so_distinctly(monkeypatch):
    r = _readyz(monkeypatch, beat=None, local_pool=0, pdf_ok=True)
    assert "worker_tier_never_started" in r["degraded"]
    assert "no_workers" not in r["degraded"]


def test_a_missing_pdf_engine_is_reported_before_a_scan_hits_it(monkeypatch):
    r = _readyz(monkeypatch, beat=_iso(seconds=5), local_pool=0, pdf_ok=False)
    assert r["ready"] is False
    assert r["degraded"] == ["pdf_engine_missing"]
    assert r["engines"]["pdf"]["available"] is False


def test_degraded_reasons_are_machine_readable_tokens(monkeypatch):
    """So a monitor can alert on one condition without parsing a sentence."""
    r = _readyz(monkeypatch, beat=None, local_pool=0, pdf_ok=False)
    assert set(r["degraded"]) == {"worker_tier_never_started", "pdf_engine_missing"}
    for token in r["degraded"]:
        assert token.replace("_", "").isalnum() and token.islower()


# ── /readyz vision-engine readiness (GPU model) ──────────────────────────────────────────
def _mock_vision(monkeypatch, *, available, model="llava:13b", reason=None, zone="local"):
    import ai
    monkeypatch.setattr(ai, "vision_is_available", lambda: available, raising=False)
    monkeypatch.setattr(ai, "vision_unavailable_reason", lambda: reason, raising=False)
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", model, raising=False)
    monkeypatch.setattr(ai, "provenance", lambda: {"zone": zone}, raising=False)


def test_readyz_reports_vision_engine_readiness(monkeypatch):
    """/readyz now carries engines.vision so the GPU/vision model's health is visible where the PDF
    engine's already is — model, zone, and whether it can actually caption."""
    _mock_vision(monkeypatch, available=True, model="llava:13b", zone="cloud")
    r = _readyz(monkeypatch, beat=_iso(seconds=5), local_pool=0, pdf_ok=True)
    v = r["engines"]["vision"]
    assert v["ready"] is True and v["reason"] is None
    assert v["model"] == "llava:13b" and v["zone"] == "cloud"


def test_readyz_flags_a_missing_vision_model_but_does_not_flip_ready(monkeypatch):
    """The exact failure we hit live: a typo'd / not-pulled vision model leaves a 'ready' GPU serving
    no captions. /readyz now surfaces WHY (vision_unavailable_reason names the model + fix). But a
    missing vision model degrades image alt to human review (ADR 0039) — it is NOT a scan-blocking
    fault like a missing PDF engine, so it must not flip top-level ready/degraded."""
    reason = ("the configured vision model 'qwen2.5-vl' is not present at http://gpu "
              "(available: qwen2.5vl:72b, llama3.1:8b)")
    _mock_vision(monkeypatch, available=False, model="qwen2.5-vl", reason=reason)
    r = _readyz(monkeypatch, beat=_iso(seconds=5), local_pool=0, pdf_ok=True)
    v = r["engines"]["vision"]
    assert v["ready"] is False and "not present" in v["reason"] and v["model"] == "qwen2.5-vl"
    # informational only — the deployment is still ready for text/assessment work
    assert r["ready"] is True and r["degraded"] == []


# ── /readyz source readiness (SMB) ───────────────────────────────────────────────────────
_SMB_ENV = ("ACP_SMB_SHARES", "ACP_SMB_DOMAIN", "ACP_SMB_USERNAME",
            "ACP_SMB_PASSWORD", "ACP_SMB_CREDENTIAL_KV")


def test_readyz_reports_smb_source_readiness_and_unconfigured_smb_is_not_a_fault(monkeypatch):
    """The dead-code guard (smb_source.describe_smb_readiness) is now reachable: /readyz carries a
    `sources.smb` block so the Sources UI / a health check can say WHY an SMB scan would be empty
    before one starts. But a Drive/SharePoint-only deployment has no SMB config, and that is NOT a
    readiness fault — it must never flip `ready` or land in `degraded`."""
    for k in _SMB_ENV:
        monkeypatch.delenv(k, raising=False)
    r = _readyz(monkeypatch, beat=_iso(seconds=5), local_pool=0, pdf_ok=True)

    smb = r["sources"]["smb"]
    assert smb["ready"] is False
    assert "shares (ACP_SMB_SHARES)" in smb["missing"]      # names the fix, not just the fault
    # Unconfigured SMB is informational only — the deployment is still fully ready for its sources.
    assert r["ready"] is True and r["degraded"] == []


def test_readyz_smb_becomes_ready_once_shares_and_a_credential_are_configured(monkeypatch):
    """With the shares and a credential source present, the block reports ready — and prefers the
    Key Vault path (the Managed-Identity credential a real VNet deployment uses)."""
    for k in _SMB_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ACP_SMB_SHARES", r"\\fileserver\dept, \\fileserver\phi")
    monkeypatch.setenv("ACP_SMB_CREDENTIAL_KV", "smb-svc-acp")
    r = _readyz(monkeypatch, beat=_iso(seconds=5), local_pool=0, pdf_ok=True)

    smb = r["sources"]["smb"]
    assert smb["ready"] is True and smb["missing"] == []
    assert smb["share_count"] == 2 and smb["credential_source"] == "key_vault"


def test_a_missing_pdf_engine_errors_the_file_instead_of_crashing_the_scan(tmp_path, monkeypatch):
    """The other half: _analyse_pdf imported the engine outside any try/except, so an absent
    engine killed the file with an opaque ModuleNotFoundError. It must degrade to a reported
    error — never to a result that could be scored as passing."""
    import scanner
    monkeypatch.setattr(scanner, "WP", tmp_path / "definitely-not-an-engine")
    # Since ADR 0029 the engine is vendored in-repo, so it IMPORTS — and any earlier test in the
    # run that exercised a PDF leaves it in sys.modules, where a later `import analysers...`
    # succeeds no matter what WP says. Pointing WP at an empty directory is then not enough to
    # reproduce a missing engine, and this test passed alone while failing in the suite.
    # Evict the modules so the absence being asserted is real.
    for mod in [m for m in sys.modules if m.split(".")[0] in ("analysers", "models", "remediation")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    # ...and drop the engine's own path, which _analyse_pdf inserts at position 0 and never removes.
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "pdf-analyser" not in str(p)])
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    out = scanner._analyse_pdf(pdf)
    assert out["succeeded"] is False
    assert out["issues"] == []                       # nothing invented, nothing passed
    assert "PDF engine unavailable" in out["errors"][0]["message"]
    assert "ACP_PDF_ENGINE" in out["errors"][0]["message"]   # names the fix, not just the fault
