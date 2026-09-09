"""The ten scenarios, as data plus a function each.

REGISTRY-DRIVEN, AND THAT IS A DESIGN CONSTRAINT RATHER THAN A STYLE. Adding a scenario is a
`@scenario(...)` decorator and a function; there is no dispatch chain, no `if sid == ...` ladder
and no second list to keep in step. The runner iterates `REGISTRY`, the report's `suite` block is
derived from it, and the mandatory lists are derived from each scenario's `claim` field — so a
scenario that is mandatory for `supported` cannot be mandatory in the code and optional in the
report, which is the drift that makes a certification claim wrong rather than merely stale.

WHICH CLAIM EACH SCENARIO GATES (PRD §C):

    mvp        1-6   API readiness, worker registration, queue and progress, the fixture
                     workflow end to end, audit and diagnostics, and worker restart mid-job.
                     These are the Kubernetes MVP claim: an installation that cannot do these
                     cannot process a document at all.
    supported  7-10  dependency degradation, scale up and down with active jobs, upgrade from
                     the previous supported release, and backup followed by an ACTUAL restore.
                     These are the operational claims — the ones that distinguish "it ran once"
                     from "somebody can run it".

THE DISTINCTION IS DATA. `Scenario.claim` is read by `mandatory_for("mvp")` and by the report
builder; nothing anywhere restates which is which in prose that could disagree.

SYNTHETIC FIXTURES ONLY. Every document the suite processes comes from `FIXTURES` below —
files this repository ships for demos. A certification run must never need a customer document or
a real credential: the suite runs on somebody else's cluster, and its evidence is written into a
report that gets attached to tickets.

WHAT THE PROBE PATHS ARE. The constants below are the API surfaces the suite depends on. Where a
build does not serve one, the scenario reports `unknown` naming the path — never `pass`, and never
`fail`, because a missing surface says nothing about whether the target's workers register or its
artifacts persist. That is also the honest answer today: this suite has been exercised against the
fake target, and against no real deployment.
"""
from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .backend import BackendError, HttpResponse
from .context import ScenarioContext
from .report import UNKNOWN, Outcome

# ── the surfaces the suite probes ─────────────────────────────────────────────
#
# Marked with whether the application serves them today, because a probe against a path that was
# never implemented produces `unknown` on a perfectly healthy cluster, and the reader deserves to
# know which kind of gap they are looking at.
PATH_HEALTH = "/healthz"                              # exists — api/routes/system.py:490
PATH_READY = "/readyz"                                # exists — api/routes/system.py:561
# WORKER REGISTRATION IS READ FROM `/readyz`, AND `/control/workers/capacity` IS DELIBERATELY NOT
# USED. That route exists (api/routes/control.py:540) and this suite probed it until it was run
# against something that is not Azure: it reads Azure Container Apps replica counts and Azure
# Monitor metrics, and with no Azure configured it returns `_empty_capacity(False)` — a block with
# no `roles` key at all. Every scenario asking it about worker tiers would report "no worker tier
# registered" on a perfectly healthy Kubernetes cluster.
#
# PRD §2.9 keeps provider differences in infrastructure adapters, and a PORTABLE acceptance suite
# that certifies six platforms cannot take its central reading through an Azure-only surface.
# `/readyz` carries `workers.roles.<role>` = {heartbeat_at, age_s, alive, pool_size, version}
# (store.worker_roles_status) on every platform, which is the same fact without the adapter.
PATH_READY_ROLES = "/readyz"                          # exists — api/routes/system.py:561
PATH_SCANS = "/scans"                                 # exists — api/routes/scans.py:200

# STARTING A SCAN IS A QUERY-STRING CALL, NOT A JSON BODY, and getting that wrong is how this
# suite spent its first life passing against a fake and failing against the application. The real
# signature is `start_scan(source: str = Query(..., pattern="^(local|drive|sharepoint)$"), ...)`:
# a POST with a JSON body and no query string answers 422 before any handler runs, so every
# scenario that starts a scan would have reported a target failure caused entirely by the suite.
#
# `source=local` reads the image's own corpus directory, and deploy/public/Dockerfile:86 copies
# `demo-fixtures/` into it — so FIXTURES below are present in any image built from this
# repository, with no upload step and no per-target seeding.
#
# `queue=true` is the point rather than a convenience: it hands the work to the worker tier, which
# is the path these scenarios exist to certify. With `queue=false` discovery runs inside the API
# process and a green report would say nothing about whether any worker ever claimed a job.
# `replace_active=true` IS NOT A CONVENIENCE, IT IS HOW THE SUITE GETS PAST ITS OWN FENCE. The
# application allows ONE active workflow per owner and answers 409 otherwise
# (`discovery_workflow_active`), and this suite authenticates as one identity throughout — so
# `worker-restart` alone starts three scans in sequence, each behind the previous one's run. The
# route's own documentation says what this parameter means: "Re-scan means start fresh,
# superseding whatever's running", and it supersedes rather than cancels, which is the difference
# between the replaced run sorting as an ordinary superseded row and it stamping completed_at and
# reading as the estate's newest, emptiest scan.
#
# `_start_scan` still treats a 409 as `unknown` rather than a failure. That is not redundancy: a
# 409 would mean this suite is racing something else on the target, which says nothing about the
# target and must not read as one of its defects.
PATH_SCAN_START = "/scans?source=local&queue=true&ai=false&pii=false&replace_active=true"

# PROGRESS IS `/live`, NOT `/status`. `/scans/{sid}/status` exists and is a different thing: ADR
# 0026's Accessibility Status roll-up, which answers `{"available": ..., ...}` and never carries
# `files_done`. Polling it for progress reads as a scan that is permanently at zero.
#
# `/live` is `live_snapshot.build_snapshot` — the authoritative object the application's own
# running screen polls, so the suite asks the same question the product asks.
PATH_SCAN_LIVE = "/scans/{sid}/live"                  # exists — api/routes/scans.py:1230
PATH_SCAN_EVENTS = "/scans/{sid}/events"              # exists (SSE) — api/routes/scans.py:1253
PATH_SCAN_ASSESS = "/scans/{sid}/assess"              # exists — api/routes/scans.py:1359
PATH_SCAN_REMEDIATE = "/scans/{sid}/remediate"        # exists — api/routes/scans.py:647
# Assessment uses scan-level progress from #1827; remediation waits for its exact
# returned job set now that durable jobs are supported by the status endpoint.
PATH_JOB = "/scans/jobs/{jid}"
PATH_ARTIFACTS = "/scans/{sid}/artifacts"             # SUITE REQUIREMENT — the durable-artifact
                                                      # inventory PRD §12 needs; a build without
                                                      # it cannot demonstrate §20.5 at all
PATH_AUDIT = "/admin/audit-events"                    # SUITE REQUIREMENT — PRD §13's audit trail
PATH_SUPPORT_BUNDLE = "/admin/support-bundle"         # SUITE REQUIREMENT — PRD §13's redacted export

# Synthetic documents, one per format the analysers cover. These are the repository's demo files;
# `tests/test_packaging_acceptance.py` asserts they exist, so the list cannot rot into a set of
# paths that only the fake target knows about.
#
# NOT test-corpus/bulk-200: throughput belongs to the performance suite, and a certification run
# that takes an hour is a certification run nobody repeats. Four documents exercise all four
# analysers, which is what these scenarios are for.
FIXTURES: tuple[str, ...] = (
    "demo-fixtures/word-accessibility-demo.docx",
    "demo-fixtures/powerpoint-accessibility-demo.pptx",
    "demo-fixtures/excel-accessibility-demo.xlsx",
    "demo-fixtures/pdf-accessibility-demo.pdf",
)

