"""Where a capacity schedule and its overrides live, and what gets written down when they change.

Phase 3 of docs/prd-capacity-scheduling.md. Two `app_settings` rows and the immutable
`decision_log` — no schema change, and both tables already survive restarts and are covered by
the existing RESET treatment.

THREE THINGS THIS MODULE IS RESPONSIBLE FOR.

**Optimistic concurrency.** PRD §8 requires it, and the reason is specific to this feature: two
administrators editing warm capacity in different tabs is not a merge conflict, it is one of them
silently undoing the other's floor and finding out during a deploy. A write carries the version
it read; a stale version is refused with both values so the caller can see what changed.

**An override that cannot silently become permanent.** §5.4 requires expiry, and the obvious
implementation — a background job that clears expired overrides — fails in the one direction that
matters: if the job stops, the override outlives its expiry with nothing reporting it. So expiry
is enforced ON READ instead. An override past its `expires_at` is not returned, by construction,
whether or not anything is running. There is nothing to fail.

**Audit before/after, with no secrets.** §11 wants actor, timestamp, reason, previous value,
requested value, outcome and a correlation id. The correlation id lets the reader tie a rejected
validation, the write it belonged to, and the Azure application that followed into one story —
which is the difference between an audit trail and a pile of rows.

WHAT IS DELIBERATELY NOT HERE: applying anything to Azure. Persistence and application are
separate steps with separate failure modes, and §9 turns on that separation — the durable record
is the intended configuration, Azure is the execution platform, and the two disagreeing is
"configuration drift" rather than a write that half-failed.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import capacity_schedule as sched
from swallowed import swallowed

SCHEDULE_KEY = "capacity_schedule"
OVERRIDE_KEY = "capacity_schedule_override"
APPLICATION_KEY = "capacity_schedule_application"
RECONCILIATION_KEY = "capacity_schedule_reconciliation"

# §5.4's list, in minutes. `until_next_transition` is resolved against the schedule at the moment
# the override is created, so an override never outlives the window it was meant to cover.
OVERRIDE_DURATIONS = {"30m": 30, "1h": 60, "2h": 120, "4h": 240}
MAX_OVERRIDE_MINUTES = 240


class ConcurrentEdit(RuntimeError):
    """A write built on a version that is no longer current."""

    def __init__(self, expected: int, actual: int):
        super().__init__(f"schedule has moved on: you read version {expected}, current is {actual}")
        self.expected, self.actual = expected, actual


class OverrideError(ValueError):
    """An override that cannot be created as asked."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialise(schedule: sched.Schedule) -> str:
    body = asdict(schedule)
    body["days"] = list(schedule.days)
    return json.dumps(body, sort_keys=True)


# Fields the dataclass declares as tuples. JSON has no tuple, so `asdict` writes them as lists
# and a naive load hands back a list — which compares unequal to an identical schedule, and makes
# a frozen dataclass unhashable. `days` was coerced from the start; `holidays` was added later
# and was NOT, which is exactly how this class of bug arrives. tests/test_capacity_store.py
# derives the list from the annotations so a third tuple field cannot repeat it.
_TUPLE_FIELDS = tuple(name for name, f in sched.Schedule.__dataclass_fields__.items()
                      if "tuple" in str(f.type))


def _deserialise(raw: str) -> sched.Schedule:
    body = json.loads(raw)
    for name in _TUPLE_FIELDS:
        if name in body:
            body[name] = tuple(body.get(name) or ())
    known = {f for f in sched.Schedule.__dataclass_fields__}
    # A stored row written by an older version may carry a field this one does not have. Dropping
    # the unknown ones beats refusing to load: the schedule is what production is running, and
    # refusing to read it would take the tab down over a field nobody uses any more.
    return sched.Schedule(**{k: v for k, v in body.items() if k in known})


