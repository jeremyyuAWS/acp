"""Estate inventory — every discovered file is classified, and discovery reports the whole estate.

The product rule these pin (customer ask, 2026-08-17): discover EVERYTHING, assess/remediate only
what ACP supports, and never let "unsupported" read as "passed". So discovery must count the whole
estate by format and capability status, while the scan itself still touches only scannable formats.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import estate_inventory as inv  # noqa: E402
import scanner  # noqa: E402

DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF = "application/pdf"
GDOC = "application/vnd.google-apps.document"
FOLDER = "application/vnd.google-apps.folder"


def _f(fid, name, mime, **extra):
    return {"id": fid, "name": name, "mimeType": mime, **extra}


# ── classify ────────────────────────────────────────────────────────────────────────────────
def test_supported_formats_are_assessable():
    for name, mime, fmt in [
        ("a.docx", DOC, "docx"),
        ("b.pdf", PDF, "pdf"),
        ("c.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
        ("d.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ]:
        r = inv.classify(_f("1", name, mime))
        assert r["format"] == fmt and r["status"] == inv.ASSESSABLE, r


def test_html_is_out_of_scope_by_default_but_still_classified_as_html():
    """HTML is outside the PDF/DOCX/XLSX/PPTX scan scope but retains its inventory format.

    The format bucket is unchanged — an .html file is still recognised AS html, and the estate
    inventory still counts it — but it is no longer `assessable`, because no listing will produce
    it for Assess to receive. This assertion used to live in the loop above and is broken out so
    the change is a statement rather than a deletion.
    """
    r = inv.classify(_f("1", "e.html", "text/html"))
    assert r["format"] == "html"
    assert r["status"] == inv.UNSUPPORTED


def test_assessable_follows_the_configured_scan_scope(monkeypatch):
    """The capability status is DERIVED from the scan scope, not written down beside it.

    The bite check for scan_formats' whole reason to exist: put HTML back in scope and the same
    file must become assessable again, with no other edit anywhere. If this passes while
    `_status_of` holds its own literal list, the two have silently drifted — which is the failure
    (an inflated assessment-eligible denominator) the module was created to make impossible.
    """
    html = _f("1", "e.html", "text/html")
    assert inv.classify(html)["status"] == inv.UNSUPPORTED

    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf,docx,xlsx,pptx,html")
    assert inv.classify(html)["status"] == inv.ASSESSABLE

    # And narrowing further takes a format out in the same breath.
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf")
    assert inv.classify(_f("2", "a.docx", DOC))["status"] == inv.UNSUPPORTED
    assert inv.classify(_f("3", "b.pdf", PDF))["status"] == inv.ASSESSABLE


def test_google_native_assesses_as_its_export_format():
    r = inv.classify(_f("1", "Untitled", GDOC))   # a Google Doc has no useful name suffix
    assert r["format"] == "docx" and r["status"] == inv.ASSESSABLE


def test_images_and_av_are_metadata_only():
    assert inv.classify(_f("1", "logo.png", "image/png"))["status"] == inv.METADATA_ONLY
    assert inv.classify(_f("2", "clip.mp4", "video/mp4"))["status"] == inv.METADATA_ONLY
    assert inv.classify(_f("3", "call.mp3", "audio/mpeg"))["status"] == inv.METADATA_ONLY
    # extension-only fallback when Drive typed it octet-stream
    assert inv.classify(_f("4", "scan.jpeg", "application/octet-stream"))["format"] == "image"


def test_other_formats_are_unsupported():
    for name in ("notes.txt", "data.csv", "bundle.zip", "legacy.doc"):
        r = inv.classify(_f("1", name, "application/octet-stream"))
        assert r["status"] == inv.UNSUPPORTED, r


def test_acp_generated_is_excluded_regardless_of_format():
    r = inv.classify(_f("1", "fixed.docx", DOC, _excluded=True))
    assert r["status"] == inv.EXCLUDED   # ACP's own output is not the user's estate


# ── summarize ────────────────────────────────────────────────────────────────────────────────
def test_summary_flags_truncation_so_a_capped_estate_is_never_reported_complete():
    files = [_f("1", "a.docx", DOC)]
    assert inv.summarize(files)["truncated"] is False              # default: complete
    assert inv.summarize(files, truncated=True)["truncated"] is True  # capped: a floor, say so


def test_summary_counts_by_format_and_status_and_drops_folders():
    files = [
        _f("1", "a.docx", DOC), _f("2", "b.docx", DOC), _f("3", "c.pdf", PDF),
        _f("4", "logo.png", "image/png"), _f("5", "clip.mp4", "video/mp4"),
        _f("6", "notes.txt", "text/plain"),
        _f("7", "Sub", FOLDER),   # a folder is not content — must not be counted
    ]
    s = inv.summarize(files)
    assert s["discovered"] == 6                      # folder excluded
    assert s["assessment_eligible"] == 3             # 2 docx + 1 pdf
    assert s["by_format"] == {"docx": 2, "pdf": 1, "image": 1, "av": 1, "other": 1}
    assert s["by_status"] == {inv.ASSESSABLE: 3, inv.METADATA_ONLY: 2, inv.UNSUPPORTED: 1}


def test_summary_samples_the_files_behind_each_status_capped_with_true_totals():
    # The drill-down needs the actual files behind a count, but the sample is a CAP — by_status stays
    # the true total so the UI shows "N of <total>" and an unsupported bucket of thousands is never
    # mistaken for the handful sampled.
    files = [_f(str(i), f"u{i}.txt", "text/plain") for i in range(5)]  # 5 unsupported
    files.append(_f("d", "a.docx", DOC))                               # 1 assessable
    s = inv.summarize(files, sample_per_status=3)
    assert s["sample_cap"] == 3
    assert s["by_status"][inv.UNSUPPORTED] == 5                        # true total, uncapped
    assert len(s["samples"][inv.UNSUPPORTED]) == 3                     # sample capped at 3
    assert len(s["samples"][inv.ASSESSABLE]) == 1                      # whole bucket fits
    row = s["samples"][inv.ASSESSABLE][0]                              # carries what the list renders
    assert row["name"] == "a.docx" and row["format"] == "docx" and "id" in row


def test_sample_rows_carry_triage_metadata_for_the_drilldown():
    # size / owner / shared let the drill-down sort biggest-first and flag externally-visible files.
    f = _f("1", "big.pdf", PDF, size="10485760",
           owners=[{"displayName": "Dr. Vega", "emailAddress": "vega@hosp.org"}], shared=True)
    row = inv.summarize([f])["samples"][inv.ASSESSABLE][0]
    assert row["size"] == 10485760        # Drive gives size as a string; coerced to int for sorting
    assert row["owner"] == "Dr. Vega"     # displayName preferred over email
    assert row["shared"] is True


def test_sample_metadata_never_becomes_a_wrong_value_when_absent_or_garbage():
    g = _f("2", "x.pdf", PDF, size="not-a-number")   # unparseable size, no owners, no shared
    row = inv.summarize([g])["samples"][inv.ASSESSABLE][0]
    assert row["size"] is None and row["owner"] is None and row["shared"] is False


# ── discovery integration: report the whole estate, scan only the scannable ───────────────────
class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self, **kw):
        return self._payload


class _FakeFiles:
    def __init__(self, rows):
        self._rows = rows

    def list(self, **kw):
        if "trashed=false" in kw.get("q", "") and kw.get("pageToken") is None:
            return _Exec({"files": self._rows})
        return _Exec({"files": []})


class _FakeSvc:
    def __init__(self, rows):
        self._files = _FakeFiles(rows)

    def files(self):
        return self._files


def test_run_scan_drive_path_honours_the_configured_estate_ceiling():
    """Wiring pin: run_scan's whole-Drive _list call must pass max_files=FANOUT_MAX_FILES, not fall
    back to _search_drive's 500-file default. A 30k-file estate covered ~500 deep — while the
    "raise ACP_FANOUT_MAX_FILES" hint points at a knob that never reached this path — is the failure
    this prevents. Source-level, matching the guard style the repo uses for handlers._scan_discover;
    a mount of run_scan would need the whole rubric/store/token fixture stack."""
    import re
    src = (Path(__file__).resolve().parent.parent / "api" / "scanner.py").read_text()
    m = re.search(r"items = _list\(source, svc,.*?\)", src, re.S)
    assert m, "run_scan's _list call was not found — did it move?"
    assert "max_files=FANOUT_MAX_FILES" in m.group(0), \
        "run_scan must pass max_files=FANOUT_MAX_FILES to _list, else the whole-Drive scan caps at 500"


def test_discovery_inventories_all_but_scans_only_scannable():
    rows = (
        [_f(f"d{i}", f"Brief-{i}.docx", DOC) for i in range(4)]
        + [_f("p1", "Policy.pdf", PDF)]
        + [_f(f"img{i}", f"photo-{i}.png", "image/png") for i in range(3)]
        + [_f("v1", "training.mp4", "video/mp4")]
        + [_f("z1", "archive.zip", "application/zip")]
    )
    svc = _FakeSvc(rows)
    scope: dict = {}
    items = scanner._list("drive", svc, folder=None, scope_out=scope)

    # The scan still ingests only the 5 scannable documents…
    assert len(items) == 5
    assert scope["scannable"] == 5
    # …but the inventory sees the whole estate of 10 files (4 docx + 1 pdf + 3 png + 1 mp4 + 1 zip).
    inventory = scope["inventory"]
    assert inventory["discovered"] == 10
    assert inventory["assessment_eligible"] == 5
    assert inventory["by_format"] == {"docx": 4, "pdf": 1, "image": 3, "av": 1, "other": 1}
    assert inventory["by_status"][inv.METADATA_ONLY] == 4   # 3 images + 1 video
    assert inventory["by_status"][inv.UNSUPPORTED] == 1     # the zip
