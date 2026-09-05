"""Actionable remediation exceptions, and the safety gate in front of a delivery-only retry.

`remediation_run.py` answers "how much is done". This module answers the next question — "who has
to do what, and what may ACP do on their behalf" — and it is PURE for the same reason that one is:
no database, no clock of its own, no HTTP, no provider SDK. Every refusal below can therefore be
tested against literals, which matters more here than it did there, because these functions decide
whether ACP writes to a customer's SharePoint library.

THE ONE RULE THIS FILE EXISTS TO ENFORCE. A delivery-only retry re-sends an artifact that has
ALREADY been produced and ALREADY been verified. It never re-applies a fix and never re-runs
verification, so it cannot change what the run claims about a document — the counters `applied`
and `verified` are untouched by construction, because nothing on this path writes them. That is
also why the gate below refuses rather than degrades: the moment ACP cannot PROVE the stored bytes
are the verified ones, "deliver them anyway" would publish an artifact whose provenance nobody can
state. `delivery_retry_decision` therefore refuses on unknown provenance exactly as loudly as it
refuses on a known-stale artifact, and says which of the two it was.

WHAT "STALE" MEANS, precisely, because it is the refusal most likely to be read as a bug:

  * the source document changed after ACP produced the correction — the corrected copy is a fix of
    bytes that no longer exist at the destination, and delivering it would silently revert someone
    else's edit;
  * the stored artifact's digest is not the digest recorded when it was verified — the object in
    ACP's own store is not the thing the verifier passed.

Both are refusals with a named code and a sentence a user can act on. Neither is repaired here.
"""
from __future__ import annotations

import datetime as _dt
import hashlib

# ── the five groups (PRD §6E, §11) ───────────────────────────────────────────

#: Every exception a run can raise, in the order a user should work them: what is irrecoverable
#: first, then what ACP can retry unattended, then what needs a person. ONE DOCUMENT LANDS IN
#: EXACTLY ONE GROUP — `classify_exception` returns a single key — so the group counts sum to the
#: number of documents needing attention rather than double-counting a document that is both
#: undelivered and awaiting review.
EXCEPTION_GROUPS: tuple[str, ...] = (
    "document_failure", "delivery_failure", "authoring_required",
    "review_required", "verification_failure",
)

#: What each group means and what may be done about it. `action` is the ONE scoped action the
#: group supports; `capability` is what the caller must hold for it (api/workspace_capability_map
#: maps the routes to the same names). A group whose action is `null` is a hand-off to another
#: surface — ACP has no automatic move to offer, and offering a button that does nothing is worse
#: than offering none.
GROUP_SPECS: dict[str, dict] = {
    "document_failure": {
        "label": "Failed documents",
        "summary": "No automatic attempts remain.",
        "action": "retry_document",
        "action_label": "Retry document",
        "capability": "remediate.run",
        "reapplies_fixes": True,
    },
    "delivery_failure": {
        "label": "Delivery failures",
        "summary": "The corrected copy exists and was verified; writing it to the source "
                   "provider did not succeed.",
        "action": "retry_delivery",
        "action_label": "Retry delivery only",
        "capability": "remediate.run",
        # The whole point. Named in the data so the UI can say it, rather than the UI asserting
        # it from a label it happens to render.
        "reapplies_fixes": False,
    },
    "authoring_required": {
        "label": "Needs authoring",
        "summary": "ACP has no substantive value to propose; a person must write one.",
        "action": None,
        "action_label": "Open in review",
        "capability": "remediate.review",
        "reapplies_fixes": False,
    },
    "review_required": {
        "label": "Individual review",
        "summary": "A human decision is required before the fix can be applied.",
        "action": None,
        "action_label": "Open in review",
        "capability": "remediate.review",
        "reapplies_fixes": False,
    },
    "verification_failure": {
        "label": "Verification failures",
        "summary": "A fix was applied but the re-scan did not observe the criterion clear. The "
                   "original is preserved and no corrected copy was delivered.",
        "action": "retry_document",
        "action_label": "Retry document",
        "capability": "remediate.run",
        "reapplies_fixes": True,
    },
}

#: The providers a corrected copy can be delivered to. Anything else is refused by name rather
#: than attempted — `local` uploads have no destination to write back to, and `blob` IS ACP's own
#: store, so "deliver to blob" would report a write that had already happened as a new one.
DELIVERY_PROVIDERS: tuple[str, ...] = ("sharepoint", "onedrive", "drive")

