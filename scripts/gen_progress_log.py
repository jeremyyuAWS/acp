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
the public log or to state the omission was deliberate (`Matrix-Note: none`). It also
exits 1 on a trailer that IS present but cannot be parsed into an entry.

That second check lives here, at PR time, because it is the last moment a commit message can
be amended. GENERATION (the push-time path the notify workflow runs) only warns and skips such
a commit: its message is already published, so failing there fails a push nobody can obey
without rewriting shared history — and it drops the whole batch, well-formed entries included.

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
    # The lane tables themselves — REMEDIATION, ASSESSMENT_OVERRIDES, CAPABILITY. Editing a cell
    # here changes what ACP CLAIMS about a (format, criterion): whether a clean scan certifies a
    # pass or only flags it for review. That is the most consequential kind of capability change
    # and it was the one path the guard missed. Two 2.4.6 corrections landed through this file on
    # 2026-07-29 (997b7d0 docx, 0be9e00 html) and neither was asked for a Matrix-Note, because
    # "api/remediate" does not prefix-match "api/remediation_capability.py" — the two strings
    # diverge at 'remediate' vs 'remediati'. Spelled out in full rather than by shortening that
    # prefix, which would silently widen it to anything starting "api/remediat".
    "api/remediation_capability.py",
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
# "this commit deliberately has no entry" — `none`, `n/a`, a bare dash, each optionally
# followed by the reason. Applied only where no WCAG: trailer was declared (see parse_commit),
# so it can never swallow a real entry that happens to start with the word "None".
_OMISSION_RE = re.compile(r"^\s*(?:none|n/?a|nil|[-—–])(?:\b|$)", re.I)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def _repo_slug() -> str:
    """owner/name for the commit links the matrix renders.

    Falls back on the default for a repo with no `origin` at all, not just for a URL that
    doesn't parse: `git config --get` exits 1 when the key is absent, which `_git` turns into
    an exception. Any checkout without that remote — a test fixture, a clone whose remote is
    named something else — would otherwise crash the whole run on a value used only to build
    a link.
    """
    try:
        url = _git("config", "--get", "remote.origin.url").strip()
    except subprocess.CalledProcessError:
        return "jeremyyuAWS/acp"
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


