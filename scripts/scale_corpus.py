#!/usr/bin/env python3
"""Generate a synthetic Drive LISTING at UTSW scale (~30k files) for the discovery/inventory test.

This is NOT 30k real documents. Assessment accuracy is tested on the labeled complex_corpus; this
produces the Drive-API METADATA a whole-Drive scan enumerates (id / name / mimeType / size /
modifiedTime / owner / sharing) at a realistic hospital content-estate shape — so the parts that
only strain at scale can be exercised without downloading or building tens of thousands of files:

  * the estate inventory's composition + capability-status split (the three denominators),
  * the funnel's top ("all files discovered" vs "assessment eligible"),
  * the department / visibility / age cuts the dashboard shows,
  * and the paging/truncation cap.

The manifest's estate summary is produced by calling `estate_inventory.summarize()` on the records
AND cross-checked against the generator's own by-construction tally — so a classifier that
misbuckets a format (a `.heic` image read as "other", a native Google Doc missed) fails the build
right here, at 30k scale. That cross-check is the point: the generator is a scale test of the
classifier, not just a data dump.

Usage:
    python scripts/scale_corpus.py [N] [OUT_DIR]      # default N=30000, OUT_DIR=scale-corpus/
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
import estate_inventory as inv  # noqa: E402

# ── Realistic hospital content-estate shape (weights per 1000 files) ────────────────────────────
# Heavy PDF + Word (policies, letters, forms, scanned faxes), a real spreadsheet/deck tail, and a
# LARGE unsupported tail (images, video, loose text) — the blind spot the whole-estate view exists
# to make visible. Assessment-eligible ≈ 63%; the other ~37% is metadata-only or unsupported.
FORMAT_WEIGHTS = {
    "pdf": 270, "docx": 210, "xlsx": 100, "pptx": 50,   # assessable (Office + PDF)
    "image": 250, "av": 40,                             # metadata-only
    "other": 80,                                        # unsupported
}
NATIVE_FRACTION = 0.15    # share of Office files that are Google-native (no filename extension)
EXCLUDED_FRACTION = 0.015  # share flagged as ACP's own output (a "Remediated" copy) → EXCLUDED
FOLDER_COUNT_RATIO = 0.006  # folders per file (dropped from the discovered count)

_OX = {
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
_NATIVE = {
    "docx": "application/vnd.google-apps.document",
    "xlsx": "application/vnd.google-apps.spreadsheet",
    "pptx": "application/vnd.google-apps.presentation",
}
_IMAGE_KINDS = [("image/png", ".png"), ("image/jpeg", ".jpg"), ("image/tiff", ".tif"),
                ("image/gif", ".gif"), ("image/heic", ".heic")]
_AV_KINDS = [("video/mp4", ".mp4"), ("audio/mpeg", ".mp3"), ("video/quicktime", ".mov")]
_OTHER_KINDS = [("text/plain", ".txt"), ("text/csv", ".csv"), ("application/zip", ".zip"),
                ("application/msword", ".doc"), ("application/vnd.ms-powerpoint", ".ppt"),
                ("application/vnd.ms-excel", ".xls")]

DEPARTMENTS = [
    "Radiology", "Cardiology", "Oncology", "Neurology", "Pediatrics", "Emergency", "Surgery",
    "Nursing", "Pharmacy", "Pathology", "Laboratory", "Anesthesiology", "Obstetrics", "Psychiatry",
    "Dermatology", "Orthopedics", "Urology", "Nephrology", "Endocrinology", "Rheumatology",
    "Administration", "Human Resources", "Finance", "Billing", "Legal", "Compliance", "IT",
    "Facilities", "Supply Chain", "Marketing", "Patient Experience", "Quality", "Research",
    "Clinical Trials", "Medical Records", "Case Management", "Social Work", "Nutrition", "Rehab",
    "Respiratory", "Infection Control", "Pharmacy Residency", "Graduate Medical Education",
    "Development", "Volunteer Services", "Security", "Environmental Services", "Transport",
    "Chaplaincy", "Population Health",
]
_NOUNS = ["Policy", "Consent Form", "Discharge Summary", "Intake", "Report", "Protocol", "Handbook",
          "Notice", "Roster", "Schedule", "Guidelines", "Checklist", "Memo", "Newsletter", "Deck",
          "Training", "Fax", "Scan", "Photo", "Recording", "Export", "Backup"]


def _weighted_format(rng: random.Random) -> str:
    r = rng.randrange(sum(FORMAT_WEIGHTS.values()))
    upto = 0
    for fmt, w in FORMAT_WEIGHTS.items():
        upto += w
        if r < upto:
            return fmt
    return "other"


def _make_record(i: int, rng: random.Random, base_day: int) -> dict:
    """One Drive file record for logical format `fmt`, with a realistic mime/name/owner/size/age."""
    fmt = _weighted_format(rng)
    dept = DEPARTMENTS[rng.randrange(len(DEPARTMENTS))]
    noun = _NOUNS[rng.randrange(len(_NOUNS))]
    stem = f"{dept.replace(' ', '_')}_{noun.replace(' ', '_')}_{i}"

    excluded = False
    if fmt == "pdf":
        mime, name = "application/pdf", stem + ".pdf"
    elif fmt in _OX:
        if rng.random() < NATIVE_FRACTION:
            mime, name = _NATIVE[fmt], stem            # Google-native: no extension
        else:
            mime, name = _OX[fmt][0], stem + _OX[fmt][1]
        excluded = rng.random() < EXCLUDED_FRACTION     # ACP's own remediated Office output
    elif fmt == "image":
        m, ext = _IMAGE_KINDS[rng.randrange(len(_IMAGE_KINDS))]
        # Half the images arrive typed only as octet-stream — exercises the extension fallback.
        mime = m if rng.random() < 0.5 else "application/octet-stream"
        name = stem + ext
    elif fmt == "av":
        m, ext = _AV_KINDS[rng.randrange(len(_AV_KINDS))]
        mime, name = m, stem + ext
    else:  # other / unsupported
        m, ext = _OTHER_KINDS[rng.randrange(len(_OTHER_KINDS))]
        mime = m if rng.random() < 0.5 else "application/octet-stream"
        name = stem + ext

    # Size (bytes): format-correlated, video biggest, text smallest.
    size_kb = {"pdf": (40, 8000), "docx": (20, 3000), "xlsx": (10, 5000), "pptx": (200, 20000),
               "image": (30, 12000), "av": (2000, 400000), "other": (1, 1500)}[fmt]
    size = rng.randint(*size_kb) * 1024
    # Age: a modifiedTime within the last ~5 years (base_day is a fixed epoch-day, no wall clock).
    day = base_day - rng.randint(0, 5 * 365)
    modified = f"{2021 + (day // 365) % 5:04d}-{1 + (day % 12):02d}-{1 + (day % 27):02d}T12:00:00.000Z"
    vis = rng.randrange(1000)
    shared = vis < 280                # ~28% shared or public
    public = vis < 80                 # ~8% public-facing

    rec = {
        "id": f"f{i:06d}",
        "name": name,
        "mimeType": mime,
        "size": str(size),
        "modifiedTime": modified,
        "owners": [{"emailAddress": f"{dept.replace(' ', '.').lower()}@utsw.edu", "displayName": dept}],
        "shared": shared,
        "department": dept,
        "visibility": "public" if public else ("shared" if shared else "internal"),
    }
    if excluded:
        rec["_excluded"] = True       # scanner sets this via provenance; pre-set for the inventory test
    return rec


def generate(n: int = 30000, seed: int = 42) -> tuple[list[dict], list[dict], dict]:
    """Return (file_records, folder_records, manifest). Deterministic for a given (n, seed)."""
    rng = random.Random(seed)
    base_day = 20000                  # a fixed epoch-day anchor; never the wall clock (reproducible)
    files = [_make_record(i, rng, base_day) for i in range(n)]
    folders = [{"id": f"dir{j:04d}", "name": DEPARTMENTS[j % len(DEPARTMENTS)],
                "mimeType": inv.FOLDER_MIME} for j in range(int(n * FOLDER_COUNT_RATIO))]

    # Authoritative estate summary — from the real classifier, on the whole listing (files+folders).
    summary = inv.summarize(files + folders)

    # Independent by-construction cross-check: what the generator INTENDED must equal what the
    # classifier produced. A divergence means summarize() misbuckets something at scale — fail loudly.
    intended_status: dict[str, int] = {}
    for f in files:
        st = inv.EXCLUDED if f.get("_excluded") else inv._status_of(inv._format_of(f["name"], f["mimeType"]))
        intended_status[st] = intended_status.get(st, 0) + 1
    assert intended_status == summary["by_status"], (
        f"classifier disagrees with the generator's intent: {summary['by_status']} != {intended_status}")
    assert summary["discovered"] == n, f"folders leaked into the discovered count: {summary['discovered']} != {n}"

    by_department: dict[str, int] = {}
    by_visibility: dict[str, int] = {}
    for f in files:
        by_department[f["department"]] = by_department.get(f["department"], 0) + 1
        by_visibility[f["visibility"]] = by_visibility.get(f["visibility"], 0) + 1

    manifest = {
        "seed": seed,
        "generated_files": n,
        "folders": len(folders),
        "estate": summary,                       # discovered / assessment_eligible / by_format / by_status
        "by_department": by_department,
        "by_visibility": by_visibility,
        "note": "Synthetic Drive LISTING (metadata) for discovery/inventory scale testing — NOT real "
                "documents. Assessment accuracy is covered by the labeled complex_corpus.",
    }
    return files, folders, manifest


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30000
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else (ROOT / "scale-corpus")
    out.mkdir(parents=True, exist_ok=True)
    files, folders, manifest = generate(n)

    with (out / "files.jsonl").open("w") as fh:
        for rec in files + folders:
            fh.write(json.dumps(rec) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    e = manifest["estate"]
    print(f"scale corpus: {n} files + {len(folders)} folders → {out}")
    print(f"  discovered           {e['discovered']}")
    print(f"  assessment-eligible  {e['assessment_eligible']} "
          f"({round(e['assessment_eligible'] / e['discovered'] * 100)}% of discovered)")
    print(f"  by format            {e['by_format']}")
    print(f"  by status            {e['by_status']}")
    print(f"  departments          {len(manifest['by_department'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
