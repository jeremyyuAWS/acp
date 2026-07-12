"""AI governance & provenance block in the certification report (ADR 0019 §4/§7).

The report must carry a real, per-scan attestation of AI usage: how many AI-assisted
operations ran, whether any document left the network, and the actual cost — every figure a
measured aggregate of the recorded ai_calls, never a fabricated score (ADR 0016). Three cases
matter: an all-local scan (the $0 / on-network governance headline), a scan with a cloud
escalation (the honest split + real cost), and a scan that used no AI at all.
"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_RUN = {"id": "scan-gov", "completed_at": "2026-07-11T21:00:00", "avg_score": 100, "owner_email": None}
_FILES = [{"file": "deck.pptx", "compliant": 1, "score": 100, "status": "ok", "issues": []}]
_META = {"target": "AA", "version": "1.2", "hash": "deadbeef"}


def _flat(pdf: bytes) -> str:
    from pypdf import PdfReader
    txt = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    return re.sub(r"\s+", " ", txt)


def test_all_local_scan_attests_zero_cost_and_on_network(isolated_store, monkeypatch):
    import core
    from report import build_report
    monkeypatch.setattr(core, "store", isolated_store)
    for _ in range(4):
        isolated_store.record_ai_call(surface="vision", provider="ollama", model="llava:13b",
                                       zone="local", latency_ms=400, ok=True, cost_usd=0.0,
                                       scan_id="scan-gov")
    t = _flat(build_report(_RUN, _FILES, _META))
    assert "AI governance" in t
    assert "processed locally" in t
    assert "$0.00" in t
    # measured count is surfaced, and no fabricated percentage anywhere in the block
    assert "4 AI-assisted operation" in t
    gov = t[t.index("AI governance"):]
    assert not re.search(r"\d+\s*%", gov)


def test_cloud_escalation_splits_local_and_off_network_with_real_cost(isolated_store, monkeypatch):
    import core
    from report import build_report
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.record_ai_call(surface="vision", provider="ollama", model="llava:13b",
                                   zone="local", latency_ms=300, ok=True, cost_usd=0.0, scan_id="scan-gov")
    isolated_store.record_ai_call(surface="vision", provider="openai", model="gpt-4.1",
                                   zone="cloud", latency_ms=900, ok=True, cost_usd=0.03, scan_id="scan-gov")
    t = _flat(build_report(_RUN, _FILES, _META))
    assert "escalated to a cloud provider" in t
    assert "$0.03" in t
    assert "1 openai" in t          # real per-provider breakdown


def test_scan_with_no_ai_states_nothing_was_sent(isolated_store, monkeypatch):
    import core
    from report import build_report
    monkeypatch.setattr(core, "store", isolated_store)
    t = _flat(build_report(_RUN, _FILES, _META))
    assert "No AI-assisted operations were needed" in t
    assert "Nothing was sent to any model" in t


def test_rollup_scan_filter_scopes_to_one_scan(isolated_store):
    s = isolated_store
    s.record_ai_call(surface="vision", provider="ollama", model="m", zone="local",
                     latency_ms=100, ok=True, cost_usd=0.0, scan_id="A")
    s.record_ai_call(surface="vision", provider="openai", model="m", zone="cloud",
                     latency_ms=100, ok=True, cost_usd=0.05, scan_id="B")
    a = s.ai_cost_rollup(scan_id="A")
    assert a["calls"] == 1 and a["cost_usd"] == 0.0
    b = s.ai_cost_rollup(scan_id="B")
    assert b["calls"] == 1 and b["cost_usd"] == 0.05
    assert s.ai_cost_rollup()["calls"] == 2       # unscoped still sees both
