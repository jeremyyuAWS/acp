"""Discover-phase tracing (ADR 0020).

THE GAP. `lf.discover_span` hangs a "Discover" span on a file's trace, which reads like the
Discover phase is traced. It is not: its only caller is `handlers._analyse_and_persist_one`, on
the ANALYSE path — and under ADR 0020 that path runs at ASSESS time. `_scan_discover`, the
handler that lists the source, persists the inventory, evaluates lifecycle rules and stops,
emitted nothing at all. A Discover-only run produced no trace to open, and the estate rows that
are inventoried and never assessed were invisible permanently, because nothing later opens them.

What is pinned here:

  * the module is a no-op without credentials — `lf` is imported everywhere and must never
    require the package or the env, so the "off" case is tested first and separately;
  * a discovery emits a RUN trace carrying its counts WITH the boundary they were counted
    within, and the truncation flag;
  * per-file Discover spans are emitted from the INVENTORY, so a file that is never assessed
    still has one;
  * the per-file cap is STATED, not silent — the run trace records how many spans were emitted
    beside how many files were inventoried, so a reader can see the difference rather than
    conclude the estate is smaller than it is;
  * a tracing failure never breaks discovery, which is the only reason it is safe to call this
    after the inventory is already written.
"""
import sys, importlib
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _reload_lf(monkeypatch, **env):
    """lf reads its config at import time, so the env has to be set before the reload."""
    for k in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
              "ACP_TRACE_DISCOVER_FILES", "ACP_TRACE_FILENAMES"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import lf
    return importlib.reload(lf)


class FakeSpan:
    def __init__(self, **kw): self.kw = kw; self.ended = False
    def end(self, **_): self.ended = True


class FakeTrace:
    def __init__(self, **kw):
        self.id = kw.get("id"); self.kw = kw; self.spans = []
    def span(self, **kw):
        s = FakeSpan(**kw); self.spans.append(s); return s
    def update(self, **_): return self
    def end(self, **_): return self


class FakeClient:
    def __init__(self): self.traces = []
    def trace(self, **kw):
        t = FakeTrace(**kw); self.traces.append(t); return t
    def flush(self): pass


@pytest.fixture()
def lf_on(monkeypatch):
    lf = _reload_lf(monkeypatch, LANGFUSE_HOST="http://lf", LANGFUSE_PUBLIC_KEY="pk",
                    LANGFUSE_SECRET_KEY="sk")
    fake = FakeClient()
    monkeypatch.setattr(lf, "_lf", lambda: fake)
    return lf, fake


INV = [{"file": f"doc{i}.docx", "doc_class": "docx", "size_kb": 10 + i} for i in range(5)]


# ── off by default ───────────────────────────────────────────────────────────

def test_no_credentials_means_no_ops_not_errors(monkeypatch):
    """lf is imported by scanner, handlers, core, ai and pii. If the off path raised — or
    required the langfuse package — every one of those would break on a plain checkout."""
    lf = _reload_lf(monkeypatch)
    assert lf._ENABLED is False
    assert lf.discover_file_spans("s1", INV, user="alex") == 0
    trace = lf.discover_run_trace("s1", "drive", listed=5, inventoried=5)
    assert isinstance(trace, lf._Noop)
    trace.span().update().end()          # the _Noop contract: chainable, never raises


# ── the run trace ────────────────────────────────────────────────────────────

def test_a_discovery_emits_a_run_trace_with_its_counts(lf_on):
    lf, fake = lf_on
    lf.discover_run_trace("s1", "sharepoint", listed=12486, inventoried=12486,
                          scope={"kind": "drive"}, user="alex", file_spans_emitted=500)
    t = fake.traces[-1]
    assert t.kw["session_id"] == "s1"
    assert "Discover" in t.kw["name"] and "SharePoint" in t.kw["name"]
    assert t.kw["output"]["files_listed"] == 12486
    assert t.kw["metadata"]["phase"] == "discover"


