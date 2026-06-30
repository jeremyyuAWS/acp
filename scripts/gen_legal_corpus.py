#!/usr/bin/env python3
"""Generate a synthetic 100-file LEGAL-PROFESSION corpus with a controlled WCAG-issue
spread (clean / minor / serious / critical / unanalysable) across HTML/PDF/DOCX/PPTX/XLSX.

Reuses the document builders from gen_bulk_corpus; only the theme (practice areas, document
types, body copy) is legal. All names/PII are synthetic. Files land in test-corpus/files/
so the deployed image bakes them and a "local" scan shows a legal estate.

Usage:  python scripts/gen_legal_corpus.py --out test-corpus/files --count 100
"""
from __future__ import annotations
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_bulk_corpus import BUILDERS, make_profile, build_unanalysable  # noqa: E402

# Legal practice areas (used as the "department" prefix).
DEPTS = ["Litigation", "Corporate", "M-and-A", "IP", "Employment", "Real-Estate",
         "Tax", "Compliance", "Estates", "Banking"]
# Legal document types.
DOCTYPES = ["Contract", "NDA", "Engagement-Letter", "Brief", "Motion", "Complaint",
            "Affidavit", "Deposition-Summary", "Settlement-Agreement", "Legal-Memo",
            "Retainer-Agreement", "Discovery-Request", "Subpoena", "Power-of-Attorney",
            "Commercial-Lease", "Last-Will", "Patent-Application", "Pleading",
            "Opinion-Letter", "Indemnity-Agreement"]
BODIES = [
    "This Agreement is entered into between the parties and sets out the terms, obligations, "
    "representations, warranties, and governing law applicable to the engagement described herein.",
    "Comes now the Plaintiff, by and through undersigned counsel, and respectfully submits the "
    "following memorandum of points and authorities in support of the motion now before this Court.",
    "The undersigned acknowledges the confidential and privileged nature of the materials disclosed "
    "and agrees to the restrictions on use and further disclosure of such information set forth below.",
    "This memorandum summarises the relevant facts, the applicable statutory and case authority, and "
    "our analysis of the legal questions presented, together with our recommendations to the client.",
    "The provisions that follow govern indemnification, limitation of liability, and dispute "
    "resolution, and shall survive any expiration or termination of this Agreement for any reason.",
    "Pursuant to the applicable rules of civil procedure, the responding party objects to and answers "
    "each request below, reserving all rights, privileges, and objections available under law.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--out", default="test-corpus/files")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*"):                # fresh legal estate
        if old.is_file():
            old.unlink()

    FORMAT_W = [("html", 30), ("pdf", 30), ("docx", 24), ("pptx", 9), ("xlsx", 7)]
    PROFILE_W = [("clean", 34), ("minor", 24), ("serious", 22), ("critical", 14), ("unanalysable", 6)]
    PII_W = [("none", 78), ("contact", 15), ("sensitive", 7)]
    fmts = [f for f, w in FORMAT_W for _ in range(w)]
    profs = [p for p, w in PROFILE_W for _ in range(w)]
    piis = [p for p, w in PII_W for _ in range(w)]

    counts = {"format": {}, "profile": {}, "pii": {}}
    used: set[str] = set()
    n = 0
    while n < args.count:
        fmt = rnd.choice(fmts)
        kind = rnd.choice(profs)
        pii = rnd.choice(piis)
        dept, dtype = rnd.choice(DEPTS), rnd.choice(DOCTYPES)
        idx = rnd.randint(1, 99)
        name = f"{dept}-{dtype}-{idx:02d}"
        ext = rnd.choice(["pdf", "docx", "xlsx"]) if kind == "unanalysable" else fmt
        fname = f"{name}.{ext}"
        if fname in used:
            continue
        used.add(fname)
        path = out / fname
        title = f"{dept.replace('-and-', ' & ')} {dtype.replace('-', ' ')}"
        body = rnd.choice(BODIES)
        try:
            if kind == "unanalysable":
                build_unanalysable(path, rnd)
            else:
                BUILDERS[fmt](path, make_profile(kind), title, body, pii, rnd)
        except Exception as e:
            print(f"  ! skip {fname}: {e}")
            used.discard(fname)
            continue
        counts["format"][ext] = counts["format"].get(ext, 0) + 1
        counts["profile"][kind] = counts["profile"].get(kind, 0) + 1
        counts["pii"][pii] = counts["pii"].get(pii, 0) + 1
        n += 1

    print(f"Generated {n} legal-profession files in {out}\n")
    for dim in ("format", "profile", "pii"):
        print(f"  by {dim}:", ", ".join(f"{k}={v}" for k, v in sorted(counts[dim].items())))


if __name__ == "__main__":
    main()
