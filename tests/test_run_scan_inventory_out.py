"""Regression: run_scan must accept `inventory_out` and thread it into _list.

The local / in-process scan path (handlers._scan, routes/scans.py sync + background) calls
run_scan(..., inventory_out=inv) so it can persist per-file inventory the way the fan-out path
does. run_scan's signature had dropped the parameter, so EVERY local scan crashed with
`run_scan() got an unexpected keyword argument 'inventory_out'`. These pin both the signature
and the pass-through so it cannot silently regress again."""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402


def test_run_scan_accepts_inventory_out():
    params = inspect.signature(scanner.run_scan).parameters
    assert "inventory_out" in params, (
        "run_scan must accept inventory_out — handlers._scan and routes/scans.py pass it; "
        "without it every local/in-process scan raises TypeError")


def test_run_scan_threads_inventory_out_into_list_and_does_not_crash(monkeypatch):
    captured: dict = {}

    def fake_list(source, svc=None, **kw):
        captured.update(kw)
        io = kw.get("inventory_out")
        if io is not None:                       # the fan-out contract: _list fills the estate rows
            io.append({"file": "movie.mp4", "doc_class": "media"})
        return []                                # no scannable items → no download/analyse needed

    monkeypatch.setattr(scanner, "_list", fake_list)
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: None)

    inv: list = []
    report = scanner.run_scan("local", inventory_out=inv)   # must NOT raise TypeError

    assert "inventory_out" in captured                       # threaded into _list
    assert inv == [{"file": "movie.mp4", "doc_class": "media"}]   # and populated for the caller
    assert isinstance(report, dict) and "summary" in report
