#!/usr/bin/env python3
"""Emit the WCAG-matrix Progress Log entries for commits that opted in.

The matrix at https://wcag-matrix.mova-io.app/ carries a `PROGRESS_LOG` — a dated
timeline of acp commits that changed detection or remediation capability for one of
the 20 WCAG SCs it tracks. It has always been hand-transcribed from `git log`, which
is why it drifts. This script derives it instead.

OPT-IN, NOT AUTOMATIC. A commit appears only if its message carries a `Matrix-Note:`
trailer — a sentence written for the matrix's audience. This is a CURATION rule, and it
matches the log's own stated posture ("Deliberately curated, not exhaustive"): most
commits here are real work that doesn't target one specific SC, and those are omitted on
purpose rather than folded in as noise. Auto-publishing every subject line would bury
the capability changes the log exists to show.

(It was also a privacy boundary while this repo was private and the matrix public. That
no longer applies — the repo is public as of 2026-07-28 — so the commit/PR links in the
log now actually resolve for readers, which they previously did not.)

Trailer format (git trailers — `Key: value` lines at the end of the commit body):

    WCAG: 1.4.11 (xlsx, pptx)
    WCAG: 2.4.6 (xlsx)
    Matrix-Note: XLSX non-text contrast is now measured structurally rather than
      routed to review. Continuation lines are indented.

`WCAG:` may repeat. Formats are optional — omitted means "all four".

A commit that changed several independent things should say so as a list. Any continuation
line starting `- ` or `* ` becomes a bullet in the rendered entry; everything before the first
bullet is the lead sentence, which is REQUIRED (a note that is only bullets has no summary to
show when the entry is collapsed):

    Matrix-Note: Five Tier-1 gaps closed across all four formats.
      - **DOCX 4.1.2** — the form-field detector now also reads w:tag.
      - **PDF 1.4.5** — a deterministic pre-OCR heuristic surfaces likely-scanned PDFs.

A bullet may open with an explicit `**label**`, which the matrix renders in bold so the list
can be scanned by format/SC. The marker is required rather than inferred: a label can't be told
from prose that merely opens with a dash-terminated phrase, and guessing gets it wrong in both
directions (SC numbers contain dots; ordinary clauses use em dashes). Unmarked bullets are
plain text.

Usage:
    python scripts/gen_progress_log.py                    # whole history -> stdout
    python scripts/gen_progress_log.py --since <sha>      # only newer commits
    python scripts/gen_progress_log.py --check            # CI drift guard, no output

`--check` exits 1 when a commit touches rule code but carries no `Matrix-Note:`,
so capability changes cannot land silently. It is a prompt to write one sentence for
the public log or to state the omission was deliberate (`Matrix-Note: none`).

This script only ever produces PROGRESS_LOG entries — a changelog. It deliberately
does NOT touch the matrix's `ROWS.a`/`ROWS.r` tier cells: those are capability claims,
and the matrix's own ground rules require a human to verify a tier against shipped code
(and cap anything with an LLM in the decision path at Guided). Auto-flipping a tier from
a commit message would break that discipline.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# The 20 SCs the matrix tracks. A commit naming anything else is a typo or is aimed at
# a criterion the matrix has no row for — either way it must not silently vanish.
TRACKED_SCS = frozenset({
    "1.1.1", "1.3.1", "1.3.2", "1.3.3", "1.4.1", "1.4.3", "1.4.4", "1.4.5",
    "1.4.10", "1.4.11", "1.4.12", "2.1.1", "2.1.2", "2.4.2", "2.4.3", "2.4.4",
    "2.4.6", "3.1.1", "3.1.2", "4.1.2",
})
FORMATS = ("docx", "xlsx", "pptx", "pdf")

# Paths whose change implies a capability change worth declaring. Used by --check only.
RULE_PATHS = (
    "engine/office-analysers/",
    "api/formats/",             # per-format detectors behind the capability registry
    "api/rule_registry.py",     # a coverage change IS a capability change worth declaring
    "api/capabilities.py",
    "api/office_structure.py",
    "api/textchecks.py",
    "api/ocr.py",
    "api/remediate",
    "api/proposals.py",
    "api/apply_alt.py",
    "api/apply_link_text.py",
    "config/rule-catalog.json",
)

_SEP = "\x1e"   # record separator — commit bodies contain blank lines, so \n\n won't do
_WCAG_RE = re.compile(r"^WCAG:\s*(\d+\.\d+\.\d+)\s*(?:\(([^)]*)\))?\s*$", re.M)
_NOTE_RE = re.compile(r"^Matrix-Note:\s*(.+?)(?=^\S+:|\Z)", re.M | re.S)
_PR_RE = re.compile(r"\(#(\d+)\)\s*$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def _repo_slug() -> str:
    """owner/name for the commit links the matrix renders."""
    url = _git("config", "--get", "remote.origin.url").strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else "jeremyyuAWS/acp"


_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
# A bullet's optional label, written **like this** at the very start.
#
# An earlier version inferred the label from a leading "DOCX 4.1.2 — " and guessed wrong in both
# directions: SC numbers contain dots, so any "no sentence punctuation" test rejects the real
# labels, while an ordinary clause set off by an em dash sails through and gets bolded. There is
# no reliable way to tell a label from prose that merely opens with a dash-terminated phrase, so
# the marker is explicit. Unmarked bullets are plain text, which is a fine default.
_LABEL_RE = re.compile(r"^\*\*\s*(.+?)\s*\*\*\s*(?:—|–|--)?\s*(.+)$", re.S)


def _split_label(text: str) -> dict:
    m = _LABEL_RE.match(text)
    return {"label": m.group(1), "text": m.group(2).strip()} if m else {"text": text}


def parse_note(raw: str) -> tuple[str, list[dict]]:
    """A Matrix-Note body -> (lead sentence, bullets).

    Whitespace inside a paragraph is collapsed (git wraps trailers at will, and the matrix
    re-flows the text anyway), but LINE STRUCTURE is preserved long enough to find the bullets —
    which is why this can't just be `" ".join(raw.split())` the way it used to be.
    """
    lead: list[str] = []
    bullets: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _BULLET_RE.match(stripped)
        if m:
            bullets.append(m.group(1).strip())
        elif bullets:
            bullets[-1] += " " + stripped      # wrapped continuation of the current bullet
        else:
            lead.append(stripped)
    return " ".join(" ".join(lead).split()), [_split_label(b) for b in bullets if b]


def parse_commit(raw: str, repo: str) -> dict | None:
    """One `git log` record -> a PROGRESS_LOG entry, or None if it didn't opt in."""
    sha, date, subject, body = raw.split("\x1f", 3)
    note = _NOTE_RE.search(body)
    if not note:
        return None
    summary, points = parse_note(note.group(1))
    if summary.lower() in ("none", "n/a", "-"):
        return None            # explicit, deliberate omission
    if points and not summary:
        raise SystemExit(f"{sha[:7]}: Matrix-Note: is all bullets with no lead sentence — the "
                         f"matrix shows the lead when the entry is collapsed, so it needs one.")

    scs: list[str] = []
    formats: set[str] = set()
    for sc, fmts in _WCAG_RE.findall(body):
        if sc not in TRACKED_SCS:
            raise SystemExit(f"{sha[:7]}: WCAG: {sc} is not one of the 20 SCs the "
                             f"matrix tracks — fix the trailer or add the row first.")
        if sc not in scs:
            scs.append(sc)
        named = [f.strip().lower() for f in (fmts or "").split(",") if f.strip()]
        for f in named or FORMATS:
            if f not in FORMATS:
                raise SystemExit(f"{sha[:7]}: unknown format '{f}' — expected one of "
                                 f"{', '.join(FORMATS)}.")
            formats.add(f)
    if not scs:
        raise SystemExit(f"{sha[:7]}: has a Matrix-Note: but no WCAG: trailer — the "
                         f"matrix needs to know which SC the entry belongs to.")

    pr = _PR_RE.search(subject)
    entry = {
        "date": date,
        "hash": sha[:7],
        "pr": int(pr.group(1)) if pr else None,
        "repo": repo,
        "title": subject,
        "scs": scs,
        # Emit in the matrix's own column order, not set order, so the badges read
        # DOCX/XLSX/PPTX/PDF consistently regardless of how the trailer was written.
        "formats": [f for f in FORMATS if f in formats],
        "summary": summary,
    }
    # Omitted entirely when there are no bullets, so a single-change note produces exactly the
    # entry shape it always did and the matrix renders it exactly as before.
    if points:
        entry["points"] = points
    return entry


