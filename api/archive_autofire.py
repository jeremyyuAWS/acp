"""Safe lifecycle archive auto-fire (R9) — the pure decision layer.

WHAT THIS IS FOR. api/disposition.py can already tell you which files an archive rule SELECTS,
and routes/disposition.py can already move one when a human approves it. What did not exist was a
lane that moves a file with NO human in the loop, and the reason it did not exist is the reason
this module is mostly refusals: an archive rule fires on age, and age is not evidence that
anything has been replaced. "Not touched in three years" describes a finished project's records
as accurately as it describes a superseded draft, and only one of those may be moved unattended.

So the rule this module exists to enforce, and the one every function here is written to make
hard to violate:

    AGE, FILENAME SIMILARITY, AND INACTIVITY NEVER AUTHORIZE A MOVE.

Auto-fire needs DURABLE EVIDENCE that a specific newer item supersedes this specific older one,
carried by STABLE SOURCE IDENTIFIERS — a Graph item id, not a name. Filenames are the tempting
signal and the disqualified one: `Clinical-Access-v2.docx` and `Clinical-Access-v3.docx` look like
a version pair and are, routinely, two unrelated documents in two unrelated libraries. Evidence
without an item id is not evidence here; see `evidence_problem`.

PURE, AND DELIBERATELY SO. Nothing in this module reads a database, calls Graph, or touches a
file. It takes facts somebody else gathered and returns a decision plus the reason for it, which
is what makes every branch below testable without a tenant — including the ones that must fail
closed, which are exactly the branches an integration test cannot reach on demand. The execution
side lives in api/archive_execution.py; the provider calls live in api/archive_sources.py.

THE THREE-VALUED LOGIC IS THE SAFETY MECHANISM. Every preflight check answers pass, fail, or
UNKNOWN, and unknown is never rounded to either neighbour. A tenant that refuses the listItem
expansion cannot be read for legal hold; that is not "no hold found" and must not become one.
This mirrors api/sp_writeback.py's own distinction — "we did not look" must not read as "we
looked and it was fine" — with the opposite default, because a write-back is a human-approved
action on one file and this is an unattended action on a queue. sp_writeback proceeds on an
unreadable precondition and says so; auto-fire routes it to a human.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from datetime import datetime, timedelta, timezone

# ── Sources ──────────────────────────────────────────────────────────────────
#
# SharePoint and OneDrive are both Microsoft Graph drives: an item has a drive-scoped id that
# survives a move, an eTag that changes when the item does, a PATCH that moves it by
# parentReference, and — the part that decides it — `_IsRecord`/`_ComplianceTag`, which is how a
# legal hold becomes readable at all.
#
# GOOGLE DRIVE IS OUT, and the PRD asks for a reason rather than a preference. Drive has stable
# ids and a real move (addParents/removeParents — disposition.execute_action performs one today),
# so it clears "stable identity and move semantics". What it does not clear is the check ABOVE
# those: ACP holds no Drive read of a retention lock, a legal hold or a records declaration, so
# "no hold blocks this move" would be an assertion about something never looked at. The PRD says
# retention uncertainty fails closed; on Drive every item is uncertain, so every item would fail
# closed, and a lane that refuses everything is worse than no lane — it looks like it works.
# Recommendation-only is the honest state for Drive, and it is what `source_problem` returns.
AUTO_SOURCES = ("sharepoint", "onedrive")

#: Why a source is recommendation-only, keyed by source. Stated per source rather than as one
#: "unsupported" string because the reasons are different and a reader acting on them needs to
#: know which one applies to their estate.
_SOURCE_REFUSALS = {
    "drive": ("Google Drive is recommendation-only: ACP cannot read a Drive legal hold, retention "
              "lock or records declaration, so it cannot show that no hold blocks the move."),
    "local": "Local and demo files are recommendation-only — there is no source system to move them in.",
    "smb": ("SMB shares are recommendation-only: a file share carries no durable item identity, so "
            "a moved file cannot be verified afterwards as the one that was evaluated."),
}


def source_problem(source: str | None) -> str:
    """Why `source` may not auto-fire, or '' when it may."""
    key = (source or "").strip().lower()
    if key in AUTO_SOURCES:
        return ""
    return _SOURCE_REFUSALS.get(key) or (
        f"Source '{source or 'not recorded'}' is recommendation-only — automatic archival is "
        f"supported for {' and '.join(AUTO_SOURCES)} only.")


# ── Supersession evidence ────────────────────────────────────────────────────
#
# The four deterministic signals the PRD approves, and nothing else. Each is a claim somebody
# else already made about these two items — ACP is reading a link, never inferring one.

#: `retentionOf` / `supersedes` metadata on the newer item naming the older one.
METADATA_LINK = "metadata_link"
#: A configured lifecycle rule identifies a stable document family and a strictly newer version.
RULE_FAMILY = "rule_family"
#: SharePoint version/publication metadata identifies a newer APPROVED replacement.
SP_VERSION = "sp_version"
#: An administrator already confirmed this document-family mapping, and the audit record holds it.
ADMIN_MAPPING = "admin_mapping"

EVIDENCE_TYPES = (METADATA_LINK, RULE_FAMILY, SP_VERSION, ADMIN_MAPPING)

EVIDENCE_LABELS = {
    METADATA_LINK: "Replacement metadata names this document (retentionOf / supersedes)",
    RULE_FAMILY: "A lifecycle rule identifies a document family and a strictly newer version",
    SP_VERSION: "SharePoint version metadata names a newer approved replacement",
    ADMIN_MAPPING: "An administrator confirmed this document-family mapping",
}

#: Evidence a rule FAMILY produced is the weakest of the four — it is ACP's own configured
#: grouping rather than a claim the tenant's own metadata makes — so it alone requires the
#: replacement to also be a strictly newer version of the same family, checked in
#: `evidence_problem`. The other three carry the tenant's own assertion of the link.


def evidence_problem(evidence: dict | None) -> str:
    """Why one evidence record is not usable, or '' when it is.

    The stable-identifier requirement is enforced HERE rather than at the point of use, because
    "the evidence had no item id" is the failure that would otherwise be discovered after a file
    had been moved on the strength of two similar filenames.
    """
    e = evidence or {}
    kind = e.get("type")
    if kind not in EVIDENCE_TYPES:
        return f"Unknown evidence type {kind!r}."
    if not str(e.get("source_item_id") or "").strip():
        return "Evidence carries no stable identifier for the document being archived."
    if not str(e.get("replacement_item_id") or "").strip():
        return "Evidence carries no stable identifier for the replacement document."
    if str(e.get("source_item_id")).strip() == str(e.get("replacement_item_id")).strip():
        return "Evidence names the same item as both the document and its replacement."
    if kind == RULE_FAMILY:
        # A family grouping is ACP's own, so it has to say WHICH family and show the version
        # ordering it claims. Without both it is a filename heuristic wearing a type name.
        if not str(e.get("family") or "").strip():
            return "Document-family evidence does not name the family it grouped these items into."
        if not _strictly_newer(e.get("replacement_version"), e.get("source_version")):
            return ("Document-family evidence does not show the replacement is a strictly newer "
                    "version of the same family.")
    if kind == SP_VERSION and not e.get("replacement_approved"):
        # SharePoint's moderation status is the difference between a published replacement and a
        # colleague's unapproved draft, and archiving the live document in favour of a draft is
        # the exact outcome this lane must not produce.
        return "SharePoint version evidence does not show the replacement is approved/published."
    if kind == ADMIN_MAPPING and not str(e.get("confirmed_by") or "").strip():
        return "Administrator-confirmed mapping does not record who confirmed it."
    if not str(e.get("replacement_modified") or "").strip():
        return "Evidence does not record when the replacement was last modified."
    return ""


def _strictly_newer(replacement, source) -> bool:
    """Version ordering that refuses anything it cannot order, rather than guessing.

    Compares dotted numeric versions ("3.0" > "2.7") and plain integers. A version it cannot
    parse on either side is not "probably newer" — it is unordered, and returns False.
    """
    def parts(v):
        text = str(v if v is not None else "").strip()
        if not text:
            return None
        bits = []
        for chunk in text.split("."):
            chunk = chunk.strip()
            if not chunk.isdigit():
                return None
            bits.append(int(chunk))
        return bits or None

    a, b = parts(replacement), parts(source)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + [0] * (width - len(a)) > b + [0] * (width - len(b))


def usable_evidence(evidence: list[dict] | None, policy: dict) -> tuple[list[dict], list[str]]:
    """Split `evidence` into the records this policy accepts and the reasons the rest were rejected.

    Two independent gates, and they fail differently on purpose: a record can be malformed (no
    item id — a defect in whoever produced it) or well-formed but of a type this tenant did not
    authorize (a policy decision). Both are reported, because "we found evidence and refused it"
    and "we found none" lead a reader to different next actions.
    """
    required = set(policy.get("required_evidence") or ())
    keep, rejected = [], []
    for record in evidence or []:
        problem = evidence_problem(record)
        if problem:
            rejected.append(problem)
            continue
        if required and record.get("type") not in required:
            rejected.append(
                f"{EVIDENCE_LABELS.get(record.get('type'), record.get('type'))} is not among the "
                f"evidence types this policy requires.")
            continue
        keep.append(record)
    return keep, rejected


def replacement_age_days(evidence: dict, now: datetime) -> float | None:
    """How long the replacement has existed in its current form, or None if unreadable.

    None is not zero. A minimum replacement age exists so that a replacement uploaded minutes ago
    — and possibly about to be corrected or withdrawn — cannot immediately retire the document it
    replaces; an unreadable timestamp cannot show that period has elapsed, so it blocks.
    """
    stamp = _parse_iso(evidence.get("replacement_modified"))
    if stamp is None:
        return None
    return (now - stamp).total_seconds() / 86400.0


def _parse_iso(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── Policy ───────────────────────────────────────────────────────────────────

#: Every field an administrator can set, with the DEFAULT that ships. Read the defaults as the
#: product's posture rather than as placeholders: disabled, dry-run, hierarchy preserved, and a
#: ceiling low enough that a misconfiguration is a bounded incident rather than an estate-wide
#: one. A tenant that changes nothing gets today's behaviour exactly — recommendations only.
POLICY_DEFAULTS = {
    "enabled": False,
    "kill_switch": False,
    "dry_run": True,
    "source_connections": [],
    "rule_ids": [],
    "required_evidence": [METADATA_LINK],
    # Administrator-confirmed document-family mappings, the fourth approved evidence type. They
    # live ON the policy — rather than in a table of their own — because that is what makes them
    # part of the AUDIT RECORD the PRD requires them to already exist in: SNAPSHOT_FIELDS pins
    # them into the content-addressed snapshot, so every execution's stored snapshot_id resolves
    # to the exact mappings that authorised it, including the administrator who confirmed each
    # one. A mapping added or withdrawn later produces a new snapshot id rather than silently
    # rewriting the authorisation of a move that already happened.
    "confirmed_families": [],
    "min_replacement_age_days": 30,
    "archive_root": "",
    "preserve_hierarchy": True,
    "max_actions_per_run": 25,
    "max_actions_per_day": 100,
}

#: Fields that change what the decision MEANS, and therefore what a snapshot has to pin. A
#: snapshot exists so a decision made at scan time can be re-checked at execution time against
#: the policy that produced it — so it covers the evaluation inputs. `kill_switch` is
#: deliberately NOT here: it is read LIVE at every execution, because a snapshot that could
#: carry a stale "not killed" would let a run keep moving files after somebody pulled the switch.
SNAPSHOT_FIELDS = ("enabled", "dry_run", "source_connections", "rule_ids", "required_evidence",
                   "confirmed_families", "min_replacement_age_days", "archive_root",
                   "preserve_hierarchy", "max_actions_per_run", "max_actions_per_day")


def normalize_policy(raw: dict | None) -> dict:
    """A stored/submitted policy coerced to the exact shape the rest of this module reads.

    Unknown keys are dropped and every value is typed, so a hand-edited settings row cannot make
    a decision function branch on a string where it expected a bool. Anything unparseable falls
    back to the DEFAULT, never to the permissive value — `enabled` from garbage is False.
    """
    src = raw if isinstance(raw, dict) else {}
    out = dict(POLICY_DEFAULTS)
    for key in ("enabled", "kill_switch", "dry_run", "preserve_hierarchy"):
        if key in src:
            out[key] = bool(src.get(key))
    for key in ("source_connections", "rule_ids"):
        value = src.get(key)
        out[key] = sorted({str(v).strip() for v in value if str(v).strip()}) if isinstance(value, list) else []
    evidence = src.get("required_evidence")
    if isinstance(evidence, list):
        chosen = sorted({str(v).strip() for v in evidence if str(v).strip() in EVIDENCE_TYPES})
        out["required_evidence"] = chosen or list(POLICY_DEFAULTS["required_evidence"])
    out["confirmed_families"] = normalize_confirmed_families(src.get("confirmed_families"))
    out["archive_root"] = _clean_path(src.get("archive_root"))
    for key, floor in (("min_replacement_age_days", 0), ("max_actions_per_run", 0),
                       ("max_actions_per_day", 0)):
        try:
            out[key] = max(floor, int(src.get(key, POLICY_DEFAULTS[key])))
        except (TypeError, ValueError):
            out[key] = POLICY_DEFAULTS[key]
    return out


#: The fields a confirmed family mapping must carry. `confirmed_by` is required and is not
#: cosmetic: an administrator-confirmed mapping whose confirming administrator is unknown is
#: indistinguishable from one ACP inferred, which is the distinction this evidence type IS.
_MAPPING_FIELDS = ("family", "source_item_id", "replacement_item_id", "confirmed_by")


def normalize_confirmed_families(raw) -> list[dict]:
    """Admin-confirmed mappings coerced to shape, dropping any that are not usable.

    Dropped HERE rather than raising, because a policy row that cannot be parsed would take the
    whole feature down for a tenant — including its kill switch, which is the one control that
    must work when everything else is misconfigured.
    """
    out: list[dict] = []
    seen = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        row = {k: str(entry.get(k) or "").strip() for k in _MAPPING_FIELDS}
        if not all(row.values()) or row["source_item_id"] == row["replacement_item_id"]:
            continue
        row["confirmed_at"] = str(entry.get("confirmed_at") or "").strip()
        key = (row["source_item_id"], row["replacement_item_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return sorted(out, key=lambda r: (r["source_item_id"], r["replacement_item_id"]))


def policy_problem(policy: dict) -> str:
    """Why this policy cannot be ENABLED, or '' when it can.

    Only checked on enable, not on save: a half-configured policy that is switched off is a
    draft, and refusing to store one would mean an administrator could not put the destination
    in before the rules. Every condition here would otherwise become an execution-time failure
    on a real file, which is the wrong place to discover a missing archive root.
    """
    p = normalize_policy(policy)
    if not p["enabled"]:
        return ""
    if not p["archive_root"]:
        return "Set an archive destination — automatic archival has nowhere to move files to."
    if not p["source_connections"]:
        return "Choose at least one source connection this policy may act on."
    if not p["rule_ids"]:
        return "Choose at least one lifecycle rule whose candidates may be archived automatically."
    if not p["required_evidence"]:
        return "Require at least one type of supersession evidence."
    if p["max_actions_per_run"] < 1 or p["max_actions_per_day"] < 1:
        return "Set the per-run and per-day action ceilings to at least one."
    if p["max_actions_per_run"] > p["max_actions_per_day"]:
        return "The per-run ceiling cannot exceed the per-day ceiling."
    return ""


def policy_snapshot(policy: dict) -> dict:
    """`{"snapshot_id", "policy"}` — the evaluation-time policy plus a stable id for it.

    The id is a hash of the CONTENT, so two scans evaluated under an unchanged policy share one
    snapshot id and an administrator who changes a single ceiling gets a new one. That is what
    makes "was this executed under the policy it was evaluated under?" answerable by comparing
    two strings, and it is why the id is derived rather than assigned.
    """
    pinned = {k: normalize_policy(policy)[k] for k in SNAPSHOT_FIELDS}
    blob = json.dumps(pinned, sort_keys=True, separators=(",", ":"))
    return {"snapshot_id": hashlib.sha256(blob.encode()).hexdigest()[:16], "policy": pinned}


def idempotency_key(*, tenant: str, source_connection: str, source_item_id: str,
                    destination: str, snapshot_id: str) -> str:
    """The key that makes a repeated submission return the FIRST execution instead of a second move.

    Exactly the five inputs the PRD names. The destination and the snapshot are in it on purpose:
    the same file archived to a different root, or under a policy an administrator has since
    changed, is a different decision and deserves its own record rather than silently colliding
    with the old one.
    """
    blob = "\x1f".join([str(tenant or ""), str(source_connection or ""), str(source_item_id or ""),
                        str(destination or ""), str(snapshot_id or "")])
    return hashlib.sha256(blob.encode()).hexdigest()


# ── Destination ──────────────────────────────────────────────────────────────

def _clean_path(value) -> str:
    """A source-relative POSIX path with no traversal, no leading slash, no empty segments."""
    text = str(value or "").strip().replace("\\", "/")
    parts = [p for p in text.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        return ""
    return "/".join(parts)


def destination_path(archive_root: str, source_path: str, *, preserve_hierarchy: bool = True) -> str:
    """Where the file lands, as a path relative to the source root.

    Hierarchy preservation is the default and the interesting case: `Policies/2024/x.docx` under
    root `Archive` becomes `Archive/Policies/2024/x.docx`, so an archive of ten thousand files is
    still navigable and a restore is a path arithmetic problem rather than a search. Flattening
    is offered because some tenants archive into a records library that imposes its own
    structure, and it is the option that can collide — two `x.docx` from different folders now
    want one path — which is why collisions are a first-class refusal rather than an overwrite.
    """
    root = _clean_path(archive_root)
    rel = _clean_path(source_path)
    if not root or not rel:
        return ""
    return posixpath.join(root, rel if preserve_hierarchy else posixpath.basename(rel))


# ── Decision states ──────────────────────────────────────────────────────────

RECOMMEND_ONLY = "recommend_only"
ELIGIBLE_AUTO = "eligible_auto"
BLOCKED = "blocked"
ARCHIVED = "archived"
RECOVERY_REQUIRED = "recovery_required"

#: The label a person reads, per state. One string per state, defined once, because the failure
#: this whole feature guards against is a surface that says "Archived" about a file that was not.
STATE_LABELS = {
    RECOMMEND_ONLY: "Recommended for archive",
    ELIGIBLE_AUTO: "Eligible for automatic archive",
    BLOCKED: "Auto-archive blocked",
    ARCHIVED: "Automatically archived",
    RECOVERY_REQUIRED: "Recovery required",
}


def decide(candidate: dict, *, policy: dict, evidence: list[dict] | None, now: datetime,
           executed: dict | None = None, day_used: int = 0, run_used: int = 0) -> dict:
    """Which lane this candidate is in, and why — the diagram in the PRD, as one function.

    `candidate` is an inventory row (source, path, drive_file_id, lifecycle_rule_id, …).
    `executed` is this candidate's existing execution record, if any — it wins over every other
    consideration, because a file that has already been moved is not a candidate for anything.

    Returns `{"state", "reason", "evidence", "rejected_evidence", "destination"}`. `reason` is
    written to be shown to a person verbatim: every refusal here is something a reader has to be
    able to act on, and a state with no reason is indistinguishable from a bug.
    """
    p = normalize_policy(policy)
    if executed:
        state = executed.get("state")
        if state in (ARCHIVED, RECOVERY_REQUIRED, BLOCKED):
            return {"state": state, "reason": executed.get("detail") or STATE_LABELS.get(state, ""),
                    "evidence": executed.get("evidence") or [], "rejected_evidence": [],
                    "destination": executed.get("destination_path") or ""}

    def out(state, reason, keep=(), rejected=(), destination=""):
        return {"state": state, "reason": reason, "evidence": list(keep),
                "rejected_evidence": list(rejected), "destination": destination}

    keep, rejected = usable_evidence(evidence, p)

    # THE EVIDENCE GATE COMES FIRST, before the policy gate, and the order is load-bearing for
    # what a reader is told. Without evidence this is a recommendation no matter what the policy
    # says — reporting it as "blocked by policy" would suggest that turning auto-fire on would
    # move it, which is false and is the misunderstanding this feature most needs to avoid.
    if not keep:
        reason = ("No supersession evidence links this document to a newer replacement, so it "
                  "stays a recommendation. Age, filename similarity and inactivity never "
                  "authorize an automatic move.")
        if rejected:
            reason += " " + " ".join(rejected)
        return out(RECOMMEND_ONLY, reason, rejected=rejected)

    source_refusal = source_problem(candidate.get("source"))
    if source_refusal:
        return out(RECOMMEND_ONLY, source_refusal, keep, rejected)

    if not p["enabled"]:
        return out(RECOMMEND_ONLY,
                   "Supersession evidence exists, but automatic archival is switched off for this "
                   "tenant. A person can still approve the archive.", keep, rejected)
    if p["kill_switch"]:
        return out(BLOCKED, "The automatic-archive kill switch is on — no new moves are started.",
                   keep, rejected)

    connection = str(candidate.get("source_connection") or "").strip()
    if connection not in p["source_connections"]:
        return out(BLOCKED,
                   f"Source connection {connection or 'not recorded'} is not one this policy may "
                   f"act on.", keep, rejected)
    rule_id = str(candidate.get("lifecycle_rule_id") or "").strip()
    if rule_id not in p["rule_ids"]:
        return out(BLOCKED,
                   f"Lifecycle rule {rule_id or 'not recorded'} is not enabled for automatic "
                   f"archival.", keep, rejected)

    ages = [replacement_age_days(e, now) for e in keep]
    if all(age is None for age in ages):
        return out(BLOCKED,
                   "The replacement's last-modified time could not be read, so its minimum age "
                   "cannot be shown to have elapsed.", keep, rejected)
    oldest = max(age for age in ages if age is not None)
    if oldest < p["min_replacement_age_days"]:
        return out(BLOCKED,
                   f"The replacement is {oldest:.1f} days old; this policy requires "
                   f"{p['min_replacement_age_days']} days before the older version may be archived.",
                   keep, rejected)

    destination = destination_path(p["archive_root"], candidate.get("path") or "",
                                   preserve_hierarchy=p["preserve_hierarchy"])
    if not destination:
        return out(BLOCKED,
                   "A destination path could not be built from the archive root and this "
                   "document's source path.", keep, rejected)

    if run_used >= p["max_actions_per_run"]:
        return out(BLOCKED, f"This run has reached its ceiling of {p['max_actions_per_run']} "
                            f"automatic actions.", keep, rejected, destination)
    if day_used >= p["max_actions_per_day"]:
        return out(BLOCKED, f"Today has reached its ceiling of {p['max_actions_per_day']} "
                            f"automatic actions.", keep, rejected, destination)

    return out(ELIGIBLE_AUTO,
               "A newer item is proven to supersede this document and the tenant policy permits "
               "automatic archival. Safety checks run immediately before the move.",
               keep, rejected, destination)


# ── Preflight ────────────────────────────────────────────────────────────────

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"

#: Each check the PRD requires, in the order it is reported. Order matters only to the reader —
#: every check is evaluated, so a report never stops at the first failure and hides the rest.
PREFLIGHT_CHECKS = ("source_exists", "source_unchanged", "replacement_exists", "replacement_newer",
                    "replacement_audience", "no_hold", "destination_reachable",
                    "destination_free", "not_already_executed")


def preflight(*, snapshot: dict, live: dict, policy: dict, already_executed: bool = False) -> dict:
    """The last thing that runs before a file moves. Returns `{"ok", "route", "checks"}`.

    `snapshot` is what evaluation recorded (item id, eTag, replacement id and time); `live` is
    what the source system says RIGHT NOW. The comparison between them is the point: a document
    edited since it was evaluated may no longer be the superseded one, and moving it would act on
    a fact that has expired.

    `route` is "proceed", "review" or "cancel", and the three are not interchangeable. A FAIL
    that a person could resolve (a collision, a hold, a permission) routes to review. A snapshot
    mismatch CANCELS instead: there is nothing for a person to decide, because the evaluation
    itself is stale and has to be redone. UNKNOWN always routes to review — never to proceed —
    which is the rule that makes an unreadable retention state fail closed.
    """
    p = normalize_policy(policy)
    checks: list[dict] = []

    def add(name, result, detail):
        checks.append({"name": name, "result": result, "detail": detail})

    def tri(value):
        return UNKNOWN if value is None else (PASS if value else FAIL)

    add("source_exists", tri(live.get("source_exists")),
        "The document was found in the source system." if live.get("source_exists")
        else ("The document is no longer in the source system." if live.get("source_exists") is False
              else "The source system did not say whether the document still exists."))

    # THE MODIFICATION MARKER, and why it is `source_marker` rather than the eTag. What the
    # evaluation recorded is the item's last-modified time — discovery writes it to
    # scan_inventory.source_modified — and an eTag is not available at evaluation time at all, so
    # comparing eTags here would compare the live value with nothing. The eTag has its own,
    # narrower job: `if-match` on the PATCH, which closes the window between this check and the
    # move (archive_sources.move). Both are needed and they are not the same guard.
    snap_id = str(snapshot.get("source_item_id") or "")
    live_id = str(live.get("source_item_id") or "")
    snap_tag = str(snapshot.get("source_marker") or "")
    live_tag = str(live.get("source_marker") or "")
    if not snap_id or not snap_tag or not live_id or not live_tag:
        add("source_unchanged", UNKNOWN,
            "The document's identifier or change marker was not recorded on one side, so it "
            "cannot be shown to be unchanged since it was evaluated.")
    elif snap_id == live_id and snap_tag == live_tag:
        add("source_unchanged", PASS, "The document is unchanged since it was evaluated.")
    else:
        add("source_unchanged", FAIL,
            "The document has changed since it was evaluated, so that evaluation no longer "
            "describes it.")

    add("replacement_exists", tri(live.get("replacement_exists")),
        "The replacement was found in the source system." if live.get("replacement_exists")
        else ("The replacement no longer exists, so nothing supersedes this document."
              if live.get("replacement_exists") is False
              else "The source system did not say whether the replacement still exists."))

    newer = _strictly_after(live.get("replacement_modified"), snapshot.get("source_modified"))
    add("replacement_newer", tri(newer),
        {PASS: "The replacement is newer than the document being archived.",
         FAIL: "The replacement is not newer than the document being archived.",
         UNKNOWN: "One of the two modification times could not be read, so their order is unknown.",
         }[tri(newer)])

    add("replacement_audience", tri(live.get("replacement_audience_ok")),
        "The replacement is reachable by the same audience as the document." if live.get("replacement_audience_ok")
        else ("The replacement is not available to the document's audience, so archiving would "
              "remove their access to both." if live.get("replacement_audience_ok") is False
              else "It could not be established who can reach the replacement."))

    hold = live.get("hold") or {}
    if not hold.get("checked"):
        # THE FAIL-CLOSED CASE, stated as its own branch so it cannot be lost in a boolean. An
        # unread hold is the one uncertainty with an irreversible downside: moving a document
        # under legal hold is a compliance event, not a retryable error.
        add("no_hold", UNKNOWN,
            "Legal-hold, retention-lock and records state could not be read for this item, so it "
            "is not known whether a hold blocks the move.")
    elif hold.get("blockers"):
        add("no_hold", FAIL, "; ".join(str(b.get("message") or b.get("code"))
                                       for b in hold.get("blockers") or []))
    else:
        add("no_hold", PASS, "No legal hold, retention lock or records declaration blocks the move.")

    add("destination_reachable", tri(live.get("destination_reachable")),
        "The archive destination is reachable." if live.get("destination_reachable")
        else ("The archive destination could not be reached." if live.get("destination_reachable") is False
              else "It could not be established whether the archive destination is reachable."))

    collision = live.get("destination_collision")
    add("destination_free", UNKNOWN if collision is None else (FAIL if collision else PASS),
        "Nothing already exists at the destination path." if collision is False
        else (f"An item already exists at the destination path "
              f"({live.get('destination_collision_detail') or 'name in use'}); ACP never overwrites it."
              if collision else "It could not be established whether the destination path is free."))

    add("not_already_executed", FAIL if already_executed else PASS,
        "An execution record already exists for this document under this policy."
        if already_executed else "No execution has been recorded for this document under this policy.")

    if p["kill_switch"]:
        add("kill_switch", FAIL, "The kill switch is on — no new moves are started.")

    failed = [c for c in checks if c["result"] == FAIL]
    unknown = [c for c in checks if c["result"] == UNKNOWN]
    stale = any(c["name"] == "source_unchanged" and c["result"] == FAIL for c in checks)
    gone = any(c["name"] == "replacement_exists" and c["result"] == FAIL for c in checks)
    if stale or gone:
        route = "cancel"
    elif failed or unknown:
        route = "review"
    else:
        route = "proceed"
    return {"ok": route == "proceed", "route": route, "checks": checks,
            "failed": [c["name"] for c in failed], "unknown": [c["name"] for c in unknown]}


def _strictly_after(later, earlier) -> bool | None:
    a, b = _parse_iso(later), _parse_iso(earlier)
    if a is None or b is None:
        return None
    return a > b


# ── Outcome ──────────────────────────────────────────────────────────────────

def classify_outcome(verification: dict | None) -> tuple[str, str]:
    """A move's verified result → `(state, detail)`.

    `verification` is what the source system said AFTER the PATCH: whether the destination item
    exists, whether the source is gone from its old path, and the destination's id/url.

    The uncertain case is the one this exists for. A provider that times out mid-move, or answers
    a shape ACP does not recognise, has not told us whether the file moved — and both possible
    truths are consequential. Retrying could move it twice; reporting success could lose it. So
    it becomes RECOVERY_REQUIRED, which is a state a person resolves, and never `completed`.
    """
    v = verification or {}
    if v.get("verified") is True and v.get("destination_item_id"):
        return ARCHIVED, (f"Moved to {v.get('destination_path') or 'the archive destination'} and "
                          f"verified at the destination.")
    if v.get("verified") is False:
        return RECOVERY_REQUIRED, (
            v.get("detail") or "The move could not be verified at the destination afterwards.")
    return RECOVERY_REQUIRED, (
        v.get("detail") or "The source system's response to the move was ambiguous, so it is not "
                           "known whether the document moved. It is not retried automatically.")


#: How a provider failure is routed. `retry` is the ONLY one that may be re-attempted, and only
#: under the same idempotency key so a retry cannot become a second move.
FAILURE_ROUTES = {
    "permission": (BLOCKED, "review"),
    "collision": (BLOCKED, "review"),
    "source_changed": (BLOCKED, "cancel"),
    "missing_replacement": (BLOCKED, "cancel"),
    "rate_limited": (ELIGIBLE_AUTO, "retry"),
    "ambiguous": (RECOVERY_REQUIRED, "recover"),
}


def backoff_seconds(attempt: int, *, base: float = 2.0, cap: float = 60.0) -> float:
    """Bounded exponential backoff for the one retryable failure (rate limiting).

    Bounded in both directions on purpose: `cap` stops a long run stalling on one throttled item,
    and the caller stops retrying at a fixed attempt count rather than backing off forever. An
    unbounded retry against a throttling tenant is how a safe feature becomes an outage.
    """
    return min(cap, base * (2 ** max(0, int(attempt) - 1)))


def next_attempt_at(attempt: int, now: datetime) -> str:
    return (now + timedelta(seconds=backoff_seconds(attempt))).isoformat()


# ── Bounded live events ──────────────────────────────────────────────────────

#: The ONLY keys an archive lifecycle event may carry. An allow-list rather than a denylist,
#: because the risk is a field nobody thought to exclude: a token in a job payload, a document
#: excerpt in a detail string, a signed URL in a destination. A key not named here is dropped.
EVENT_KEYS = ("scan_id", "execution_id", "state", "rule_id", "snapshot_id", "source_path",
              "replacement_path", "destination_path", "phase", "detail", "eligible", "completed",
              "blocked", "remaining", "dry_run")

#: Substrings that mark a value as a credential even when it arrives under an allowed key. The
#: `detail` field is free text from a provider error, which is exactly where a signed URL with an
#: embedded SAS token has historically ended up.
_SECRET_MARKERS = ("bearer ", "authorization", "access_token", "refresh_token", "sig=", "sv=",
                   "?code=", "client_secret", "x-sp-token", "x-drive-token")


def event_payload(raw: dict) -> dict:
    """`raw` reduced to the bounded shape Live Operations may receive.

    Never document contents and never credentials — paths and counts only. A value that trips a
    secret marker is replaced rather than dropped, so the event still says a detail existed and
    was withheld instead of silently losing the failure it described.
    """
    out = {}
    for key in EVENT_KEYS:
        if key not in raw:
            continue
        value = raw.get(key)
        if isinstance(value, str):
            lowered = value.lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                out[key] = "[withheld: the provider's message contained a credential]"
                continue
            value = value[:400]
        elif not isinstance(value, (int, float, bool)) and value is not None:
            continue
        out[key] = value
    return out


def run_progress(counts: dict) -> str:
    """The one-line run summary, from measured counts only.

    No estimate and no percentage: a percentage of a queue whose eligibility is re-decided per
    item would be a number ACP cannot stand behind, and this surface's whole job is to be
    truthful about what has actually happened.
    """
    eligible = int(counts.get("eligible") or 0)
    completed = int(counts.get("completed") or 0)
    blocked = int(counts.get("blocked") or 0)
    remaining = max(0, eligible - completed - blocked)
    return (f"{eligible} eligible · {completed} completed · {blocked} blocked · "
            f"{remaining} remaining")