def load_schedule(store) -> sched.Schedule:
    """The stored schedule, or the PRD's proposal when nothing has ever been saved.

    A READ FAILURE FALLS BACK TO THE PROPOSAL AND SAYS SO BY LEAVING `applied` FALSE, per §12
    ("if the schedule service is unavailable, retain the last successfully applied policy") — the
    honest degradation is a schedule that reads as not-in-force, never a fabricated live one.
    """
    try:
        raw = store.get_setting(SCHEDULE_KEY)
    except Exception:  # noqa: BLE001 — the tab must render something truthful either way
        # Reported, not merely absorbed. This degradation is CORRECT (§12) and also invisible:
        # the tab renders a schedule that reads as not-in-force, which is exactly what it shows
        # on a deployment that has never saved one. Without a line here, "nobody has configured a
        # schedule" and "the database is unreachable" look identical from the outside.
        swallowed("capacity_store.load_schedule: reading the stored schedule failed")
        return sched.PROPOSED
    if not raw:
        return sched.PROPOSED
    try:
        return _deserialise(raw)
    except (ValueError, TypeError):
        return sched.PROPOSED


def save_schedule(store, proposed: sched.Schedule, *, actor: str, expected_version: int,
                  reason: str, correlation_id: str | None = None) -> sched.Schedule:
    """Persist a schedule, bumping its version. Refuses a stale write; audits either way.

    Saving records intent, not Azure state. Application evidence lives separately under
    APPLICATION_KEY, so a newly edited schedule cannot inherit an earlier version's success.
    """
    correlation_id = correlation_id or uuid.uuid4().hex[:12]
    current = load_schedule(store)
    if expected_version != current.version:
        _audit(store, actor, "settings.capacity_schedule.rejected", reason=reason,
               correlation_id=correlation_id,
               detail=f"stale version {expected_version}, current {current.version}")
        raise ConcurrentEdit(expected_version, current.version)

    saved = replace(proposed, version=current.version + 1, applied=False)
    store.set_setting(SCHEDULE_KEY, _serialise(saved))
    _audit(store, actor, "settings.capacity_schedule.saved", reason=reason,
           correlation_id=correlation_id,
           detail=_diff_detail(current, saved))
    return saved


def load_application(store) -> dict:
    """Return durable application evidence, never a fabricated success."""
    empty = {"state": "never_applied", "desired_version": None, "applied_version": None,
             "apps": []}
    try:
        raw = store.get_setting(APPLICATION_KEY)
        body = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        swallowed("capacity_store.load_application: reading application state failed")
        return empty
    return body if isinstance(body, dict) else empty


def start_application(store, *, version: int, actor: str, reason: str,
                      correlation_id: str) -> dict:
    """Persist the attempt before an injected gateway is allowed to make its first write."""
    previous = load_application(store)
    body = {"state": "applying", "desired_version": int(version),
            # A new attempt does not erase evidence of the last successful application. If this
            # attempt fails, operators still need to know which version Azure was last verified
            # against; success below replaces it with this desired version.
            "applied_version": previous.get("applied_version"),
            "attempted_at": _now().isoformat(), "actor": actor, "reason": reason,
            "correlation_id": correlation_id, "apps": []}
    store.set_setting(APPLICATION_KEY, json.dumps(body, sort_keys=True))
    _audit(store, actor, "settings.capacity_schedule.apply_started", reason=reason,
           correlation_id=correlation_id, detail=f"applying schedule v{version}")
    return body


def finish_application(store, attempt: dict, result: dict) -> dict:
    """Persist the gateway's secret-free per-app result and audit its terminal state."""
    successful = result.get("state") == "applied"
    body = {**attempt, "state": result.get("state", "failed"),
            "applied_version": (attempt["desired_version"] if successful
                                else attempt.get("applied_version")),
            "completed_at": _now().isoformat(), "apps": list(result.get("apps") or [])}
    store.set_setting(APPLICATION_KEY, json.dumps(body, sort_keys=True))
    _audit(store, attempt["actor"],
           "settings.capacity_schedule.applied" if successful
           else "settings.capacity_schedule.apply_failed",
           reason=attempt["reason"], correlation_id=attempt["correlation_id"],
           detail=f"schedule v{attempt['desired_version']} result={body['state']}; "
                  + ", ".join(f"{r.get('app')}={r.get('status')}" for r in body["apps"]))
    return body