WORKER_ROLES = ("discovery", "assess", "remediate")

# Worker deployments, by role. The chart's names; a target that renamed them fails the restart and
# scale scenarios with "no workload named ...", which is a true statement about a target the suite
# cannot drive rather than a claim about the application.
WORKLOAD = {"discovery": "acp-worker-discover", "assess": "acp-worker-assess",
            "remediate": "acp-worker-remediate"}

# In-cluster dependencies the degradation scenario can take away. A target using MANAGED Postgres,
# Redis or object storage has no such workload — that dependency then reports `unknown` (we could
# not take it away), never `pass`.
DEPENDENCY_WORKLOAD = {"redis": "acp-redis", "postgres": "acp-postgres",
                       "object-storage": "acp-objectstore", "ai-provider": "acp-ollama"}
DEPENDENCY_CHECK = {"redis": "redis", "postgres": "database",
                    "object-storage": "object_storage", "ai-provider": "ai_provider"}

# A heartbeat older than this means the tier has pods and has not registered — the exact failure
# scenario 2 exists for, and one that reads as healthy in `kubectl get deploy`.
HEARTBEAT_MAX_SECONDS = 90

POLL_SECONDS = 5.0
MAX_POLLS = 24                    # two minutes at the poll interval above

# ASSESSMENT GETS ITS OWN BUDGET, because it is a different kind of work from the one MAX_POLLS
# was sized for. Discovery lists metadata; assessment DOWNLOADS each document and runs the WCAG
# analysers over it — LibreOffice for Office formats, the PDF engine for PDFs — which is minutes
# of CPU per corpus rather than seconds of I/O.
#
# NOT A NUMBER CHOSEN TO MAKE A SCENARIO PASS. Run 34246784436 reported "assessment did not
# complete within 120s" on the reference cluster, which is a one-node runner already measured at
# 1000m of CPU BELOW ACP's own minimum (`capacity.floor`: needs 5000m, has 4000m) and which had
# earlier refused the assess request outright with DB_CAPACITY_BUSY. Two minutes was the discovery
# budget applied to a job that is not discovery.
#
# Still bounded, and a timeout is still a FAIL: a target that accepts work and never finishes it
# is a finding, and the message below carries the progress counts so the next run says whether it
# stalled at zero or was one document short.
ASSESS_MAX_POLLS = 120            # ten minutes at the poll interval above

# The run states, taken from what `api/store.py` actually WRITES to `scan_runs.status`. The first
# real run against a cluster is why this list is not `live_snapshot._ACTIVE_STATES`: copying that
# set produced `unknown` on a run that was working perfectly, twice.
#
# `discovered` IS A TERMINAL SUCCESS, and it is the one that matters here. A Discover-only scan
# stops at `discovered` with `completed_at` staying NULL until somebody runs Assess
# (store.py:308, 3343) — so a suite waiting for `completed` waits forever on a scan that finished.
# The first reference-cluster run reported exactly that, as "the run reports state 'discovered',
# which this suite does not model", and worker-restart turned it into a lost-work FAILURE about a
# cluster that had lost nothing.
#
# DO NOT DERIVE THIS FROM THE SNAPSHOT'S `active` FIELD. `live_snapshot._ACTIVE_STATES` covers
# neither `queued` nor `discovered`, so both report `active: false` while being, respectively, not
# started and finished — opposite conditions that the one boolean cannot tell apart.
RUN_IN_PROGRESS_STATES = frozenset({"queued", "preparing", "running", "degraded", "pausing",
                                    "paused", "finalizing"})
RUN_SUCCEEDED_STATES = frozenset({"discovered", "done", "completed"})
RUN_FAILED_STATES = frozenset({"failed", "error", "cancelled", "canceled", "interrupted",
                               "superseded"})

# Storage schemes that are DURABLE. PRD §12: no authoritative output may exist only on ephemeral
# disk, and §20.5 makes that an acceptance criterion. A remediated file whose only location is
# file:///tmp is lost the moment the pod is rescheduled, and nothing reports it.
DURABLE_SCHEMES = ("s3", "azblob", "gs", "https", "minio")


@dataclass(frozen=True)
class Scenario:
    """One acceptance question: what it is called, which claim it gates, what the target must
    allow before it can run at all, and the function that runs it."""

    id: str
    title: str
    claim: str                       # "mvp" | "supported"
    requires: frozenset[str]
    proves: str                      # one line, quoted in the README and in --list
    run: Callable[[ScenarioContext], Outcome]


REGISTRY: dict[str, Scenario] = {}


def scenario(*, id: str, title: str, claim: str, requires: Iterable[str], proves: str):
    """Register a scenario. Order of definition is the order of execution.

    ORDER MATTERS AND IS DELIBERATE: readiness before registration before the workflow, and the
    destructive scenarios last. A suite that restarts workers before it has established that the
    target could process a document at all reports a restart failure for a target that was never
    working — which sends the reader to the wrong problem.
    """
    if claim not in ("mvp", "supported"):
        raise ValueError(f"claim must be 'mvp' or 'supported', got {claim!r}")

    def register(fn: Callable[[ScenarioContext], Outcome]) -> Callable:
        if id in REGISTRY:
            raise ValueError(f"duplicate scenario id {id!r}")
        REGISTRY[id] = Scenario(id=id, title=title, claim=claim,
                                requires=frozenset(requires), proves=proves, run=fn)
        return fn

    return register


def mandatory_for(claim: str) -> tuple[str, ...]:
    """The scenario ids a claim requires. Derived, so the code and the report cannot disagree."""
    return tuple(s.id for s in REGISTRY.values() if s.claim == claim)


# ── shared probing helpers ────────────────────────────────────────────────────

def _json(resp: HttpResponse) -> Any | None:
    return resp.json()


def _detail(resp: HttpResponse) -> str:
    """A bounded, printable slice of a response body, for evidence.

    THE SECOND REFERENCE-CLUSTER RUN COST A WHOLE CYCLE FOR WANT OF THIS. `fixture-workflow`
    reported "starting assessment answered 503" and nothing else, so the run established that
    something returned 503 and gave no way to tell `DB_CAPACITY_BUSY` from a dozen other 503s in
    this application. A status code alone is not a diagnosis, and the next run is fifteen minutes
    away.
    """
    body = resp.json()
    if isinstance(body, dict):
        named = {k: body[k] for k in ("code", "detail", "message", "changes") if k in body}
        if named:
            return json.dumps(named)[:400]
    return (resp.body or "")[:400]


def _unavailable(resp: HttpResponse, path: str) -> Outcome | None:
    """The answers that mean "nothing was established", as an Outcome or None.

    A transport error and a 404 are both `unknown`, and neither is a fail: the first says the
    suite could not reach the target, the second says this build does not serve the surface. Both
    leave the underlying question — do workers register, do artifacts persist — completely open.

    SO IS A 503, AND THAT ONE IS NOT OBVIOUS. `app.py`'s capacity guard answers 503 with
    `Retry-After`, `code: DB_CAPACITY_BUSY` and `changes: "unknown"` — it is the application
    stating that it could not even determine whether the request took effect. Reporting that as a
    target FAILURE says "this installation cannot assess documents" about one that was busy, which
    is the same false-accusation shape as the restart scenario's lost-work finding. The caller
    retries first (see `_post_with_retry`); this maps a 503 that SURVIVES the retries, and it maps
    it to `unknown` because a target that stayed at capacity established nothing either way.

    Every other non-2xx stays a failure. A 500, a 409 or a 422 is the target answering
    definitively, and a suite that treated those as inconclusive could not fail at all.
    """
    if resp.error:
        return Outcome.unknown(f"could not reach {path}: {resp.error}", path=path)
    if resp.status == 404:
        return Outcome.unknown(
            f"this build does not serve {path}, so the question could not be answered here",
            path=path, status=404)
    if resp.status == 503:
        return Outcome.unknown(
            f"{path} answered 503 after retries — the target was unable to accept the request and "
            f"says so: {_detail(resp)}. Nothing about its behaviour was established.",
            path=path, status=503, body=_detail(resp))
    return None