def collect(since: str | None) -> list[dict]:
    repo = _repo_slug()
    rng = [f"{since}..HEAD"] if since else []
    out = _git("log", *rng, f"--format=%H\x1f%ad\x1f%s\x1f%b{_SEP}", "--date=short")
    entries = []
    for raw in out.split(_SEP):
        if raw.strip():
            entry = parse_commit(raw.strip("\n"), repo)
            if entry:
                entries.append(entry)
    return entries   # git log is already newest-first, which is the log's order


def check(since: str | None) -> int:
    """Fail when a commit changed rule code without declaring its matrix impact."""
    rng = f"{since}..HEAD" if since else "HEAD~1..HEAD"
    shas = _git("log", rng, "--format=%H").split()
    bad = []
    for sha in shas:
        files = _git("show", "--name-only", "--format=", sha).split()
        if not any(f.startswith(p) for f in files for p in RULE_PATHS):
            continue
        body = _git("log", "-1", "--format=%b", sha)
        if not _NOTE_RE.search(body):
            bad.append((sha[:7], _git("log", "-1", "--format=%s", sha).strip()))
    for sha, subject in bad:
        print(f"{sha} touches rule code but has no Matrix-Note: trailer\n"
              f"         {subject}", file=sys.stderr)
    if bad:
        print("\nAdd a Matrix-Note: (and WCAG:) trailer, or 'Matrix-Note: none' to "
              "record that the omission is deliberate.", file=sys.stderr)
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="only commits after this ref")
    ap.add_argument("--check", action="store_true",
                    help="drift guard: fail if rule code changed without a trailer")
    args = ap.parse_args()
    if args.check:
        return check(args.since)
    json.dump(collect(args.since), sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
