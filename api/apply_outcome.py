"""Why an APPROVED review row is still unapplied — read back from the decision log for the card.

_apply_one_value_kind (handlers.py) writes an approved value into a working copy, re-scans it,
and credits the row only if the criterion cleared. When it does not clear — or the re-scan could
not run — it logs `apply.unverified` and returns the PRE-write bytes: the row stays approved and
unapplied, the document is unchanged, and until this module existed nothing told the reviewer.
They approved, clicked, and saw nothing. On pptx 1.4.5 that was every approval, for months.

This module is deliberately pure (rows and decisions in, outcome out) so the parsing is testable
without a database, and deliberately conservative: it asserts an outcome only when the decision
names this row's criterion, and only for decisions logged after the row's approval — an older
failure belonged to an earlier attempt, not to what the reviewer just did.

The decision carries no rule_id (see handlers._apply_one_value_kind — adding one there would
land on lines another PR is editing); the criteria are only in `detail`, rendered as a Python
list — `['1.4.5', '1.4.9']` — so that is what is parsed here.
"""
from __future__ import annotations

import re

ACTION = "apply.unverified"
STILL_FAILING = "still_failing"
COULD_NOT_VERIFY = "could_not_verify"
# Nothing reached the document at all: every approved locator resolved to no element. Distinct
# from STILL_FAILING (the value went in and the criterion still failed) because the reviewer's
# next move is different — there is nothing to re-check, the description named an image this
# document cannot carry alt text for, and re-running the apply job will not change that.
NOTHING_WRITTEN = "nothing_written"

_SC_RE = re.compile(r"'(\d+\.\d+\.\d+)'")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
# could-not-verify detail, as written by _apply_one_value_kind:
#   "wrote N <noun> value(s) but could not verify ['1.4.5']: <reason>. Credit withheld; the
#    approved value is kept for retry"
_REASON_RE = re.compile(r"could not verify \[[^\]]*\]:\s*(.*?)(?:\.\s*Credit withheld|$)", re.S)


def normalise_sc(rule_id) -> str:
    """'SC_1_4_5' / '1.4.5' / '1.4.5 Images of Text' → '1.4.5'; anything else → ''."""
    s = str(rule_id or "").strip()
    m = re.match(r"^(?:SC[_\s]?)?(\d+)[._](\d+)[._](\d+)", s)
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""


def parse_unverified(detail: str | None) -> dict:
    """{outcome, criteria, reason} from an apply.unverified detail string; {} if unrecognised.

    Exactly THREE shapes are written by _apply_one_value_kind. Anything else is not asserted on —
    a decision this code cannot read must never become a claim on the card.

    The third — "reach no image in this document" — is the wedge case, and it was silent before
    it existed: the lane returned at `if not applied:` without logging, so a reviewer whose
    approved description named an unreachable image (a picture on a pptx slideLayout, a footnote
    image, a VML sheet graphic) got no card and a file that never published.
    """
    text = " ".join(str(detail or "").split())
    if not text:
        return {}
    criteria = sorted(set(_SC_RE.findall(text)))
    if "could not verify" in text:
        m = _REASON_RE.search(text)
        return {"outcome": COULD_NOT_VERIFY, "criteria": criteria,
                "reason": (m.group(1).strip() if m else "")}
    if "still fails on re-scan" in text:
        return {"outcome": STILL_FAILING, "criteria": criteria, "reason": ""}
    # Matched on its own wording rather than by elimination: the detail says "wrote no" and names
    # no reason clause, so neither shape above can claim it, and this stays a positive test.
    if "reach no image in this document" in text:
        return {"outcome": NOTHING_WRITTEN, "criteria": criteria, "reason": ""}
    return {}


def _not_before(ts: str | None, since: str | None) -> bool:
    """ts is not earlier than since. Lenient: when either side is not an ISO date, do not
    exclude — a missing reviewed_at must not hide a real outcome."""
    if not ts or not since or not _ISO_RE.match(ts) or not _ISO_RE.match(since):
        return True
    return ts >= since


def apply_outcome_for(row: dict, decisions: list[dict]) -> dict | None:
    """The newest apply.unverified decision that explains why THIS approved row is unapplied.

    None for anything that is not an approved, unapplied row, and for a row no decision names.
    """
    if not row or str(row.get("status") or "") != "approved" or row.get("applied"):
        return None
    sc = normalise_sc(row.get("rule_id"))
    since = row.get("reviewed_at")
    best: dict | None = None
    for d in decisions or []:
        if d.get("action") != ACTION:
            continue
        if d.get("scan_id") != row.get("scan_id") or d.get("file") != row.get("file"):
            continue
        ts = str(d.get("ts") or "")
        if not _not_before(ts, since):
            continue
        parsed = parse_unverified(d.get("detail"))
        if not parsed:
            continue
        if sc and parsed["criteria"] and sc not in parsed["criteria"]:
            continue
        if best is None or ts > best["ts"]:
            best = {**parsed, "ts": ts}
    return best


def annotate_apply_outcomes(rows: list[dict], decisions: list[dict]) -> list[dict]:
    """Attach `apply_outcome` to every row it applies to, in place. Rows it does not apply to
    are left untouched — no key — so the wire shape of a pending row does not change."""
    for r in rows:
        out = apply_outcome_for(r, decisions)
        if out:
            r["apply_outcome"] = out
    return rows