# How long to keep asking a target that says it is busy. `app.py`'s capacity guard sets
# `Retry-After: 5`, so this is twelve of the server's own suggested intervals — and it is a
# CLIENT-CORRECTNESS number, not a number chosen to make a scenario pass. Giving up after three
# retries on a server explicitly asking to be asked again under-implements its stated contract,
# and the third reference-cluster run showed the difference matters: `POST /assess` was refused
# while the discovery that preceded it was still settling.
#
# Bounded, because "retry until it works" is how a suite reports a permanently saturated target
# as healthy. A 503 that survives the whole budget is `unknown`, and stays `unknown`.
RETRY_BUSY_SECONDS = 60.0


def _post_with_retry(ctx: ScenarioContext, path: str,
                     attempts: int = int(RETRY_BUSY_SECONDS / POLL_SECONDS)
                     ) -> HttpResponse:
    """POST, retrying only a 503 and only as many times as the application asks.

    RETRY IS SCOPED TO 503 DELIBERATELY. `app.py` answers it with `Retry-After` and
    `changes: "none"` for safe methods — an explicit "temporarily at capacity, ask again". Nothing
    else is retried: retrying a 500 turns one defect into four identical ones in the log, and
    retrying a 409 fights the application's own single-flight fence.
    """
    resp = ctx.post(path)
    for _ in range(max(0, attempts - 1)):
        if resp.status != 503:
            return resp
        ctx.backend.sleep(POLL_SECONDS)
        resp = ctx.post(path)
    return resp


def _start_scan(ctx: ScenarioContext, fixtures: Iterable[str] = FIXTURES
                ) -> tuple[str | None, Outcome | None]:
    """Start a queued local scan of the image's own fixture corpus. Returns (scan_id, failure).

    THE FIXTURE READ IS A PRECONDITION CHECK, NOT AN UPLOAD. There is no endpoint that accepts
    document bytes from this suite, and inventing one would mean certifying a path no user takes.
    `source=local` scans what the image already carries, and deploy/public/Dockerfile:86 copies
    `demo-fixtures/` in — so reading them here asserts that the repository this image was built
    from still contains the documents the assertions below count. A run whose corpus silently
    shrank would otherwise report "4 of 4 processed" while processing two.
    """
    names = []
    for path in fixtures:
        try:
            ctx.backend.read_fixture(path)
        except BackendError as exc:
            return None, Outcome.unknown(f"fixture {path} could not be read: {exc}")
        names.append(path.rsplit("/", 1)[-1])

    resp = ctx.post(PATH_SCAN_START)
    bad = _unavailable(resp, PATH_SCAN_START)
    if bad is not None:
        return None, bad
    body = _json(resp) or {}
    if resp.status == 409:
        # One active workflow per owner (api/routes/scans.py's discovery_workflow_active fence).
        # A previous scenario's run is still going, which is a fact about how this suite sequences
        # its own work and not a finding about the target.
        return None, Outcome.unknown(
            f"{PATH_SCANS} answered 409: a scan for this owner is still active, so this scenario "
            f"could not start its own", status=409, detail=str(body.get("detail"))[:200])
    if not resp.ok or not body.get("scan_id"):
        return None, Outcome.failed(
            f"starting a local scan of {len(names)} fixtures answered {resp.status} without a "
            f"scan id", status=resp.status)
    return str(body["scan_id"]), None


def _counts(snap: dict | None) -> dict[str, int]:
    """The three denominators `/live` reports, as ints.

    THREE, NOT ONE, and the snapshot's own comment says why: "discovered >= eligible >= completed
    — three honest denominators, never blended into one %". A scenario that compares `completed`
    against `discovered` reports a failure on every run with an ineligible file in the corpus.
    """
    totals = (snap or {}).get("totals") or {}
    kpis = (snap or {}).get("kpis") or {}
    return {"discovered": int(totals.get("discovered") or 0),
            "eligible": int(totals.get("eligible") or 0),
            "completed": int(kpis.get("completed") or 0)}


def _await_scan(ctx: ScenarioContext, sid: str, *, max_polls: int = MAX_POLLS
                ) -> tuple[dict | None, Outcome | None]:
    """Poll `/live` to a terminal run state. Returns (final snapshot, failure).

    A scan that never terminates is a FAIL, not an unknown: the suite reached the target, asked
    repeatedly, and the target did not finish work it accepted. That is a statement about the
    target — which is exactly what a timeout here usually means (a worker took the job and died,
    or a scale-down abandoned it).

    `available: false` IS NOT A TIMEOUT AND NOT A FAILING RUN. `/live` degrades to it for an
    unknown OR FOREIGN scan, and this suite authenticates as whatever the target's access gate
    makes of it — so the same answer means "your scan id is wrong" and "you are asking as a
    different owner than the one who created it". Neither establishes anything about the target's
    ability to process work, so it is `unknown`, with the reason named.
    """
    path = PATH_SCAN_LIVE.format(sid=sid)
    seen: list[int] = []
    for _ in range(max_polls):
        resp = ctx.get(path)
        bad = _unavailable(resp, path)
        if bad is not None:
            return None, bad
        body = _json(resp) or {}
        if not body.get("available", False):
            return None, Outcome.unknown(
                f"{path} reports the run is not available to this caller "
                f"({body.get('reason') or 'no reason given'}); it is either an unknown scan or "
                f"one owned by a different identity, and neither says anything about the target",
                reason=body.get("reason"))
        state = str(body.get("state") or "").strip().lower()
        seen.append(_counts(body)["completed"])
        if state in RUN_SUCCEEDED_STATES:
            return body, None
        if state in RUN_FAILED_STATES:
            return body, Outcome.failed(f"the run ended in state {state!r}", state=state)
        if state not in RUN_IN_PROGRESS_STATES:
            return None, Outcome.unknown(
                f"the run reports state {state!r}, which this suite does not model. That is a gap "
                f"in the suite, not a finding about the target.", state=state)
        ctx.backend.sleep(POLL_SECONDS)
    return None, Outcome.failed(
        f"the run did not reach a terminal state within {max_polls} polls "
        f"({max_polls * POLL_SECONDS:.0f}s); completed went {seen}",
        progress=seen)


def _artifacts(ctx: ScenarioContext, sid: str) -> tuple[list[dict] | None, Outcome | None]:
    """The artifact inventory. Also stashes the whole body on the context for `_artifacts_body`,
    because one field of it — `object_storage_configured` — decides whether an empty inventory is
    a failure or a deployment fact, and threading a second return value through every caller would
    change four signatures for one reader."""
    path = PATH_ARTIFACTS.format(sid=sid)
    resp = ctx.get(path)
    bad = _unavailable(resp, path)
    if bad is not None:
        return None, bad
    body = _json(resp) or {}
    items = body.get("artifacts")
    if not isinstance(items, list):
        return None, Outcome.failed(f"{path} answered {resp.status} with no artifact list",
                                    status=resp.status)
    _LAST_ARTIFACT_BODY[id(ctx)] = body
    return items, None