def test_the_count_carries_the_boundary_it_was_counted_within(lf_on):
    """"12,486 files" and "12,486 files in /Finance" are different facts. A trace that records
    only the first cannot tell them apart afterwards — the same reason the UI never renders a
    count without its scope."""
    lf, fake = lf_on
    lf.discover_run_trace("s1", "drive", listed=40, inventoried=40,
                          scope={"kind": "folder", "folder": "Finance"})
    inp = fake.traces[-1].kw["input"]
    assert inp["kind"] == "folder" and inp["folder"] == "Finance"


def test_truncation_reaches_the_trace(lf_on):
    lf, fake = lf_on
    lf.discover_run_trace("s1", "drive", listed=5000, inventoried=5000,
                          scope={"kind": "drive", "truncated": True})
    assert fake.traces[-1].kw["output"]["truncated"] is True


def test_the_run_trace_id_is_deterministic(lf_on):
    """A worker retry must update the one trace, not add a sibling."""
    lf, fake = lf_on
    lf.discover_run_trace("s1", "drive", listed=1, inventoried=1)
    lf.discover_run_trace("s1", "drive", listed=1, inventoried=1)
    assert fake.traces[0].kw["id"] == fake.traces[1].kw["id"]


# ── per-file spans ───────────────────────────────────────────────────────────

def test_every_inventoried_file_gets_a_discover_span(lf_on):
    """From the INVENTORY, not the assessable subset — a file that is never opened still has a
    Discover span, which is the whole point."""
    lf, fake = lf_on
    assert lf.discover_file_spans("s1", INV, user="alex") == 5
    spans = [s for t in fake.traces for s in t.spans]
    assert len(spans) == 5
    assert all(s.kw["name"] == "Discover" for s in spans)
    assert all(s.kw["input"]["opened"] is False for s in spans)
    assert spans[0].kw["output"]["doc_class"] == "docx"


def test_the_span_id_is_deterministic_per_file(lf_on):
    lf, fake = lf_on
    lf.discover_file_spans("s1", INV[:1])
    lf.discover_file_spans("s1", INV[:1])
    ids = [s.kw["id"] for t in fake.traces for s in t.spans]
    assert ids[0] == ids[1]


def test_the_cap_bounds_the_spans_and_is_reported_not_silent(lf_on, monkeypatch):
    """A cap nobody can see is indistinguishable from a small estate — so the emitted count is
    returned for the run trace to carry beside files_inventoried."""
    lf, fake = lf_on
    monkeypatch.setenv("ACP_TRACE_DISCOVER_FILES", "2")
    emitted = lf.discover_file_spans("s1", INV)
    assert emitted == 2
    lf.discover_run_trace("s1", "drive", listed=5, inventoried=5, file_spans_emitted=emitted)
    out = fake.traces[-1].kw["output"]
    assert (out["file_spans_emitted"], out["files_inventoried"]) == (2, 5)


def test_per_file_spans_can_be_turned_off_entirely(lf_on, monkeypatch):
    lf, _ = lf_on
    monkeypatch.setenv("ACP_TRACE_DISCOVER_FILES", "0")
    assert lf.discover_file_spans("s1", INV) == 0


def test_a_bad_cap_value_falls_back_rather_than_crashing_discovery(lf_on, monkeypatch):
    lf, _ = lf_on
    monkeypatch.setenv("ACP_TRACE_DISCOVER_FILES", "not-a-number")
    assert lf.discover_file_spans("s1", INV) == 5


def test_a_filename_is_not_put_in_the_trace_by_default(lf_on):
    """The PHI rule lf._doc_label exists for applies here too — Discover is the phase that sees
    EVERY filename in the estate, including the ones Assess never opens."""
    lf, fake = lf_on
    lf.discover_file_spans("s1", [{"file": "Smith_John_MRN0114233_intake.docx", "doc_class": "docx"}])
    blob = repr([t.kw for t in fake.traces])
    assert "MRN0114233" not in blob and "Smith_John" not in blob
    assert ".docx" in blob


# ── failure containment ──────────────────────────────────────────────────────