def load_reconciliation(store) -> dict:
    """Durable evidence for automatic override application/restoration."""
    empty = {"state": "idle", "desired_key": None, "applied_key": None,
             "failures": 0, "next_attempt_at": None, "apps": []}
    try:
        raw = store.get_setting(RECONCILIATION_KEY)
        body = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        swallowed("capacity_store.load_reconciliation: reading reconciliation state failed")
        return empty
    return {**empty, **body} if isinstance(body, dict) else empty


def save_reconciliation(store, body: dict, *, action: str, reason: str,
                        correlation_id: str) -> dict:
    """Persist one secret-free reconcile outcome and append its audit record."""
    safe = {
        "state": body.get("state", "failed"),
        "desired_key": body.get("desired_key"),
        "applied_key": body.get("applied_key"),
        "schedule_version": body.get("schedule_version"),
        "authority": body.get("authority"),
        "attempted_at": body.get("attempted_at"),
        "completed_at": body.get("completed_at"),
        "next_attempt_at": body.get("next_attempt_at"),
        "failures": int(body.get("failures") or 0),
        "apps": list(body.get("apps") or []),
    }
    store.set_setting(RECONCILIATION_KEY, json.dumps(safe, sort_keys=True))
    _audit(store, "capacity-reconciler", action, reason=reason,
           correlation_id=correlation_id,
           detail=(f"desired={safe['desired_key']} state={safe['state']}; "
                   + ", ".join(f"{r.get('app')}={r.get('status')}" for r in safe["apps"])))
    return safe


def _diff_detail(before: sched.Schedule, after: sched.Schedule) -> str:
    """Previous and requested values, per §11 — and ONLY the fields that moved.

    A full before/after of every field on every edit is a log nobody reads, which is the same
    outcome as no log. The version pair is always included so a row can be placed in sequence
    even when the change itself was a single number.
    """
    changed = []
    for field in ("enabled", "timezone", "days", "start", "end",
                  "business_hours", "off_hours", "maximums"):
        old, new = getattr(before, field), getattr(after, field)
        if old != new:
            changed.append(f"{field}: {old!r} -> {new!r}")
    return (f"v{before.version} -> v{after.version}; "
            + ("; ".join(changed) if changed else "no field changed"))


# ── overrides ────────────────────────────────────────────────────────────────────────────────

def get_override(store, now: datetime | None = None) -> dict | None:
    """The active override, or None. EXPIRY IS ENFORCED HERE, not by a background job.

    §5.4: "An override must never silently become permanent." A sweeper that clears expired rows
    fails in exactly the direction that breaks that promise — stop the sweeper and the override
    lives on, with nothing reporting it. Enforcing expiry on the read path means an expired
    override is invisible to every caller whether or not anything is running: there is no
    component whose failure extends it.
    """
    now = now or _now()
    try:
        raw = store.get_setting(OVERRIDE_KEY)
    except Exception:  # noqa: BLE001
        # Same reasoning as load_schedule: "there is no override" and "we could not look" are the
        # same answer to a caller and very different answers to an operator.
        swallowed("capacity_store.get_override: reading the stored override failed")
        return None
    if not raw:
        return None
    try:
        body = json.loads(raw)
        expires = datetime.fromisoformat(body["expires_at"])
    except (ValueError, TypeError, KeyError):
        return None
    if expires <= now:
        return None
    return body


