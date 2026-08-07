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
    # The lane tables themselves — REMEDIATION, ASSESSMENT_OVERRIDES, CAPABILITY. Editing a cell
    # here changes what ACP CLAIMS about a (format, criterion): whether a clean scan certifies a
    # pass or only flags it for review. That is the most consequential kind of capability change
    # and it was the one path the guard missed. Two 2.4.6 corrections landed through this file on
    # 2026-07-29 (997b7d0 docx, 0be9e00 html) and neither was asked for a Matrix-Note, because
    # "api/remediate" does not prefix-match "api/remediation_capability.py" — the two strings
    # diverge at 'remediate' vs 'remediati'. Spelled out in full rather than by shortening that
    # prefix, which would silently widen it to anything starting "api/remediat".
    "api/remediation_capability.py",
    # RULE_FORMATS / REVIEW_FORMATS live here since de0f273 moved them out of store.py. Same
    # class of claim as the lane tables above — which formats a criterion is judged on decides
    # whether a clean scan can certify a pass — and the move had left the guard blind to it.
    "api/assessment_policy.py",
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
_WCAG_LINE_RE = re.compile(r"^WCAG:\s*(.+)$", re.M)
# One SC and its optional (formats) inside a WCAG: line. Applied repeatedly across the line, so
# `WCAG: 1.1.1 (pdf), 4.1.2 (pdf)` works as well as one SC per line. It used to anchor on `$`
# after the formats, which meant a comma-separated pair matched NOTHING — the commit then read
# as "Matrix-Note with no WCAG:" and hard-exited the generator. 676f081 is exactly that.
# `\b` so the SC has to start at a token boundary. Without it the digits were matched INSIDE a
# larger token and `WCAG: SC1.1.1 (pdf)` parsed happily as 1.1.1 — the same class of gap as the
# `$` anchor above, in the opposite direction: accepting more than the documented format rather
# than less. No trailer in history relies on the laxity (generation output is byte-identical
# before and after), and a format the parser silently invents support for is one nobody can
# document.
_WCAG_RE = re.compile(r"\b(\d+\.\d+\.\d+)\s*(?:\(([^)]*)\))?")
_NOTE_RE = re.compile(r"^Matrix-Note:\s*(.+?)(?=^\S+:|\Z)", re.M | re.S)
_PR_RE = re.compile(r"\(#(\d+)\)\s*$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def _repo_slug() -> str:
    """owner/name for the commit links the matrix renders.

    Falls back rather than raising when there is no remote at all: `git config --get` exits 1 on a
    missing key, and a clone or test fixture without an origin is a perfectly ordinary place to
    generate a log. Only the link text depends on this, so guessing beats crashing.
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


# "This commit deliberately has no log entry" — `none`, optionally followed by the reason.
#
# The verdict is read from the FIRST LINE of the note only, and an explanation may follow either
# after punctuation ("none — a test-only guard") or on the next line. It used to require the whole
# note to be exactly "none", which is a trap rather than a rule: authors naturally say WHY they
# are opting out, and the moment they do, the note stops being an omission, falls through to the
# WCAG check, and hard-exits the generator. That happened twice on 2026-07-29 alone — 0c79986
# (#35) wrote "none — a test-only guard over existing tables", which broke log generation on main.
#
# The separator is required so this cannot swallow a real note: "None of the four formats now
# certify 2.4.6" continues with a word, not punctuation, and is still a genuine entry.
_OMISSION_RE = re.compile(r"^\s*(?:none|n/a|-)\s*(?:[—–:.,;]|-(?!\S)|$)", re.I)


def _is_omission(note_body: str) -> bool:
    """True when a Matrix-Note declares a deliberate omission, reason or not."""
    first_line = note_body.strip().splitlines()[0] if note_body.strip() else ""
    return bool(_OMISSION_RE.match(first_line))


class TrailerProblem(Exception):
    """A malformed matrix trailer. Fatal pre-merge (--check), reported-and-skipped after.

    Which is the whole point of it being an exception rather than a SystemExit. A trailer lives in
    a COMMIT MESSAGE: before the merge its author can still fix it, and after the merge nobody can
    without rewriting shared history. Halting the generator on immutable history therefore does not
    prompt a fix — it just means the log never builds again, and one bad trailer takes the whole
    public timeline down with it. That is precisely what happened: four commits landed on
    2026-07-29 with four different malformed trailers, and generation had been dead ever since.

    So severity now follows fixability. --check stays strict and gains trailer validation, so these
    are caught on the PR where they CAN be corrected; generation reports each problem loudly on
    stderr and skips that one entry. "Must not silently vanish" is preserved — nothing here is
    silent — without letting history brick the log.
    """


def parse_commit(raw: str, repo: str, strict: bool = False) -> dict | None:
    """One `git log` record -> a PROGRESS_LOG entry, or None if it didn't opt in.

    `strict` raises TrailerProblem on a malformed trailer (for --check). Otherwise the problem is
    reported on stderr and the entry skipped, so one bad commit cannot kill the whole log.
    """
    sha, authored, subject, body = raw.split("\x1f", 3)
    date, time, tz = _split_when(authored)
    note = _NOTE_RE.search(body)
    if not note:
        return None
    summary, points = parse_note(note.group(1))
    if _is_omission(note.group(1)):
        return None            # explicit, deliberate omission

    def bad(msg: str):
        problem = TrailerProblem(f"{sha[:7]}: {msg}")
        if strict:
            raise problem
        # `::warning::` is how a line on stderr becomes a GitHub Actions ANNOTATION — surfaced on
        # the run summary instead of buried in a log nobody opens for a green job. These skips
        # are the whole safety net for the severity-follows-fixability rule above: an entry the
        # matrix will never receive, reported at the only volume left once the commit is
        # published. Outside Actions the prefix is inert text, so local runs read the same.
        print(f"::warning::skipped {problem} ", file=sys.stderr)
        return None

    if points and not summary:
        return bad("Matrix-Note: is all bullets with no lead sentence — the matrix shows the "
                   "lead when the entry is collapsed, so it needs one.")

    wcag_lines = _WCAG_LINE_RE.findall(body)
    scs: list[str] = []
    formats: set[str] = set()
    untracked: list[str] = []
    for sc, fmts in [m for line in wcag_lines
                     for m in _WCAG_RE.findall(line)]:
        if sc not in TRACKED_SCS:
            untracked.append(sc)
            msg = (f"WCAG: {sc} is not one of the 20 SCs the matrix tracks — fix the "
                   f"trailer or add the row first.")
            if strict:
                raise TrailerProblem(f"{sha[:7]}: {msg}")   # pre-merge: still fixable, still fatal
            # After the merge it is not fixable, and the same severity-follows-fixability rule
            # that stops one bad trailer bricking the log applies WITHIN an entry too: commits
            # routinely declare a tracked SC alongside one the matrix has no row for — 2caaa6c is
            # `1.4.3 (pdf)` plus `1.4.6 (pdf)` — and dropping the entry discards the 1.4.3 the
            # matrix CAN render. Three of this history's eight entries were being lost that way.
            # The untracked SC is announced and omitted; "must not silently vanish" is preserved,
            # because stderr is not silence.
            print(f"::warning::skipped SC {sha[:7]}: {msg} ", file=sys.stderr)
            continue
        if sc not in scs:
            scs.append(sc)
        named = [f.strip().lower() for f in (fmts or "").split(",") if f.strip()]
        for f in named or FORMATS:
            if f not in FORMATS:
                return bad(f"unknown format '{f}' — expected one of {', '.join(FORMATS)}.")
            formats.add(f)
    if not scs:
        # Three different failures used to share one message, and it named the only cause the code
        # had NOT established: that the author omitted the trailer. When a `WCAG:` line was sitting
        # right there and merely failed to parse, "no WCAG: trailer" sent the reader to audit a
        # commit that was fine. That is not hypothetical — it is how the `$`-anchor bug above went
        # undiagnosed: 51a673b and 676f081 both carried valid comma-separated trailers, the message
        # was read at face value, and the wrong cause reached a commit message, a PR body (#49) and
        # a broadcast to five sessions before anyone reproduced it. See #57.
        #
        # The distinguishing information is already in hand at this point, so each case says what
        # was actually observed, and the unparsed case ECHOES the line: seeing the offending text
        # quoted back makes the parser (or the typo) the obvious suspect in one read.
        if not wcag_lines:
            return bad("has a Matrix-Note: but no WCAG: trailer — the matrix needs to know which "
                       "SC the entry belongs to.")
        if not untracked:
            quoted = "; ".join(f"`WCAG: {line.strip()}`" for line in wcag_lines)
            return bad(f"has a WCAG: trailer but no criterion parsed out of it: {quoted} — "
                       f"expected a three-part SC like `WCAG: 1.1.1 (pdf)`.")
        # Every SC present parsed, and every one of them was untracked. Each already got its own
        # `skipped SC` warning above, so the old message did not merely mislead here — it
        # CONTRADICTED the line before it, naming a missing trailer the previous line had just
        # quoted. Say what is true instead: the trailer parsed and nothing survived the filter.
        return bad(f"every criterion in its WCAG: trailer is untracked "
                   f"({', '.join(untracked)}) — nothing is left for the matrix to render.")

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
        if not _NOTE_RE.search(body):
            # Only a commit that touches rule code is REQUIRED to carry a note. This is the one
            # question the rule paths decide; validating a note that IS there is a separate
            # matter, handled below for every commit.
            files = _git("show", "--name-only", "--format=", sha).split()
            if any(f.startswith(p) for f in files for p in RULE_PATHS):
                bad.append((sha[:7], subject, "touches rule code but has no Matrix-Note: trailer"))
            continue
        # A trailer that is PRESENT but malformed used to sail through here and only surface
        # later, in generation — by which time the commit is merged and the message can no
        # longer be fixed. Validating it on the PR is the only point where the author can act,
        # so --check parses what it previously only detected the presence of.
        #
        # That validation now runs WHATEVER the commit touched. The rule-path test above used to
        # gate it as well, so a note on a commit outside those paths was never parsed at all: it
        # passed review, then was skipped at generation forever. That is how b13c700 — docs-only
        # — reached main carrying a note the generator could not read.
        raw = _git("log", "-1", f"--format=%H\x1f%aI\x1f%s\x1f%b", sha).strip("\n")
        try:
            # The slug only ever reaches the rendered entry, which validation never builds, so
            # it is deliberately not resolved here: _repo_slug() shells out to `git config --get
            # remote.origin.url`, which EXITS NONZERO in a repo with no remote — exactly what the
            # guard's own test fixtures are. Validating a trailer must not depend on having one.
            parse_commit(raw, "", strict=True)
        except TrailerProblem as e:
            bad.append((sha[:7], subject, str(e).split(": ", 1)[-1]))
    for sha, subject, why in bad:
        print(f"{sha} {why}\n         {subject}", file=sys.stderr)
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