def test_one_files_tracing_failure_does_not_stop_the_rest(lf_on, monkeypatch):
    lf, fake = lf_on
    calls = {"n": 0}
    real = fake.trace

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("langfuse hiccup")
        return real(**kw)
    monkeypatch.setattr(fake, "trace", flaky)
    assert lf.discover_file_spans("s1", INV) == 4     # 5 attempted, 1 lost, none fatal


def test_a_dead_client_never_raises_into_discovery(lf_on, monkeypatch):
    lf, fake = lf_on
    monkeypatch.setattr(fake, "trace", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
    assert lf.discover_file_spans("s1", INV) == 0
    assert isinstance(lf.discover_run_trace("s1", "drive", listed=1, inventoried=1), lf._Noop)


# ── the wiring, which is the actual gap ──────────────────────────────────────
#
# Everything above tests lf.py in isolation. The defect was never in lf.py — `discover_span` had
# existed all along. It was that `_scan_discover` never called anything. So the test that would
# have caught this is one that drives the real handler and asserts a trace came out.

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _items():
    return [
        {"name": "old.docx", "id": "d-old", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Archive/old.docx", "parent_folder": "/Archive", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c-old"},
        {"name": "clip.mp4", "id": "d-clip", "mime": "video/mp4", "source_mime": "video/mp4",
         "path": "/Media/clip.mp4", "parent_folder": "/Media", "owner": "cfo@x.com",
         "created_at": "2020-01-01T00:00:00+00:00", "source_modified": "2020-01-01T00:00:00+00:00",
         "size_kb": 90000, "checksum": "c-clip"},
    ]


def test_a_discover_only_run_now_produces_a_trace(isolated_store, monkeypatch):
    """The regression that matters: before this, running Discover under ADR 0020 emitted nothing
    to Langfuse at all — not a thin trace, nothing to open."""
    import core, scanner, handlers
    lf = _reload_lf(monkeypatch, LANGFUSE_HOST="http://lf", LANGFUSE_PUBLIC_KEY="pk",
                    LANGFUSE_SECRET_KEY="sk")
    fake = FakeClient()
    monkeypatch.setattr(lf, "_lf", lambda: fake)
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())

    handlers._scan_discover({"scan_id": "s1", "source": "local", "user": "admin@x.com"},
                            {"scan_id": "s1"})

    run = [t for t in fake.traces if "Discover ·" in (t.kw.get("name") or "")]
    assert len(run) == 1, "a Discover-only run must emit exactly one run trace"
    out = run[0].kw["output"]
    # BOTH rows, not just the assessable one: the .mp4 is inventoried and never opened, and it is
    # precisely the kind of row that was invisible in tracing before.
    assert out["files_inventoried"] == 2
    assert out["file_spans_emitted"] == 2
    spans = [s for t in fake.traces for s in t.spans]
    # classify_from_metadata's own vocabulary, taken from the classifier rather than assumed:
    # a .docx is a 'text-document', a .mp4 is 'unknown'. The point is that the span carries the
    # classification LISTING produced, with no file opened.
    assert {s.kw["output"]["doc_class"] for s in spans} == {"text-document", "unknown"}


def test_discovery_still_completes_when_tracing_is_dead(isolated_store, monkeypatch):
    """The inventory is already persisted when tracing runs, so a Langfuse outage must cost
    tracing and nothing else."""
    import core, scanner, handlers
    lf = _reload_lf(monkeypatch, LANGFUSE_HOST="http://lf", LANGFUSE_PUBLIC_KEY="pk",
                    LANGFUSE_SECRET_KEY="sk")
    monkeypatch.setattr(lf, "_lf", lambda: (_ for _ in ()).throw(RuntimeError("langfuse down")))
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())

    handlers._scan_discover({"scan_id": "s1", "source": "local", "user": "admin@x.com"},
                            {"scan_id": "s1"})
    assert len(isolated_store.list_inventory("s1")) == 2, "the inventory must survive a tracing failure"