# Keyed by context identity and never read across runs; see `_artifacts`.
_LAST_ARTIFACT_BODY: dict[int, dict] = {}


def _authoritative(items: list[dict]) -> list[dict]:
    return [a for a in items if a.get("authoritative")]


def _duplicate_outputs(items: list[dict]) -> list[str]:
    """Files with more than one authoritative artifact.

    THE FAILURE THIS DETECTS IS SILENT. A worker restarted mid-document can re-run it and write a
    second output; both writes succeed, both are recorded, and the corrected file a user downloads
    is whichever the API happens to list first. Nothing errors, and the counts still look right if
    you only count files.
    """
    seen: dict[str, int] = {}
    for entry in _authoritative(items):
        name = str(entry.get("file", ""))
        seen[name] = seen.get(name, 0) + 1
    return sorted(name for name, n in seen.items() if n > 1)


def _ephemeral(items: list[dict]) -> list[str]:
    out = []
    for entry in _authoritative(items):
        location = str(entry.get("location", ""))
        scheme = location.split("://", 1)[0] if "://" in location else ""
        if scheme not in DURABLE_SCHEMES:
            out.append(location)
    return out


def _role_status(ctx: ScenarioContext) -> tuple[dict | None, Outcome | None]:
    """`/readyz`'s per-role heartbeat block. Returns (roles, failure).

    A ROLE ABSENT FROM THE BLOCK HAS NEVER BEATEN, which `store.worker_roles_status` draws as a
    deliberate distinction from a role that beat and went stale (present, `alive` false, with an
    age). The two need completely different fixes — a tier that never started versus one that
    started and lost Redis — so the scenarios below keep them apart rather than reporting "not
    ready" for both.
    """
    resp = ctx.get(PATH_READY_ROLES)
    bad = _unavailable(resp, PATH_READY_ROLES)
    if bad is not None:
        return None, bad
    body = _json(resp) or {}
    roles = ((body.get("workers") or {}).get("roles") or {})
    if not isinstance(roles, dict) or "error" in roles:
        return None, Outcome.unknown(
            f"{PATH_READY_ROLES} could not report per-role worker state "
            f"({roles.get('error') if isinstance(roles, dict) else type(roles).__name__})")
    return roles, None


def _ready_replicas(ctx: ScenarioContext, workload: str) -> int | None:
    """Ready replicas for one Deployment, or None when it cannot be read.

    kubectl RATHER THAN AN API FIELD, because replica count is a property of the orchestrator and
    the application does not portably know it — the Azure route that did is the one this suite
    just stopped using.
    """
    got = ctx.backend.kubectl(["get", f"deployment/{workload}", "-n", ctx.target.namespace,
                               "-o", "json"])
    if not got.ok:
        return None
    payload = got.json()
    # NO `status` KEY AT ALL IS "COULD NOT READ", NOT ZERO. A List payload, an empty body or a
    # shape this suite does not model would otherwise read as a Deployment with no ready replicas
    # — reporting a scaling failure on a tier that scaled perfectly.
    if not isinstance(payload, dict) or "status" not in payload:
        return None
    return int((payload.get("status") or {}).get("readyReplicas") or 0)


def _scale(ctx: ScenarioContext, workload: str, replicas: int, *, requires: str):
    return ctx.backend.kubectl(
        ["scale", f"deployment/{workload}", f"--replicas={replicas}",
         "-n", ctx.target.namespace], requires=requires)


# ── 1. api-readiness ──────────────────────────────────────────────────────────

@scenario(id="api-readiness", title="API readiness and build/version reporting",
          claim="mvp", requires=["api"],
          proves="the API answers /healthz and /readyz, and names the build it was made from")
def api_readiness(ctx: ScenarioContext) -> Outcome:
    """PRD §5.1: every image must expose /healthz, /readyz and build version metadata.

    THE VERSION HALF IS NOT DECORATION. An installation that cannot name the commit it was built
    from cannot answer "is my fix live?" except by inference from deploy timestamps — which this
    repository learned the hard way and fixed in #1529. A report certifying a target that cannot
    say what it is running is certifying an unknown.
    """
    health = ctx.get(PATH_HEALTH)
    bad = _unavailable(health, PATH_HEALTH)
    if bad is not None:
        return bad
    if not health.ok:
        return Outcome.failed(f"{PATH_HEALTH} answered {health.status}", status=health.status)
    hbody = _json(health) or {}
    if not hbody.get("version_stamped", False):
        return Outcome.failed(
            "the API is up but reports version_stamped=false, so it cannot name the build it was "
            "made from — every later claim in this report would be about an unidentified release",
            version=hbody.get("version"), commit=hbody.get("commit"))

    ready = ctx.get(PATH_READY)
    bad = _unavailable(ready, PATH_READY)
    if bad is not None:
        return bad
    rbody = _json(ready) or {}
    if ready.status != 200 or not rbody.get("ready", False):
        return Outcome.failed(
            f"{PATH_READY} answered {ready.status} "
            f"(degraded: {rbody.get('degraded') or rbody.get('checks')})",
            status=ready.status, checks=rbody.get("checks"))
    return Outcome.passed(
        f"the API is ready and reports version {hbody.get('version')!r}",
        version=hbody.get("version"), commit=hbody.get("commit"),
        checks=rbody.get("checks"))


# ── 2. worker-registration ────────────────────────────────────────────────────

@scenario(id="worker-registration", title="Worker registration and heartbeats for all three tiers",
          claim="mvp", requires=["api"],
          proves="discover, assess and remediate workers have registered and are heartbeating")
def worker_registration(ctx: ScenarioContext) -> Outcome:
    """PRD §14: worker health and heartbeat, and actual replicas versus application worker slots.

    WHY THE HEARTBEAT AND NOT THE REPLICA COUNT. `kubectl get deploy` showing 3/3 says the pods
    are running; it says nothing about whether they claimed a queue lane. A worker with the wrong
    ACP_WORKER_ROLE, or one that cannot reach Redis, is Ready by every Kubernetes measure and
    processes nothing — and the queue simply grows. So the assertion is on the application's own
    registration surface, and the Deployment count is cross-checked underneath it to tell "no pods"
    apart from "pods that never registered", which need completely different fixes.
    """
    roles, failure = _role_status(ctx)
    if failure is not None:
        return failure
    stale, missing, observed = [], [], {}
    for role in WORKER_ROLES:
        entry = roles.get(role)
        if not entry:
            missing.append(role)
            continue
        age = entry.get("age_s")
        observed[role] = {"alive": entry.get("alive"), "heartbeatAgeSeconds": age,
                          "poolSize": entry.get("pool_size"), "version": entry.get("version")}
        if age is None or float(age) > HEARTBEAT_MAX_SECONDS or not entry.get("alive"):
            stale.append(role)

    pods = {}
    if ctx.target.has("kubectl"):
        got = ctx.backend.kubectl(["get", "deployments", "-n", ctx.target.namespace,
                                   "-l", "app.kubernetes.io/part-of=acp", "-o", "json"])
        for item in ((got.json() or {}).get("items") or []):
            labels = ((item.get("metadata") or {}).get("labels") or {})
            role = labels.get("acp.mova.io/role")
            if role:
                pods[role] = (item.get("status") or {}).get("readyReplicas", 0)

    if missing:
        return Outcome.failed(
            f"no worker tier registered for {', '.join(missing)} — the queue lanes for those job "
            f"types have nothing claiming them",
            roles=observed, readyPods=pods)
    if stale:
        detail = ", ".join(f"{r} (pods ready: {pods.get(r, 'unknown')})" for r in stale)
        return Outcome.failed(
            f"registered tiers with no fresh heartbeat: {detail}. Pods that are Ready but not "
            f"heartbeating look healthy in kubectl and process nothing.",
            roles=observed, readyPods=pods, maxAgeSeconds=HEARTBEAT_MAX_SECONDS)
    return Outcome.passed(
        f"all three worker tiers registered and heartbeating within {HEARTBEAT_MAX_SECONDS}s",
        roles=observed, readyPods=pods)