#: Why a delivery-only retry was refused. Every code carries a sentence in REFUSAL_MESSAGES; a
#: refusal without one is a programming error, which `refusal_message` surfaces rather than
#: papering over with a generic string.
REFUSAL_CODES: tuple[str, ...] = (
    "not_a_delivery_exception", "already_delivered", "artifact_missing",
    "artifact_provenance_unknown", "artifact_not_verified", "artifact_stale",
    "destination_unknown", "provider_unsupported", "run_cancelled", "retry_in_flight",
)

REFUSAL_MESSAGES: dict[str, str] = {
    "not_a_delivery_exception":
        "This document has no corrected copy waiting for delivery.",
    "already_delivered":
        "The corrected copy has already been written to the source provider.",
    "artifact_missing":
        "ACP has no stored corrected copy for this document, so there is nothing to deliver. "
        "Retry the document instead — that re-applies the approved fixes.",
    "artifact_provenance_unknown":
        "ACP cannot prove the stored copy is the one that passed verification: no content "
        "digest was recorded for it. Retry the document instead, which produces and verifies a "
        "fresh corrected copy.",
    "artifact_not_verified":
        "No fix on this document passed the independent re-check, so there is no verified "
        "corrected copy to deliver.",
    "artifact_stale":
        "The source document changed after this corrected copy was produced. Delivering it "
        "would overwrite the newer version with a fix of the older one. Retry the document to "
        "remediate the current version.",
    "destination_unknown":
        "ACP has no recorded destination for this document, so it cannot address the write.",
    "provider_unsupported":
        "Delivery-only retry is available for SharePoint, OneDrive and Google Drive. This run's "
        "documents came from somewhere else.",
    "run_cancelled":
        "This run was cancelled. Nothing further is written to the source provider.",
    "retry_in_flight":
        "A delivery for this document is already in progress.",
}


def refusal_message(code: str) -> str:
    """The sentence for a refusal code. An unknown code says so rather than inventing a reason."""
    return REFUSAL_MESSAGES.get(code) or f"Delivery-only retry refused ({code})."


# ── classification ───────────────────────────────────────────────────────────

def classify_exception(record: dict) -> tuple[str, str] | None:
    """The ONE exception group this document is in, with the reason code, or None when it is not
    an exception at all.

    PRECEDENCE, and why it is this order rather than another:

      1. `document_failure` — the queue has given up. Nothing else ACP could offer is true while
         that is; a document with no attempts left is not "awaiting review".
      2. `delivery_failure` — a verified corrected copy exists and has not reached the provider.
         It sits ABOVE the review groups deliberately: a document can be both undelivered and
         carrying an open review item, and burying the undelivered copy under "someone must
         decide something" is how a lost corrected copy stays lost. The corrective actions are
         different and independent, and this one is ACP's to take.
      3. `authoring_required` before `review_required` — both are a person's job, but they are
         different jobs. "Approve this alt text" and "write alt text; ACP has none to propose"
         cannot share a queue without the second looking like a slow version of the first.
      4. `verification_failure` — last, because a document that is also awaiting review is
         already routed to the person who will see the failed fix.
    """
    if not record:
        return None
    if record.get("outcome") == "failed":
        return "document_failure", str(record.get("reason") or "attempts_exhausted")
    if _has_undelivered_correction(record):
        return "delivery_failure", "corrected_copy_not_delivered"
    if record.get("review_pending"):
        if record.get("review_kind") == "authoring":
            return "authoring_required", "no_proposed_value"
        return "review_required", "human_decision_required"
    if int(record.get("fixes_applied") or 0) > int(record.get("fixes_verified") or 0):
        return "verification_failure", "fix_did_not_clear_on_recheck"
    return None


def _has_undelivered_correction(record: dict) -> bool:
    """A corrected copy ACP stored and the provider has not acknowledged.

    `stored_at` is the proof ACP produced one; `delivered_url` is the proof it reached the
    provider. Their difference is exactly PRD §11's delivery-failure class, and it is a fact about
    two columns rather than an inference from an error message nobody kept.
    """
    return bool(record.get("artifact_stored_at")) and not record.get("delivered_url")


# ── destination identity ─────────────────────────────────────────────────────