def _split_when(authored: str) -> tuple[str, str, str]:
    """A commit's author timestamp -> ("YYYY-MM-DD", "HH:MM", "PDT"), in Pacific time.

    PACIFIC, not UTC. The reason for normalising at all is unchanged and still the point:
    contributors and CI runners sit in different zones, and a log mixing them is not orderable
    by eye — two entries an hour apart can read as five hours apart, or backwards. What changed
    is WHICH single clock. UTC is the neutral choice for machines; this log is read by people
    who work Pacific hours, and "shipped 00:31" meaning late morning is a small tax paid on
    every read.

    The zone is `America/Los_Angeles`, not a fixed -8 offset, so the conversion stays correct
    across a DST boundary instead of silently going an hour wrong every March. That is also why
    the abbreviation is RETURNED rather than hardcoded: half the year it is PST and half PDT,
    and a log stamped "PST" in July is simply false. The renderer prints whatever this returns.

    Falls back to date-only when the timestamp cannot be parsed, or when the host has no tz
    database (a bare container can lack one) — a missing zone must degrade to no time rather
    than to a wrong time, and an entry with no time renders without one, exactly as the
    pre-timestamp entries in the log already do.
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        pacific = ZoneInfo("America/Los_Angeles")
    except Exception:
        return authored.strip()[:10], "", ""
    try:
        dt = datetime.fromisoformat(authored.strip()).astimezone(pacific)
    except ValueError:
        return authored.strip()[:10], "", ""
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), dt.strftime("%Z")


class MalformedTrailer(Exception):
    """A commit opted in with `Matrix-Note:` but its trailers cannot be turned into an entry.

    Raised by parse_commit, and deliberately handled DIFFERENTLY at the two moments this script
    runs, because only one of them can still act on it:

      --check      PR time. The message is a commit on a branch; the author can amend it. FATAL.
      generation   Push time. The message is published — correcting it means rewriting shared
                   history, which this repo forbids. WARN and skip the entry.

    It used to be fatal at both, which put the only enforcement at the one moment nobody could
    obey it: a malformed trailer failed every push to main until someone rewrote history, and
    took the whole notification down with it — including the well-formed entries beside it.
    """


def parse_commit(raw: str, repo: str) -> dict | None:
    """One `git log` record -> a PROGRESS_LOG entry, or None if it didn't opt in.

    Raises MalformedTrailer when the commit DID opt in but the trailers are unusable; see that
    class for why the two callers treat it differently."""
    sha, authored, subject, body = raw.split("\x1f", 3)
    date, time, tz = _split_when(authored)
    note = _NOTE_RE.search(body)
    if not note:
        return None
    summary, points = parse_note(note.group(1))
    if summary.lower() in ("none", "n/a", "-"):
        return None            # explicit, deliberate omission
    if points and not summary:
        raise MalformedTrailer(f"{sha[:7]}: Matrix-Note: is all bullets with no lead sentence — the "
                         f"matrix shows the lead when the entry is collapsed, so it needs one.")

    scs: list[str] = []
    formats: set[str] = set()
    for sc, fmts in _WCAG_RE.findall(body):
        if sc not in TRACKED_SCS:
            raise MalformedTrailer(f"{sha[:7]}: WCAG: {sc} is not one of the 20 SCs the "
                             f"matrix tracks — fix the trailer or add the row first.")
        if sc not in scs:
            scs.append(sc)
        named = [f.strip().lower() for f in (fmts or "").split(",") if f.strip()]
        for f in named or FORMATS:
            if f not in FORMATS:
                raise MalformedTrailer(f"{sha[:7]}: unknown format '{f}' — expected one of "
                                 f"{', '.join(FORMATS)}.")
            formats.add(f)
    if not scs:
        # `Matrix-Note: none — <reason>` is the deliberate-omission form this script's own usage
        # note invites, and it is how people actually write it: "none", then why. The check at
        # the top of this function is an EXACT match, so the reason turned an omission into a
        # real entry, which then failed for the WCAG: trailer it never needed — six commits on
        # main between 2026-07-28 and 2026-07-29, each failing the notify workflow's first step.
        #
        # Only reachable when NO SC was declared, and that is what makes the loose match safe:
        # a genuine entry opening with the word "None" carries a WCAG: trailer, so it never
        # reaches here and cannot be swallowed.
        if _OMISSION_RE.match(summary):
            return None
        raise MalformedTrailer(f"{sha[:7]}: has a Matrix-Note: but no WCAG: trailer — the "
                         f"matrix needs to know which SC the entry belongs to.")

    pr = _PR_RE.search(subject)
    entry = {
        "date": date,
        "time": time,
        "tz": tz,
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
    # %aI (strict ISO, author date with offset) rather than --date=short: the date alone
    # cannot order two commits that landed the same day, which is most of a busy day's log.
    out = _git("log", *rng, f"--format=%H\x1f%aI\x1f%s\x1f%b{_SEP}")
    entries = []
    for raw in out.split(_SEP):
        if not raw.strip():
            continue
        try:
            entry = parse_commit(raw.strip("\n"), repo)
        except MalformedTrailer as exc:
            # Push time. This message is published: the only way to "fix" it is to rewrite
            # shared history, which this repo forbids. Failing here therefore fails a push
            # nobody can obey, and takes down the notification for every WELL-FORMED entry in
            # the same range — one bad trailer silently costs the matrix the whole batch.
            # Say it loudly (::warning:: surfaces in the run summary) and keep going.
            print(f"::warning::{exc} Entry skipped — the commit is published, so this is "
                  f"reported rather than fatal; --check catches it at PR time.", file=sys.stderr)
            continue
        if entry:
            entries.append(entry)
    return entries   # git log is already newest-first, which is the log's order


def check(since: str | None) -> int:
    """Fail when a commit changed rule code without declaring its matrix impact, OR declared it
    with a trailer that cannot be turned into an entry.

    Both are caught HERE because this is the last moment either can be fixed: on a PR the
    message still belongs to a branch and `git commit --amend` is available. Generation only
    warns (see MalformedTrailer), so this is the only enforcement — a malformed trailer that
    slips past here reaches the matrix as a skipped entry and a warning nobody reads.
    """
    rng = f"{since}..HEAD" if since else "HEAD~1..HEAD"
    shas = _git("log", rng, "--format=%H").split()
    repo = _repo_slug()
    bad = []
    malformed: list[str] = []
    for sha in shas:
        # Merge commits are skipped EXPLICITLY, by parent count. They author nothing: every
        # change they carry arrived in a commit this loop already judged on its own trailer,
        # and a merge has no authored message to put one in.
        #
        # This used to rely on `git show --name-only` printing nothing for a merge, which is
        # only true when the two sides touched DISJOINT files. `git show` renders a merge as a
        # combined diff, listing whatever differs from every parent — so the moment a PR and
        # its base both edited one rule file, CI flagged GitHub's own merge ref for a trailer
        # that cannot exist, and the PR could not go green by any action its author could take.
        if len(_git("log", "-1", "--format=%P", sha).split()) > 1:
            continue
        body = _git("log", "-1", "--format=%b", sha)
        subject = _git("log", "-1", "--format=%s", sha).strip()
        if _NOTE_RE.search(body):
            # Opted in — so it must actually parse. Checked for EVERY commit carrying a note,
            # not just the rule-code ones: a malformed trailer breaks its own entry whatever
            # the commit touched, and the author can still amend it right now.
            authored = _git("log", "-1", "--format=%aI", sha).strip()
            try:
                parse_commit("\x1f".join([sha, authored, subject, body]), repo)
            except MalformedTrailer as exc:
                malformed.append(str(exc))
            continue
        files = _git("show", "--name-only", "--format=", sha).split()
        if any(f.startswith(p) for f in files for p in RULE_PATHS):
            bad.append((sha[:7], subject))
    for sha, subject in bad:
        print(f"{sha} touches rule code but has no Matrix-Note: trailer\n"
              f"         {subject}", file=sys.stderr)
    if bad:
        print("\nAdd a Matrix-Note: (and WCAG:) trailer, or 'Matrix-Note: none' to "
              "record that the omission is deliberate.", file=sys.stderr)
    for msg in malformed:
        print(msg, file=sys.stderr)
    if malformed:
        print("\nAmend the trailer now — once this is pushed the message is published, and "
              "generation can only warn and drop the entry.", file=sys.stderr)
    return 1 if (bad or malformed) else 0


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