# ── 3. queue-and-progress ─────────────────────────────────────────────────────

@scenario(id="queue-and-progress", title="Queue processing and SSE live progress",
          claim="mvp", requires=["api"],
          proves="submitted work is queued, processed, and reported live over SSE")
def queue_and_progress(ctx: ScenarioContext) -> Outcome:
    """PRD §19's contract list: queue processing and SSE/live event delivery.

    THE STREAM IS ASSERTED SEPARATELY FROM THE OUTCOME because they fail independently and both
    matter: a target can complete every job while delivering no live events at all (a proxy that
    buffers `text/event-stream` is the usual cause, and it is invisible to any check that only
    polls). The UI is then permanently at "starting…" on an installation whose jobs all succeed.
    """
    sid, failure = _start_scan(ctx)
    if failure is not None:
        return failure

    stream_path = PATH_SCAN_EVENTS.format(sid=sid)
    try:
        events = ctx.backend.sse(stream_path, max_events=10, timeout=POLL_SECONDS * 4)
    except BackendError as exc:
        return Outcome.unknown(f"the event stream at {stream_path} could not be opened: {exc}")

    # THIS STREAM CARRIES NO `event:` FIELD, and an earlier version of this scenario looked for
    # one — it filtered on `event` starting with "progress" and would have reported "no progress
    # events" on a stream working exactly as designed. `stream_live_events` is a snapshot-REPLACE
    # stream: every `data:` frame is the whole `/live` object, emitted when its content changes,
    # with `: keep-alive` comment frames in between. So a progress frame is one whose decoded data
    # is a snapshot, and the keep-alives are deliberately not counted as progress.
    snapshots = [e for e in events if isinstance(e.get("data"), dict)
                 and "available" in e["data"]]
    if not events:
        return Outcome.failed(
            f"{stream_path} opened and delivered no events; live progress is how every UI in this "
            f"application reports work, and a buffered proxy produces exactly this")

    final, failure = _await_scan(ctx, sid)
    if failure is not None:
        return failure
    counts = _counts(final)
    if counts["discovered"] < len(FIXTURES):
        return Outcome.failed(
            f"the queued run completed having discovered {counts['discovered']} documents; the "
            f"image carries at least {len(FIXTURES)} under its local corpus, so the worker tier "
            f"either did not claim the job or listed nothing",
            discovered=counts["discovered"], expected=len(FIXTURES))
    if not snapshots:
        return Outcome.failed(
            f"the run completed but the stream carried no snapshot frames "
            f"(saw {len(events)} frame(s), none of them a snapshot)", frames=len(events))
    return Outcome.passed(
        f"{counts['discovered']} documents queued and processed by the worker tier, with "
        f"{len(snapshots)} live snapshot frames on the event stream",
        scanId=sid, **counts, snapshotFrames=len(snapshots))


# ── 4. fixture-workflow ───────────────────────────────────────────────────────

@scenario(id="fixture-workflow",
          title="Local fixture discovery, assessment, remediation and artifact persistence",
          claim="mvp", requires=["api"],
          proves="a synthetic document goes discover → assess → remediate and its output lands in "
                 "durable storage")
def fixture_workflow(ctx: ScenarioContext) -> Outcome:
    """The end-to-end path, and PRD §12/§20.5: no authoritative output on ephemeral disk.

    THE STORAGE ASSERTION IS THE HALF THAT IS EASY TO MISS. A remediated file written to the
    worker's own /tmp is produced, downloadable and correct — right up to the moment the pod is
    rescheduled, which on an autoscaled tier is routine and unannounced. Nothing errors; the file
    is simply gone, and the scan still says it succeeded. So the check is on WHERE each output
    lives, not on whether it was produced.
    """
    sid, failure = _start_scan(ctx)
    if failure is not None:
        return failure
    _, failure = _await_scan(ctx, sid)
    if failure is not None:
        return failure

    # NEITHER CALL TAKES THE BODY THIS USED TO SEND. `assess` declares only query parameters
    # (`level`, `include_lifecycle_flagged`), so a JSON body is silently ignored — it read as a
    # scope being honoured and never was. `remediate`'s optional body is
    # `{"scope": ["file1.html", ...]}`, a LIST of filenames, and its docstring says omitting it
    # remediates every eligible file, which is exactly what this scenario wants. The old
    # `{"scope": "all"}` was a string where a list belongs.
    for path, label in ((PATH_SCAN_ASSESS, "assessment"), (PATH_SCAN_REMEDIATE, "remediation")):
        resp = _post_with_retry(ctx, path.format(sid=sid))
        bad = _unavailable(resp, path.format(sid=sid))
        if bad is not None:
            return bad
        if not resp.ok:
            return Outcome.failed(
                f"starting {label} answered {resp.status}: {_detail(resp)}",
                status=resp.status, body=_detail(resp))
        if label == "remediation":
            accepted = _json(resp) or {}
            jobs = accepted.get("job_ids")
            if (not isinstance(jobs, list) or any(not isinstance(j, str) or not j for j in jobs)
                    or (not jobs and accepted.get("enqueued") != 0)):
                return Outcome.failed("remediation did not return its accepted job IDs")
            for job_id in jobs:
                job_path = PATH_JOB.format(jid=job_id)
                for _ in range(ASSESS_MAX_POLLS):
                    result = ctx.get(job_path)
                    bad = _unavailable(result, job_path)
                    if bad is not None:
                        return bad
                    status = str((_json(result) or {}).get("status", ""))
                    if status in ("complete", "completed", "done"):
                        break
                    if status in ("failed", "error", "dead", "cancelled"):
                        return Outcome.failed(f"the remediation job ended {status!r}", job=job_id)
                    ctx.backend.sleep(POLL_SECONDS)
                else:
                    return Outcome.failed("the remediation job did not finish within "
                                          f"{ASSESS_MAX_POLLS * POLL_SECONDS:.0f}s", job=job_id)
            continue
        # Assessment completion is scan-level progress, as adopted from #1827.
        # `kpis.completed` REACHING `totals.eligible` is the completion signal, and it has to be
        # that rather than "the run reached a terminal state": a Discover-only run is ALREADY
        # terminal at `discovered` (see RUN_SUCCEEDED_STATES), so a terminal-state wait here would
        # return immediately and report an assessment that had not started as finished.
        progressed = False
        for _ in range(ASSESS_MAX_POLLS):
            snap = ctx.get(PATH_SCAN_LIVE.format(sid=sid))
            bad = _unavailable(snap, PATH_SCAN_LIVE.format(sid=sid))
            if bad is not None:
                return bad
            body = _json(snap) or {}
            state = str(body.get("state") or "").strip().lower()
            if state in RUN_FAILED_STATES:
                return Outcome.failed(f"the run ended in state {state!r} during {label}",
                                      state=state, **_counts(body))
            counts = _counts(body)
            if counts["eligible"] and counts["completed"] >= counts["eligible"]:
                progressed = True
                break
            if not counts["eligible"] and state in RUN_SUCCEEDED_STATES:
                # NOTHING ELIGIBLE AND THE RUN IS TERMINAL: there is no work to wait for, and
                # waiting for zero documents to complete waits forever. The artifact check below
                # is what then reports the absence, with the reason it deserves.
                progressed = True
                break
            ctx.backend.sleep(POLL_SECONDS)
        if not progressed:
            # THE COUNTS GO IN THE MESSAGE, not only the evidence. "did not complete within 120s"
            # was true and told me nothing: a run stalled at 0 of 6 and a run one document short
            # produce the identical line, and they are completely different findings. The 503
            # taught the same lesson one round earlier.
            final_counts = _counts(_json(ctx.get(PATH_SCAN_LIVE.format(sid=sid))) or {})
            return Outcome.failed(
                f"{label} did not complete within "
                f"{ASSESS_MAX_POLLS * POLL_SECONDS:.0f}s — "
                f"{final_counts['completed']} of {final_counts['eligible']} eligible documents "
                f"finished ({final_counts['discovered']} discovered)",
                **final_counts)

    items, failure = _artifacts(ctx, sid)
    if failure is not None:
        return failure
    items_body = _LAST_ARTIFACT_BODY.get(id(ctx), {})
    authoritative = _authoritative(items or [])
    ephemeral = _ephemeral(items or [])
    manifest = ctx.artifact(
        "artifact-manifest.json",
        "\n".join(f"{a.get('file')}\t{a.get('location')}" for a in authoritative),
        scenario_id="fixture-workflow")
    if len(authoritative) < len(FIXTURES):
        # TWO READINGS OF AN EMPTY INVENTORY THAT LOOK IDENTICAL AND MEAN OPPOSITE THINGS. If the
        # installation has no object storage configured, nothing here was ever going to keep a
        # corrected copy, and reporting that as a §20.5 FAILURE would accuse the application of a
        # defect that belongs to the deployment. If storage IS configured and the artifacts are
        # still missing, remediation produced nothing and that is a failure.
        #
        # The distinction is the target's answer, not a guess: `/artifacts` reports
        # `object_storage_configured` for exactly this.
        if not (items_body or {}).get("object_storage_configured", True):
            return Outcome.unknown(
                f"the workflow ran and {len(authoritative)} authoritative artifacts exist, and "
                f"this installation has NO object storage configured — so nothing here was going "
                f"to keep a corrected copy and §20.5 cannot be evaluated. That is a fact about "
                f"the deployment, not a defect in remediation.",
                expected=len(FIXTURES), found=len(authoritative), objectStorage=False
            ).with_artifacts([manifest])
        return Outcome.failed(
            f"{len(FIXTURES)} synthetic documents produced {len(authoritative)} authoritative "
            f"artifacts", expected=len(FIXTURES), found=len(authoritative)
        ).with_artifacts([manifest])
    if ephemeral:
        return Outcome.failed(
            f"{len(ephemeral)} authoritative artifact(s) exist only on ephemeral storage "
            f"({', '.join(sorted(ephemeral)[:3])}). PRD §12: they are lost on the next pod "
            f"reschedule, silently.", ephemeral=sorted(ephemeral)
        ).with_artifacts([manifest])
    return Outcome.passed(
        f"{len(authoritative)} documents discovered, assessed, remediated, and persisted to "
        f"durable storage", scanId=sid, artifacts=len(authoritative),
        schemes=sorted({str(a.get('location', '')).split('://')[0] for a in authoritative})
    ).with_artifacts([manifest])