def destination_identity(record: dict) -> dict | None:
    """Where a corrected copy would be written, as a DURABLE address — or None when the run has
    not recorded one.

    NO CREDENTIALS AND NO SIGNED URLS (PRD §13). What comes back is the provider, the container
    ids the run itself recorded, and a stable `key` built from them. The key is what an
    idempotency record is anchored on, so it must be derivable identically on a later request
    from stored rows alone — which rules out anything session-scoped, including an access token,
    a signed link, or the id of the worker that happened to hold the lease.

    Returning None is a real answer and the caller refuses on it (`destination_unknown`). A
    plausible default — "the drive the signed-in user has open" — is precisely the inference PRD
    §6A forbids, and here it would not merely mislabel a panel, it would write a document into a
    library the run never touched.
    """
    provider = (record.get("provider") or "").strip().lower()
    if provider not in DELIVERY_PROVIDERS:
        return None
    if provider == "drive":
        # Drive addresses the mirror folder, not the source item: ACP's Drive delivery has always
        # been an upsert into a "Remediated" folder rather than an in-place overwrite, and the
        # retry must land in the same place the first attempt would have. The folder ID the
        # submission stamped into every job payload is preferred; the configured folder NAME is
        # the fallback, because find-or-create by that name is what produced the id in the first
        # place and resolves to the same folder for the same account.
        folder = record.get("destination_folder_id") or record.get("destination_folder")
        if not folder:
            return None
        parts = ("drive", "folder", str(folder))
    else:
        drive_id = record.get("destination_drive_id")
        folder = record.get("destination_folder_id") or record.get("destination_folder")
        if not (drive_id and folder):
            return None
        parts = (provider, "drive", str(drive_id), "folder", str(folder))
    return {
        "provider": provider,
        "drive_id": record.get("destination_drive_id") or None,
        "folder_id": record.get("destination_folder_id") or None,
        "folder": record.get("destination_folder") or None,
        "item_id": record.get("destination_item_id") or None,
        "label": record.get("destination_label") or None,
        "key": ":".join(parts),
    }


