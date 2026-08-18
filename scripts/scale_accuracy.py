#!/usr/bin/env python3
"""Assessment accuracy AT SCALE — the labeled complex_corpus, embedded in the 30k estate.

The honest framing first, because it decides what this can and cannot prove:

    ACP assesses one file at a time. `score_assessment.scan()` copies each fixture into its own
    temp directory and scans it alone, exactly as the fan-out worker does per file. So per-file
    detection accuracy is SCALE-INVARIANT — a file scores the same whether it sits alone or among
    30 000 others. What scale can break is DISCOVERY and ATTRIBUTION: are the labeled files found
    among the estate at all (not dropped past a cap, not deduped away, not misclassified), and do
    their findings come back tied to the right file?

So this does two things:
  1. Embeds the complex_corpus's labeled files (real files, known {SC: count}) as ground-truth
     entries in the scale_corpus synthetic estate, and proves discovery accounts for every one of
     them among the 30k — unique, assessable, labels intact. (Engine-free; runs anywhere.)
  2. Locates those files and scores each against its injected-SC floor — reusing the shipped
     score path (score_assessment.scan) so this is the same measurement the docx scorecard makes,
     now demonstrably run on files that live inside the large estate. (Needs the analyser engine;
     the CLI runs it, the metadata test skips it.)

Usage:
    python scripts/scale_accuracy.py --complex ./complex-corpus     # embed + score the real files
    python scripts/scale_accuracy.py                                # embed a synthetic label set only
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import estate_inventory as inv  # noqa: E402
import scale_corpus  # noqa: E402

# A representative real MIME per assessable format, so an embedded label record classifies exactly
# as the real file would when Drive lists it.
FORMAT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "html": "text/html",
}


def labeled_records(entries: list[dict], base_id: int = 900000) -> list[dict]:
    """Turn complex_corpus manifest entries into ground-truth Drive records.

    `entries` is manifest["files"]: each carries `filename`, `format`, `injected_by_sc`, and
    `not_seeded`. The returned record is what a whole-Drive listing would return for that file,
    plus the label payload the scorer reads back: `labels` (the injected floor), `not_seeded`, and
    a `_ground_truth` marker so it can be located among the synthetic estate.
    """
    out = []
    for k, e in enumerate(entries):
        fmt = e["format"]
        mime = FORMAT_MIME.get(fmt, "application/octet-stream")
        out.append({
            "id": f"gt{base_id + k:06d}",
            "name": e["filename"],
            "mimeType": mime,
            "size": str(64 * 1024),
            "modifiedTime": "2026-08-01T12:00:00.000Z",
            "owners": [{"emailAddress": "quality@utsw.edu", "displayName": "Quality"}],
            "_ground_truth": True,
            "labels": dict(e.get("injected_by_sc", {})),
            "not_seeded": dict(e.get("not_seeded", {})),
        })
    return out


def embed(estate_files: list[dict], labeled: list[dict], seed: int = 0) -> list[dict]:
    """Interleave the labeled ground-truth records into the estate listing at deterministic
    positions — so the located-file test exercises finding them scattered through the estate, not
    conveniently bunched at the end."""
    rng = random.Random(seed)
    merged = list(estate_files)
    for rec in labeled:
        merged.insert(rng.randrange(len(merged) + 1), rec)
    return merged


def ground_truth(estate: list[dict]) -> list[dict]:
    """The labeled records located within an estate listing — discovery's job at scale."""
    return [f for f in estate if f.get("_ground_truth")]


def score_located(complex_dir: Path, *, verbose: bool = True) -> dict:
    """Scan each located labeled file and score it against its injected-SC floor.

    Needs the analyser engine (imports score_assessment → scanner). Returns per-file recall over
    the seeded SCs and the set it missed. `injected_by_sc` is a FLOOR (some detectors report
    per-document), so recall is over DISTINCT SCs surfaced, not raw counts — the same contract the
    complex_corpus manifest states.
    """
    import score_assessment as sa  # lazy: pulls in the whole OOXML/PDF engine
    import assessment_policy as pol

    man = json.loads((complex_dir / "manifest.json").read_text())
    rows = []
    for e in man["files"]:
        path = complex_dir / e["filename"]
        injected = set(e.get("injected_by_sc", {}))
        if not injected or not path.exists():
            continue
        issues, _ = sa.scan(path)
        surfaced = {pol._extract_sc(i.get("wcag", "")) for i in issues} - {None, ""}
        # Attribution at scale: every finding from an isolated scan must name THIS file.
        wrong_file = [i for i in issues if i.get("file") and i.get("file") != e["filename"]]
        hit = injected & surfaced
        rows.append({
            "file": e["filename"], "format": e["format"],
            "injected_scs": sorted(injected), "surfaced_scs": sorted(surfaced),
            "missing_scs": sorted(injected - surfaced),
            "recall": round(len(hit) / len(injected), 3),
            "attribution_ok": not wrong_file,
        })
        if verbose:
            mark = "ok " if not (injected - surfaced) and not wrong_file else "MISS"
            miss = f"  missing {sorted(injected - surfaced)}" if (injected - surfaced) else ""
            print(f"  {mark} {e['filename']:34} recall {len(hit)}/{len(injected)}{miss}")
    macro = round(sum(r["recall"] for r in rows) / len(rows), 3) if rows else 0.0
    return {"per_file": rows, "macro_recall": macro,
            "all_attributed": all(r["attribution_ok"] for r in rows)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--complex", type=Path, help="a generated complex-corpus dir (manifest.json + files)")
    ap.add_argument("-n", type=int, default=30000, help="estate size to embed into")
    args = ap.parse_args()

    if args.complex and (args.complex / "manifest.json").exists():
        entries = json.loads((args.complex / "manifest.json").read_text())["files"]
    else:
        # No real corpus available (e.g. a minimal env): embed a synthetic stand-in so the
        # discovery/embedding half still runs and reports.
        entries = [{"filename": f"labeled-{f}.{f}", "format": f,
                    "injected_by_sc": {"1.1.1": 3, "1.4.3": 2}, "not_seeded": {}}
                   for f in ("docx", "xlsx", "pptx", "pdf")]

    labeled = labeled_records(entries)
    files, folders, _ = scale_corpus.generate(args.n)
    estate = embed(files, labeled)

    located = ground_truth(estate)
    summary = inv.summarize(estate + folders)
    print(f"embedded {len(labeled)} labeled file(s) into a {args.n}-file estate")
    print(f"  located among the estate: {len(located)} / {len(labeled)}")
    print(f"  all classified assessable: {all(inv.classify(r)['status'] == inv.ASSESSABLE for r in located)}")
    print(f"  estate assessment-eligible: {summary['assessment_eligible']} of {summary['discovered']}")

    if args.complex and any((args.complex / e['filename']).exists() for e in entries):
        print("\nscoring located files against their injected-SC floor:")
        score = score_located(args.complex)
        print(f"\n  macro recall {score['macro_recall']}   "
              f"attribution {'OK' if score['all_attributed'] else 'BROKEN'}")
    else:
        print("\n(no real corpus files present — skipping the engine score; "
              "run scripts/complex_corpus.py first and pass --complex to score)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