# ── 5. audit-and-diagnostics ──────────────────────────────────────────────────

@scenario(id="audit-and-diagnostics", title="Audit-event persistence and redacted diagnostics",
          claim="mvp", requires=["api"],
          proves="operational events are recorded, and the diagnostics export carries no secret")
def audit_and_diagnostics(ctx: ScenarioContext) -> Outcome:
    """PRD §13: audit records for deployment, configuration and capacity changes, and support
    bundles that redact tokens, document names, user identities and file contents.

    THE REDACTION HALF IS CHECKED AGAINST THIS RUN'S OWN CREDENTIALS. The suite knows exactly
    which secret values the target descriptor carries, so it can do what no generic scrubber can:
    fetch the bundle and look for those literal values. That turns "the export says it is
    redacted" — a boolean the export sets about itself — into a fact somebody measured.
    """
    resp = ctx.get(PATH_AUDIT + "?limit=50")
    bad = _unavailable(resp, PATH_AUDIT)
    if bad is not None:
        return bad
    events = (_json(resp) or {}).get("events") or []
    kinds = sorted({str(e.get("type", "")) for e in events})
    if not events:
        return Outcome.failed(
            f"{PATH_AUDIT} returned no audit events at all; PRD §13 requires deployment, "
            f"configuration and capacity changes to be recorded")

    bundle = ctx.get(PATH_SUPPORT_BUNDLE)
    bad = _unavailable(bundle, PATH_SUPPORT_BUNDLE)
    if bad is not None:
        return bad
    if not bundle.ok:
        return Outcome.failed(f"{PATH_SUPPORT_BUNDLE} answered {bundle.status}",
                              status=bundle.status)
    leaked = sorted(v for v in ctx.target.secret_values() if len(v) >= 6 and v in bundle.body)
    if leaked:
        # NAMES NOTHING. Reporting which value leaked would put it in the report — the same
        # document this scenario just proved the bundle should not contain.
        return Outcome.failed(
            f"the diagnostics export contains {len(leaked)} value(s) that this run supplied as "
            f"credentials. PRD §13 requires support bundles to redact tokens; this one does not.",
            leakedValueCount=len(leaked))
    body = _json(bundle) or {}
    if body.get("redacted") is not True:
        return Outcome.failed("the diagnostics export does not declare itself redacted",
                              flags=sorted(body.keys()))
    return Outcome.passed(
        f"{len(events)} audit events recorded and a redacted diagnostics export carrying none of "
        f"this run's credentials", eventTypes=kinds)


# ── 6. worker-restart ─────────────────────────────────────────────────────────

@scenario(id="worker-restart", title="Restart of each worker tier during a job",
          claim="mvp", requires=["api", "kubectl", "workload-restart"],
          proves="a restarted worker tier neither loses work nor produces a duplicate "
                 "authoritative output")