def delivery_idempotency_key(run_id: str, file: str, destination_key: str,
                             artifact_digest: str) -> str:
    """The identity of ONE delivery operation: this artifact, to this destination, for this run.

    DELIBERATELY CONTAINS NO TIME AND NO NONCE. Two identical retry requests — a double-click, a
    dropped response the browser retried, two operators pressing the button at once — compute the
    SAME key and therefore claim the same durable row, which is what makes "duplicate requests
    produce one delivery operation" a property of the data rather than a race the UI has to win.

    It DOES contain the artifact digest, so a genuinely new corrected copy is a genuinely new
    operation. Keying on (run, document) alone would make the second delivery of a re-remediated
    document look like a replay of the first and silently do nothing.

    `hashlib.sha256` over NUL-separated fields, matching publish.publication_key's construction —
    the separator is what stops ("a", "bc") and ("ab", "c") colliding.
    """
    raw = "\0".join((str(run_id), str(file), str(destination_key), str(artifact_digest)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── the delivery-only retry gate ─────────────────────────────────────────────

def _parse(ts) -> _dt.datetime | None:
    if not ts:
        return None
    if isinstance(ts, _dt.datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)
    try:
        out = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=_dt.timezone.utc)


def artifact_staleness(record: dict) -> str | None:
    """Why this stored artifact may not be delivered, or None when it is provably the verified one.

    Three questions, asked in the order that a "no" is most informative:

      * is there a digest at all? Without one there is no statement to check, and "the bytes are
        probably fine" is not a provenance. Rows written before ACP recorded a digest land here,
        and they are refused — the honest outcome, and one a re-run clears.
      * does the stored digest still match the object? A mismatch means the store holds something
        other than what the verifier passed.
      * did the SOURCE move on? A corrected copy of last week's document is not a correction of
        this week's, however faithfully it was verified.
    """
    digest = (record.get("artifact_digest") or "").strip()
    if not digest:
        return "artifact_provenance_unknown"
    observed = (record.get("artifact_observed_digest") or "").strip()
    if observed and observed != digest:
        return "artifact_stale"
    stored_at = _parse(record.get("artifact_stored_at"))
    source_modified = _parse(record.get("source_modified"))
    if stored_at is not None and source_modified is not None and source_modified > stored_at:
        return "artifact_stale"
    return None


def delivery_retry_decision(record: dict, *, cancelled: bool = False,
                            in_flight: bool = False) -> dict:
    """May ACP re-send this document's corrected copy, and under what identity?

    Returns `{"eligible": bool, "code": str|None, "message": str|None, "destination": dict|None,
    "idempotency_key": str|None}`. Every ineligible answer carries a code AND a sentence, because
    a greyed-out button with no explanation is the thing this whole slice replaces.

    Note what is NOT here: no re-application, no re-verification, no "fix it first and then
    deliver". The eligible path hands back an address and a key. If the artifact cannot be
    delivered as it stands, the answer is a refusal that names the document-level retry as the
    remedy — a different action, with a different capability, that the user chooses.
    """
    def _no(code: str) -> dict:
        return {"eligible": False, "code": code, "message": refusal_message(code),
                "destination": None, "idempotency_key": None}

    if cancelled:
        return _no("run_cancelled")
    group = classify_exception(record)
    if not group or group[0] != "delivery_failure":
        return _no("already_delivered" if record.get("delivered_url")
                   else ("artifact_missing" if not record.get("artifact_stored_at")
                         else "not_a_delivery_exception"))
    if int(record.get("fixes_verified") or 0) <= 0:
        return _no("artifact_not_verified")
    stale = artifact_staleness(record)
    if stale:
        return _no(stale)
    provider = (record.get("provider") or "").strip().lower()
    if provider not in DELIVERY_PROVIDERS:
        return _no("provider_unsupported")
    destination = destination_identity(record)
    if not destination:
        return _no("destination_unknown")
    if in_flight:
        return _no("retry_in_flight")
    return {
        "eligible": True, "code": None, "message": None, "destination": destination,
        "idempotency_key": delivery_idempotency_key(
            record.get("run_id") or "", record.get("file") or "", destination["key"],
            record.get("artifact_digest") or ""),
    }


# ── the grouped payload the panel renders ────────────────────────────────────

#: Fields of an exception row that may cross the API boundary. A WHITELIST, for the reason
#: store._issue_provenance is one: `record` is assembled from several tables and could grow a
#: column tomorrow, and a projection that copies whatever it is handed is an open channel out of
#: the database. Filenames and provider container names are in here — that is what makes the read
#: owner-scoped (PRD §13) — and extracted document CONTENT is not, at all.
_ROW_FIELDS: tuple[str, ...] = (
    "file", "group", "reason", "outcome", "review_items", "review_kind",
    "fixes_applied", "fixes_verified", "attempts", "max_attempts",
    "artifact_stored_at", "artifact_digest", "artifact_bytes",
    "delivered_url", "evidence_url", "corrected_copy_url",
)


def exception_row(record: dict, *, cancelled: bool = False) -> dict | None:
    """One document's exception, projected for the client, with its action already decided here.

    THE SERVER DECIDES ELIGIBILITY, not the browser. `remediation_run.py`'s docstring says the
    client never derives a terminal state; the same rule applies with more force to an action that
    writes to a customer's estate. The row carries `action`, `action_enabled` and, when it is not,
    `action_reason` — so the panel renders a decision rather than making one.
    """
    classified = classify_exception(record)
    if not classified:
        return None
    group, reason = classified
    spec = GROUP_SPECS[group]
    row = {key: record.get(key) for key in _ROW_FIELDS if key in record}
    row["file"] = record.get("file")
    row["group"] = group
    row["reason"] = reason
    row["action"] = spec["action"]
    row["action_label"] = spec["action_label"]
    row["capability"] = spec["capability"]
    row["reapplies_fixes"] = spec["reapplies_fixes"]
    if group == "delivery_failure":
        decision = delivery_retry_decision(record, cancelled=cancelled)
        row["action_enabled"] = decision["eligible"]
        row["action_reason"] = decision["message"]
        row["action_code"] = decision["code"]
        row["destination"] = decision["destination"] or _public_destination(record)
    elif spec["action"] is None:
        row["action_enabled"] = False
        row["action_reason"] = None
        row["action_code"] = None
    else:
        row["action_enabled"] = not cancelled
        row["action_reason"] = refusal_message("run_cancelled") if cancelled else None
        row["action_code"] = "run_cancelled" if cancelled else None
    return row


def _public_destination(record: dict) -> dict | None:
    """The destination as far as it is known, for a row whose retry was refused.

    A refused row still says WHERE the copy was meant to go — that is the fact an administrator
    acts on — but it never gains a key it is not entitled to, so `key` is omitted here.
    """
    provider = (record.get("provider") or "").strip().lower()
    if not provider:
        return None
    return {"provider": provider, "label": record.get("destination_label") or None,
            "drive_id": record.get("destination_drive_id") or None,
            "folder": record.get("destination_folder") or None}


def build_exception_groups(records, *, cancelled: bool = False) -> list[dict]:
    """Every exception in the run, grouped by the response it needs.

    Groups come back in EXCEPTION_GROUPS order and empty groups are dropped: a heading reading
    "Failed documents · 0" is noise on a screen whose whole job is to say what needs doing.
    """
    rows: list[dict] = []
    for record in records or ():
        row = exception_row(record, cancelled=cancelled)
        if row:
            rows.append(row)
    out: list[dict] = []
    for key in EXCEPTION_GROUPS:
        members = [row for row in rows if row["group"] == key]
        if not members:
            continue
        spec = GROUP_SPECS[key]
        out.append({
            "key": key, "label": spec["label"], "summary": spec["summary"],
            "action": spec["action"], "action_label": spec["action_label"],
            "capability": spec["capability"], "reapplies_fixes": spec["reapplies_fixes"],
            "documents": len(members),
            "actionable": sum(1 for row in members if row.get("action_enabled")),
            "items": sorted(members, key=lambda row: (row.get("file") or "")),
        })
    return out


# ── run controls ─────────────────────────────────────────────────────────────

#: The controls a remediation run can offer, and — for each — the ONE thing the backend can
#: truthfully do. Written down here rather than in the route because the panel must be able to
#: state the limit before the user presses the button: `scope` is rendered, not just enforced.
CONTROL_SPECS: dict[str, dict] = {
    "cancel": {
        "label": "Stop run",
        "scope": "Stops work that has not started and asks active attempts to stop at their next "
                 "checkpoint. Documents already corrected keep their corrected copies.",
        "capability": "remediate.run",
    },
    "pause": {
        "label": "Pause run",
        "scope": "Holds work that has not been claimed. Attempts already in flight run to "
                 "completion — ACP cannot suspend a document mid-fix.",
        "capability": "remediate.run",
    },
    "resume": {
        "label": "Resume run",
        "scope": "Releases the held work back to the queue.",
        "capability": "remediate.run",
    },
}


def run_controls(*, state: str, counters: dict | None = None, paused: bool = False,
                 cancel_requested: bool = False, cancelled: bool = False,
                 terminal: bool = False) -> list[dict]:
    """Which run controls are offered, and why each one is or is not available right now.

    ONLY WHAT THE BACKEND CAN TRUTHFULLY DO. `remediation_run.RUN_STATES` has carried `paused`
    since Phase 1 with a comment saying it is declared and never derived, because ACP had no pause
    control and inferring one from an idle queue would report a capacity fact as a decision. This
    function is the other half of that sentence: pause is offered now because there is a durable
    hold behind it, and its `scope` says exactly what the hold does and does not reach — held work
    is work nobody has claimed, and an attempt in flight finishes.

    An unavailable control comes back with `available: false` and a reason, rather than being
    omitted. A control that disappears reads as a bug in the panel; a control that says "nothing
    is waiting to be held" reads as an answer.
    """
    counters = counters or {}
    waiting = int(counters.get("waiting") or 0)
    processing = int(counters.get("processing") or 0)
    out: list[dict] = []

    def _control(key: str, available: bool, reason: str | None, **extra) -> dict:
        spec = CONTROL_SPECS[key]
        return {"action": key, "label": spec["label"], "scope": spec["scope"],
                "capability": spec["capability"], "available": available,
                "reason": reason, **extra}

    if cancelled:
        out.append(_control("cancel", False, "This run is already cancelled."))
    elif cancel_requested:
        out.append(_control("cancel", False, "Stopping — waiting for active attempts to finish."))
    elif terminal:
        out.append(_control("cancel", False, "This run has finished."))
    elif waiting + processing == 0:
        out.append(_control("cancel", False, "No work is outstanding."))
    else:
        out.append(_control("cancel", True, None, in_flight=processing))

    if cancelled or cancel_requested or terminal:
        out.append(_control("pause", False, "This run is no longer accepting work."))
    elif paused:
        out.append(_control("pause", False, "Already paused."))
    elif waiting == 0:
        # The honest refusal. With nothing unclaimed there is nothing a pause could hold, and a
        # button that would hold zero documents while three are mid-fix promises a stop it cannot
        # deliver.
        out.append(_control("pause", False,
                            "Nothing is waiting to be held."
                            + (f" {processing} attempt{'' if processing == 1 else 's'} already in "
                               "flight will finish." if processing else "")))
    else:
        out.append(_control("pause", True, None, holds=waiting, in_flight=processing))

    if paused and not (cancelled or cancel_requested):
        out.append(_control("resume", True, None, holds=waiting))
    else:
        out.append(_control("resume", False,
                            "This run is not paused." if not paused else "This run is stopping."))
    return out


# ── group action outcomes ────────────────────────────────────────────────────

def summarize_outcomes(results) -> dict:
    """One honest sentence about a group action, plus the per-document detail behind it.

    NEVER "ALL DONE" WHEN IT WAS NOT. A group retry over twelve documents that starts nine,
    refuses two and fails one is reported as exactly that; the summary line names each non-success
    count, and `results` keeps every document's own outcome so the panel can show which. The
    failure this guards against is the ordinary one — a caller reading `200 OK` off the request
    and telling the user the group succeeded.
    """
    rows = list(results or ())
    counts = {"started": 0, "refused": 0, "failed": 0, "duplicate": 0}
    for row in rows:
        outcome = (row or {}).get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    total = len(rows)
    parts: list[str] = []
    if counts["started"]:
        parts.append(f"{counts['started']} delivery{'' if counts['started'] == 1 else ' operations'} started")
    if counts["duplicate"]:
        parts.append(f"{counts['duplicate']} already in progress")
    if counts["refused"]:
        parts.append(f"{counts['refused']} refused")
    if counts["failed"]:
        parts.append(f"{counts['failed']} could not be started")
    return {
        "requested": total,
        "started": counts["started"], "duplicate": counts["duplicate"],
        "refused": counts["refused"], "failed": counts["failed"],
        "complete_success": total > 0 and counts["started"] + counts["duplicate"] == total,
        "summary": " · ".join(parts) if parts else "Nothing to do",
        "results": rows,
    }


# ── audit ────────────────────────────────────────────────────────────────────

#: What an exception-action audit event may carry (PRD §13). Actor, run, document, destination,
#: action, outcome — and nothing else. The destination is named by its durable identity, never by
#: a signed URL or a token, and no field here can hold text extracted from a document.
_AUDIT_FIELDS: tuple[str, ...] = (
    "actor", "run_id", "file", "action", "outcome", "destination_provider",
    "destination_key", "idempotency_key", "reason",
)


def audit_payload(*, actor: str | None, run_id: str | None, file: str | None, action: str,
                  outcome: str, destination: dict | None = None,
                  idempotency_key: str | None = None, reason: str | None = None) -> dict:
    """The bounded record of one exception action.

    A WHITELIST rather than a dump, and the whitelist is the point: `destination` arrives as a
    dict this module built, but the shape of that dict is free to grow, and an audit row that
    copies whatever it is given is how a signed URL reaches a log. Only `provider` and `key` are
    taken from it, and `key` is by construction made of container ids — see destination_identity.
    """
    row = {
        "actor": actor or None, "run_id": run_id or None, "file": file or None,
        "action": action, "outcome": outcome,
        "destination_provider": (destination or {}).get("provider") or None,
        "destination_key": (destination or {}).get("key") or None,
        "idempotency_key": idempotency_key or None,
        "reason": reason or None,
    }
    return {key: row[key] for key in _AUDIT_FIELDS if row.get(key) is not None}


# ── composition ──────────────────────────────────────────────────────────────

def compose_records(*, outcomes: dict, documents, run_id: str | None = None) -> list[dict]:
    """Join the run's per-document OUTCOME to its per-document exception FACTS.

    `outcomes` is {file: (outcome, reason)} as `remediation_run.classify_document` returns them;
    `documents` is `store.remediation_exception_facts`'s rows. Two sources because they answer
    two questions — the queue knows whether attempts remain, and file_records knows whether a
    corrected copy exists — and neither can answer the other's.

    A document present in the facts but ABSENT from the outcomes is carried through with no
    outcome rather than dropped. That is the shape of a document whose job row was pruned or
    predates the batch, and it can still hold an undelivered corrected copy; dropping it would
    make a lost artifact invisible, which is the failure the delivery-failure class exists to
    surface.
    """
    out: list[dict] = []
    for row in documents or ():
        file = row.get("file")
        outcome, reason = (outcomes or {}).get(file, (None, None))
        out.append({**row, "run_id": row.get("run_id") or run_id,
                    "outcome": outcome, "reason": row.get("reason") or reason})
    return out
