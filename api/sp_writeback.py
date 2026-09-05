"""What has to be true before ACP overwrites a document in SharePoint.

THE ORDER IS THE BUG. `routes/sharepoint.sharepoint_upload`'s in-place path archives the original
and *then* replaces it, and nothing between those two steps asked whether the replace could
succeed. A file somebody has checked out fails the replace — after the copy has already landed in
`SP_ARCHIVE_FOLDER/<today>/`. The original is not lost (the archive is a copy, not a move), but
the archive folder accumulates dated copies of documents that were never replaced, indistinguishable
from the ones that were, in the folder a customer would go to if they ever needed to roll a
remediation back.

The worse case is quieter. A DECLARED RECORD is a document the tenant has locked under a retention
policy, and overwriting one is a compliance event rather than a failed write. `sp_metadata` has read
`_IsRecord` and `_ComplianceTag` since Phase 2 and its own docstring calls check-out "the
precondition Phase 5 has to check" — the fields were read for this purpose and nothing consumed
them.

READ LIVE, NOT FROM THE SCAN. The inventory's `checked_out_by` is as old as the scan, and a file
checked out since then is exactly the case this exists to catch. That is one Graph call per
write-back, which is the opposite trade from the walk: a write-back is per-file, approval-gated,
and capped at 500 for the pilot, so a call here is proportionate where the same call in a 30-site
listing is an outage (tests/test_sp_scale.py).

WHAT BLOCKS AND WHAT DOES NOT, because refusing too much is its own failure:

  * checked out — BLOCKS. The write will fail regardless; refusing first is the same outcome
    without the orphan, and it can name who holds the lock.
  * declared record — BLOCKS. Not a failed write but a governance decision, and not ACP's to make.
  * a retention LABEL alone — does NOT block. A label commonly sets a retention period without
    locking edits, so refusing on it would turn away writes that would have succeeded. Reported as
    context so a human approving the write sees it.

AND AN UNREADABLE PRECONDITION DOES NOT BLOCK EITHER. A tenant that refuses the listItem expansion
would otherwise have every write-back refused by a check that never ran. Proceeding is exactly
today's behaviour and Graph still enforces the real rules; what changes is that the response says
the preconditions were UNVERIFIED rather than implying they were clear. "We did not look" must not
read as "we looked and it was fine" — the same distinction the whole availability contract in
sp_metadata is built on.
"""
from __future__ import annotations

import sp_metadata

#: A blocker's `code`, for a caller that wants to branch rather than read prose.
CHECKED_OUT = "checked_out"
DECLARED_RECORD = "declared_record"


def preconditions(fields: dict | None, *, checked: bool = True) -> dict:
    """Whether this item may be overwritten, from its listItem `fields` bag.

    `checked=False` says the bag could not be read at all — the caller then gets no blockers and
    a report that says so, rather than a clean bill of health it did not earn.

    Returns `{"ok", "checked", "blockers": [{"code", "message"}], "notes": [...]}`. Pure and
    synchronous: the Graph call is the caller's, so the decision itself is testable without one.
    """
    if not checked:
        return {"ok": True, "checked": False, "blockers": [],
                "notes": ["Write-back preconditions could not be read for this item, so it is "
                          "NOT known whether it is checked out or declared as a record. The "
                          "write was allowed to proceed and Microsoft Graph will enforce its own "
                          "rules; this is not a clean check."]}

    f = fields or {}
    blockers: list[dict] = []
    notes: list[str] = []

    who = sp_metadata.checkout_user(f)
    if who:
        blockers.append({
            "code": CHECKED_OUT,
            "message": (f"This document is checked out to {who}. Replacing it would fail, and "
                        f"the original would already have been copied into the archive folder by "
                        f"then — leaving a dated copy of a document that was never replaced. Ask "
                        f"them to check it in, then retry."),
        })

    if sp_metadata.is_record(f) is True:
        tag = sp_metadata.compliance_tag(f)
        blockers.append({
            "code": DECLARED_RECORD,
            "message": ("This document is declared as a record in SharePoint"
                        + (f" under '{tag}'" if tag else "")
                        + ". Overwriting a record is a governance decision, not a remediation — "
                          "ACP will not make it. Undeclare the record, or publish the remediated "
                          "copy alongside instead of replacing."),
        })

    # Context, deliberately NOT a blocker: a retention label commonly sets a period without
    # locking edits, and refusing on it would turn away writes that would have succeeded.
    tag = sp_metadata.compliance_tag(f)
    if tag and sp_metadata.is_record(f) is not True:
        notes.append(f"This document carries the retention label '{tag}'. That does not block a "
                     f"replace, but the remediated version inherits the label's policy.")

    return {"ok": not blockers, "checked": True, "blockers": blockers, "notes": notes}


def read_state(token: str, drive_id: str | None, item_id: str, *, get=None) -> dict:
    """The live precondition state for one item — `preconditions()` over a fresh listItem read.

    Never raises. A precondition check that can fail the write it is guarding would be worse than
    no check: the fallback is `checked=False`, which proceeds and says it did not verify.

    `get` is the seam the tests use; production passes None and gets `scanner._sp_get`.
    """
    import scanner
    fetch = get or scanner._sp_get
    base = f"{scanner.GRAPH}/drives/{drive_id}" if drive_id else f"{scanner.GRAPH}/me/drive"
    # Only the three columns the decision turns on. A bare `$expand=fields` would pull the
    # tenant's entire column set per write-back for three values.
    url = (f"{base}/items/{item_id}/listItem"
           "?$expand=fields($select=CheckoutUser,CheckoutUserLookupId,_IsRecord,_ComplianceTag)")
    try:
        data = fetch(token, url)
    except Exception:  # noqa: BLE001 — see the docstring: never fail the write from here
        return preconditions(None, checked=False)
    fields = (data or {}).get("fields")
    if not isinstance(fields, dict):
        # A listItem with no fields bag is not a clean read of an unlocked item; it is a shape
        # this code does not understand, and saying so costs nothing.
        return preconditions(None, checked=False)
    return preconditions(fields)