def set_override(store, *, mode: str, floors: dict | None, duration: str, reason: str,
                 actor: str, schedule: sched.Schedule, now: datetime | None = None,
                 correlation_id: str | None = None) -> dict:
    """Create a temporary override. Every field §5.4 requires is mandatory here.

    `duration` is one of OVERRIDE_DURATIONS or "until_next_transition", which is resolved against
    the schedule NOW — so the override cannot outlive the window it was meant to cover, and a
    schedule with no next transition cannot produce an endless one.
    """
    now = now or _now()
    correlation_id = correlation_id or uuid.uuid4().hex[:12]
    if mode not in ("business_hours", "off_hours", "custom"):
        raise OverrideError(f"unknown override mode {mode!r}")
    if not (reason or "").strip():
        # §5.4 lists a plain-language reason as required. An override with no reason is the one
        # an operator finds a week later and cannot decide whether to cancel.
        raise OverrideError("an override requires a plain-language reason")
    if mode == "custom" and not floors:
        raise OverrideError("a custom override must name the capacity it wants")

    if duration == "until_next_transition":
        upcoming = sched.next_transition(schedule, now) if schedule.enabled else None
        if not upcoming:
            raise OverrideError(
                "this schedule has no next transition, so 'until the next scheduled transition' "
                "has no end. Choose a fixed duration.")
        expires = upcoming[0]
    elif duration in OVERRIDE_DURATIONS:
        expires = now + timedelta(minutes=OVERRIDE_DURATIONS[duration])
    else:
        raise OverrideError(f"unknown duration {duration!r}")

    body = {
        "mode": mode,
        "floors": dict(floors) if floors else schedule.floors(mode) if mode != "custom" else {},
        "reason": reason.strip(),
        "actor": actor,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        # Which schedule resumes afterwards, so the UI can say it without re-deriving it — §5.4
        # requires the answer to be visible, and deriving it at render time is how it becomes
        # wrong after an edit.
        "resumes_schedule_version": schedule.version,
        "correlation_id": correlation_id,
    }
    store.set_setting(OVERRIDE_KEY, json.dumps(body, sort_keys=True))
    _audit(store, actor, "settings.capacity_override.created", reason=reason,
           correlation_id=correlation_id,
           detail=f"mode={mode} until {body['expires_at']} floors={body['floors']}")
    return body


def clear_override(store, *, actor: str, reason: str = "cancelled",
                   correlation_id: str | None = None) -> None:
    store.set_setting(OVERRIDE_KEY, "")
    _audit(store, actor, "settings.capacity_override.cancelled", reason=reason,
           correlation_id=correlation_id or uuid.uuid4().hex[:12], detail="override cleared")


def effective_floors(schedule: sched.Schedule, override: dict | None, now: datetime) -> tuple[dict, str]:
    """The warm floors actually in force, and which authority set them.

    An override wins over the schedule while it lasts — that is what it is for — and the mode
    string it returns is `manual_override` rather than the mode it copied, so nothing downstream
    can report an overridden fleet as though the schedule had produced it.
    """
    if override:
        return dict(override.get("floors") or {}), "manual_override"
    mode = sched.effective_mode(schedule, now)
    return schedule.floors(mode), mode


def _audit(store, actor: str, action: str, *, reason: str, correlation_id: str,
           detail: str) -> None:
    """One immutable decision-log row.

    NO SECRETS AND NO CONNECTION STRINGS, per §11 — which is why this writes a rendered `detail`
    string built from replica counts and field names rather than dumping whatever object it was
    handed. The scale-rule metadata carries a `connection=database-url` reference, and a
    convenience that logged the policy wholesale is how that becomes a credential in a log.
    """
    try:
        store.log_decision(actor or "unknown", action,
                           detail=f"[{correlation_id}] {detail} · reason: {reason}"[:2000])
    except Exception:  # noqa: BLE001 — an audit failure must not lose the write it describes;
        # the caller has already persisted, and losing the row is better than losing the change.
        #
        # REPORTED, NOT DISCARDED. A `pass` here would be the worst possible place for one: the
        # whole point of §11 is that a capacity change leaves a trace, so an audit path that
        # fails silently defeats the requirement it implements while every write still appears to
        # succeed. `swallowed` logs it with a traceback and escalates a persistent failure at
        # powers of two, which is what turns "the log is empty" into a question somebody asks.
        swallowed(f"capacity_store._audit: writing the {action} audit row failed")