def worker_restart(ctx: ScenarioContext) -> Outcome:
    """PRD §19's failure tests: a worker dies mid-job. Two distinct failures, both silent.

    LOST WORK is the one people expect: the job stalls, and on a cluster where pods restart for
    ordinary reasons (a node drain, an OOM, a rollout) it looks like ACP being slow.

    DUPLICATE AUTHORITATIVE OUTPUT is the one that matters more and is far harder to see. A
    restarted worker that re-runs a document it had already finished writes a SECOND corrected
    file. Both writes succeed. The user downloads whichever the API lists first, and the two may
    differ. No count is wrong — there are still four documents — which is why this asserts one
    authoritative artifact PER FILE rather than a total.

    ALL THREE TIERS, not one: they have different lease and idempotency code paths, and a suite
    that restarts only discovery certifies nothing about remediation, which is the tier that
    writes the authoritative output in the first place.
    """
    findings, evidence = [], {}
    for role in WORKER_ROLES:
        sid, failure = _start_scan(ctx)
        if failure is not None:
            return failure
        ctx.backend.sleep(POLL_SECONDS)          # let work actually start before pulling the tier
        restart = ctx.backend.kubectl(
            ["rollout", "restart", f"deployment/{WORKLOAD[role]}", "-n", ctx.target.namespace],
            requires="workload-restart")
        if not restart.ok:
            return Outcome.unknown(
                f"could not restart the {role} tier ({restart.error or restart.stderr.strip()}), "
                f"so its behaviour under restart was not established", role=role)
        final, failure = _await_scan(ctx, sid)
        if failure is not None:
            # AN `unknown` IS NOT A LOST-WORK FINDING, and folding it in was a real defect: the
            # first reference-cluster run reported "work did not complete after the tier
            # restarted" for all three tiers, on a cluster where all three had completed, because
            # `_await_scan` came back `unknown` over a run state the suite did not model. The
            # runner's rule is that nothing about the target is established by a call that could
            # not be interpreted, so that must propagate as `unknown` and never become a FAIL.
            if failure.state == UNKNOWN:
                return failure
            # A run that genuinely did not finish after a restart IS the lost-work failure;
            # reported as this scenario's finding rather than as a generic timeout.
            findings.append(f"{role}: work did not complete after the tier restarted "
                            f"({failure.detail})")
            evidence[role] = {"scanId": sid, "completed": False}
            continue
        items, failure = _artifacts(ctx, sid)
        if failure is not None:
            return failure
        duplicates = _duplicate_outputs(items or [])
        authoritative = _authoritative(items or [])
        evidence[role] = {"scanId": sid, "completed": True,
                          "authoritativeArtifacts": len(authoritative),
                          "duplicates": duplicates}
        if not authoritative:
            # THE DUPLICATE HALF WAS NOT EXERCISED, so this scenario has not proved its claim.
            # `proves` says the tier "neither loses work NOR produces a duplicate authoritative
            # output"; with no artifacts at all, "no duplicates" is vacuously true and a `pass`
            # would be a check that could not have failed. The lost-work half DID hold — the run
            # completed after the restart — and that is stated rather than discarded.
            #
            # Reachable as soon as `/scans/{sid}/artifacts` exists: before it did, this scenario
            # returned `unknown` at the probe itself and never got here.
            return Outcome.unknown(
                f"the {role} tier restarted and its work completed, so no work was lost — but the "
                f"scan produced no authoritative artifacts, so whether a restart DUPLICATES one "
                f"was not exercised. A discover-only run cannot answer that half.",
                role=role, tiers=evidence)
        if duplicates:
            findings.append(f"{role}: {len(duplicates)} document(s) have two authoritative "
                            f"outputs after the restart")
        elif _counts(final)["discovered"] < len(FIXTURES):
            findings.append(f"{role}: {_counts(final)['discovered']} of {len(FIXTURES)} documents "
                            f"survived the restart")
    if findings:
        return Outcome.failed("; ".join(findings), tiers=evidence)
    return Outcome.passed(
        "each of the three worker tiers was restarted mid-job with no lost work and exactly one "
        "authoritative output per document", tiers=evidence)


# ── 7. dependency-degradation ─────────────────────────────────────────────────

@scenario(id="dependency-degradation",
          title="Redis, Postgres, object-storage and AI-provider degradation behaviour",
          claim="supported", requires=["api", "kubectl", "fault-injection"],
          proves="each dependency's absence is reported as not-ready rather than absorbed, and "
                 "the installation recovers when it returns")
def dependency_degradation(ctx: ScenarioContext) -> Outcome:
    """PRD §19's failure tests, and §14's connectivity reporting.

    WHAT IS BEING ASSERTED IS THE HONESTY OF /readyz, NOT SURVIVAL. An API that keeps answering
    200 while Postgres is gone is the dangerous case: Kubernetes goes on routing traffic to it,
    the load balancer sees a healthy backend, and every request fails somewhere deeper where the
    cause is much harder to see. Reporting not-ready is what lets the platform do its job.

    RECOVERY IS PART OF THE SCENARIO. A target that goes not-ready and stays there after the
    dependency returns needs a manual restart to recover, which is an outage in every incident
    that touches Redis — and it passes any check that only takes the dependency away.
    """
    results, unknowns = {}, []
    for dep, workload in DEPENDENCY_WORKLOAD.items():
        down = _scale(ctx, workload, 0, requires="fault-injection")
        if not down.ok:
            # A managed dependency has no workload to scale. That is a legitimate target shape and
            # NOT a pass: the behaviour was not observed. Naming the dependency keeps the report
            # actionable — the operator can inject the fault their own way and re-run.
            unknowns.append(f"{dep} ({down.error or down.stderr.strip() or 'no such workload'})")
            continue
        resp = ctx.get(PATH_READY)
        body = _json(resp) or {}
        degraded = resp.status == 503 or body.get("ready") is False
        named = DEPENDENCY_CHECK[dep] in (body.get("degraded") or []) or \
            str((body.get("checks") or {}).get(DEPENDENCY_CHECK[dep], "")) not in ("ok", "")
        up = _scale(ctx, workload, 1, requires="fault-injection")
        recovered = False
        if up.ok:
            for _ in range(MAX_POLLS):
                again = ctx.get(PATH_READY)
                if again.status == 200 and (_json(again) or {}).get("ready"):
                    recovered = True
                    break
                ctx.backend.sleep(POLL_SECONDS)
        results[dep] = {"reportedNotReady": bool(degraded), "namedTheDependency": bool(named),
                        "recovered": recovered, "statusWhileDown": resp.status}

    if unknowns:
        return Outcome.unknown(
            "could not take these dependencies away on this target, so their degradation "
            "behaviour was not established: " + "; ".join(unknowns),
            observed=results, notInjected=sorted(u.split(" ")[0] for u in unknowns))
    bad = [dep for dep, r in results.items()
           if not r["reportedNotReady"] or not r["recovered"]]
    if bad:
        return Outcome.failed(
            "dependencies whose absence was absorbed rather than reported, or which did not "
            "recover when restored: " + ", ".join(sorted(bad)), observed=results)
    return Outcome.passed(
        f"all {len(results)} dependencies reported not-ready while absent and recovered when "
        f"restored", observed=results)


# ── 8. scale-updown ───────────────────────────────────────────────────────────

@scenario(id="scale-updown", title="Scale-up and graceful scale-down with active jobs",
          claim="supported", requires=["api", "kubectl", "scale-control"],
          proves="new replicas register, and a scale-down during active work drains rather than "
                 "abandoning it")
def scale_updown(ctx: ScenarioContext) -> Outcome:
    """PRD §11: independent worker scaling, and "drain workers before scale-down".

    THE SCALE-DOWN IS THE HALF WITH TEETH. Scaling up and watching pods appear proves the
    autoscaler's arithmetic; scaling down while documents are in flight is where work is quietly
    abandoned. The job's lease expires, nothing retries it, the scan sits at 3/4 forever, and the
    only symptom is a number that stops moving — on a KEDA-scaled tier that happens whenever the
    queue drains, which is to say constantly and unattended.
    """
    role = "assess"
    workload = WORKLOAD[role]
    start_replicas = _ready_replicas(ctx, workload)
    if start_replicas is None:
        return Outcome.unknown(
            f"could not read the replica count of {workload}; nothing about scaling was "
            f"established", workload=workload)
    start_replicas = max(1, start_replicas)

    up = _scale(ctx, workload, start_replicas + 2, requires="scale-control")
    if not up.ok:
        return Outcome.unknown(f"could not scale {workload}: {up.error or up.stderr.strip()}")
    # BOTH HALVES, because either alone passes on a broken tier: pods can be Ready without ever
    # claiming a queue lane (scenario 2's whole subject), and the tier can keep heartbeating from
    # its OLD replicas while the new ones never start.
    registered = False
    for _ in range(MAX_POLLS):
        ready_now = _ready_replicas(ctx, workload) or 0
        roles, failure = _role_status(ctx)
        entry = (roles or {}).get(role) or {}
        if ready_now >= start_replicas + 2 and entry.get("alive"):
            registered = True
            break
        ctx.backend.sleep(POLL_SECONDS)
    if not registered:
        _scale(ctx, workload, start_replicas, requires="scale-control")
        return Outcome.failed(
            f"scaled {workload} to {start_replicas + 2} and the new replicas never registered "
            f"with the queue within {MAX_POLLS * POLL_SECONDS:.0f}s", role=role)

    sid, failure = _start_scan(ctx)
    if failure is not None:
        return failure
    ctx.backend.sleep(POLL_SECONDS)
    down = _scale(ctx, workload, start_replicas, requires="scale-control")
    if not down.ok:
        return Outcome.unknown(f"could not scale {workload} back down: {down.stderr.strip()}")
    final, failure = _await_scan(ctx, sid)
    if failure is not None:
        return Outcome.failed(
            f"work in flight during the scale-down did not complete: {failure.detail}. PRD §11 "
            f"requires draining before scale-down.", role=role, scanId=sid)
    items, failure = _artifacts(ctx, sid)
    if failure is not None:
        return failure
    duplicates = _duplicate_outputs(items or [])
    if duplicates:
        return Outcome.failed(
            f"the drained tier re-ran {len(duplicates)} document(s), leaving two authoritative "
            f"outputs each", duplicates=duplicates)
    return Outcome.passed(
        f"{workload} scaled {start_replicas}→{start_replicas + 2}→{start_replicas}; new replicas "
        f"registered and in-flight work drained without duplication",
        role=role, scanId=sid, **_counts(final))


# ── 9. upgrade-from-previous ──────────────────────────────────────────────────

@scenario(id="upgrade-from-previous", title="Upgrade from the previous supported release",
          claim="supported", requires=["helm", "kubectl", "api", "previous-release"],
          proves="the previous release upgrades to this one by digest, migrations run, and the "
                 "installation is ready afterwards")
def upgrade_from_previous(ctx: ScenarioContext) -> Outcome:
    """PRD §15 and §20.7: upgrade demonstrated from the previous supported release.

    DIGEST-PINNING IS A PRECONDITION, NOT A NICE-TO-HAVE. §15 requires deploying "new API and
    workers by immutable digest", so an upgrade performed against a mutable tag has not
    demonstrated the requirement no matter how cleanly it ran — the same tag can resolve to a
    different image an hour later, and the run would be certifying something nobody can reproduce.
    """
    previous = ctx.target.release.previous_version
    if not previous:
        return Outcome.skipped(
            "the target descriptor names no previous release, so there is nothing to upgrade from")
    if not ctx.target.release.pinned:
        return Outcome.failed(
            "this release is not pinned by digest, so an upgrade here cannot demonstrate PRD §15 "
            "(deploy new API and workers by immutable digest) whatever the upgrade does",
            components=sorted(ctx.target.release.components))

    history = ctx.backend.helm(["history", ctx.target.release_name, "-n", ctx.target.namespace,
                                "-o", "json"])
    if not history.ok:
        return Outcome.unknown(
            f"could not read the release history: {history.error or history.stderr.strip()}")
    revisions = history.json() or []
    if not any(str(r.get("app_version")) == previous for r in revisions):
        return Outcome.unknown(
            f"the release history does not contain {previous!r}, so this run cannot show an "
            f"upgrade FROM the previous supported release",
            versions=[r.get("app_version") for r in revisions])

    upgraded = ctx.backend.helm(
        ["upgrade", ctx.target.release_name, "-n", ctx.target.namespace, "--wait"],
        requires="previous-release")
    if not upgraded.ok:
        return Outcome.failed(f"helm upgrade failed: {upgraded.stderr.strip() or upgraded.error}")

    jobs = ctx.backend.kubectl(["get", "jobs", "-n", ctx.target.namespace,
                                "-l", "app.kubernetes.io/component=migrations", "-o", "json"])
    migrations = [(j.get("status") or {}) for j in ((jobs.json() or {}).get("items") or [])]
    if not migrations:
        return Outcome.unknown("no migration Job was found after the upgrade, so whether "
                               "migrations ran could not be established")
    if any(int(m.get("failed") or 0) for m in migrations):
        return Outcome.failed("a migration Job failed during the upgrade", jobs=migrations)

    health = ctx.get(PATH_HEALTH)
    version = (_json(health) or {}).get("version")
    ready = ctx.get(PATH_READY)
    if ready.status != 200:
        return Outcome.failed(f"the installation is not ready after the upgrade "
                              f"({PATH_READY} answered {ready.status})", version=version)
    if ctx.target.release.version and version != ctx.target.release.version:
        return Outcome.failed(
            f"after the upgrade the API reports {version!r}, not the target release "
            f"{ctx.target.release.version!r}", reported=version)
    return Outcome.passed(
        f"upgraded from {previous} to {version} by pinned digest; migrations succeeded and the "
        f"installation is ready", fromVersion=previous, toVersion=version,
        migrationJobs=len(migrations))


# ── 10. backup-restore ────────────────────────────────────────────────────────

@scenario(id="backup-restore", title="Backup followed by an actual restore and a post-restore "
                                     "workflow",
          claim="supported", requires=["kubectl", "api", "backup-restore"],
          proves="a backup can be restored, and the installation processes documents afterwards")
def backup_restore(ctx: ScenarioContext) -> Outcome:
    """PRD §16: "a backup is not considered healthy until a restore test has succeeded".

    THE RESTORE IS THE SCENARIO. A backup job that exits zero proves a file was written; it proves
    nothing about whether that file can be read back, whether the schema it contains matches the
    running release, or whether object-storage artifacts were included. Every one of those fails
    only at restore time — which, if this scenario merely checked backup freshness, would be
    during the incident.

    AND A WORKFLOW AFTERWARDS, because a restore that leaves the installation unable to process a
    document has restored data into something that cannot use it.
    """
    ns = ctx.target.namespace
    backup = ctx.backend.kubectl(
        ["create", "job", f"acceptance-backup", "--from=cronjob/acp-backup", "-n", ns],
        requires="backup-restore")
    if not backup.ok:
        return Outcome.unknown(
            f"no backup job could be created on this target "
            f"({backup.error or backup.stderr.strip()}), so backup and restore were not exercised")

    restore = ctx.backend.kubectl(
        ["create", "job", f"acceptance-restore", "--from=cronjob/acp-restore", "-n", ns],
        requires="backup-restore")
    if not restore.ok:
        return Outcome.failed(
            f"the backup ran but no restore could be performed "
            f"({restore.error or restore.stderr.strip()}). PRD §16: a backup is not healthy until "
            f"a restore has succeeded.")

    jobs = ctx.backend.kubectl(["get", "jobs", "-n", ns, "-o", "json"])
    statuses = [(j.get("metadata") or {}).get("name", "") for j in
                ((jobs.json() or {}).get("items") or [])
                if int(((j.get("status") or {}).get("failed") or 0)) > 0]
    if statuses:
        return Outcome.failed(f"backup/restore jobs reported failures: {', '.join(statuses)}")

    sid, failure = _start_scan(ctx)
    if failure is not None:
        return Outcome.failed(
            f"the restore completed but the installation could not accept work afterwards: "
            f"{failure.detail}")
    final, failure = _await_scan(ctx, sid)
    if failure is not None:
        return Outcome.failed(
            f"the post-restore workflow did not complete: {failure.detail}", scanId=sid)
    items, failure = _artifacts(ctx, sid)
    if failure is not None:
        return failure
    return Outcome.passed(
        f"backup taken, restore performed, and a {len(FIXTURES)}-document workflow completed "
        f"afterwards with {len(_authoritative(items or []))} artifacts persisted",
        scanId=sid, **_counts(final))
