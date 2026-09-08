"""A described target the whole suite can run against, with no cluster anywhere.

WHY A SIMULATOR AND NOT A RECORDED TRANSCRIPT. The interesting acceptance cases are behaviours
over time — a worker tier restarted while a job is running, a dependency taken away and put back,
a scale-down that must drain rather than abandon. A transcript of a healthy run cannot express any
of them, and a suite whose failure paths are never exercised is a suite whose failure paths are
first exercised on certification day. So this is a small state machine: a scan progresses, a
rollout restart resets pods, scaling a dependency to zero makes `/readyz` report it unavailable.

WHAT IT DOES NOT PROVE, stated plainly because it is the limitation that matters most here — the
same one `tests/packaging_kubectl_fake.py` states for kubectl. These responses are what ACP's API
and kubectl are DOCUMENTED to return, not a recording of a real deployment. They exercise the
suite's LOGIC, its report format and its eligibility rule; they establish nothing whatsoever about
any real target, and `--self-test` says so in the report it writes (`target.name: self-test`, and
the runner refuses to let a self-test report claim eligibility for a real target name).

BREAK ONE THING, ASSERT ONE FINDING. `world(...)` returns the healthy target with overrides
applied, exactly like `packaging_kubectl_fake.shape(...)`, and `faults` lets a test make any single
route fail. A scenario test that cannot make its scenario FAIL is a claim, not a test.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .backend import BackendError, CommandResult, ExecutionBackend, HttpResponse

# The three worker roles the application understands (api/core.py's ACP_WORKER_ROLE values, as
# mirrored in acpctl's inventory.TIER_ROLE). Named here because scenario 2 and scenario 6 both
# iterate them and a suite that checked two of three would pass a target with no remediate tier.
WORKER_ROLES = ("discovery", "assess", "remediate")

# Deployment names the chart renders for each role, and for the optional in-cluster dependencies.
# A target with managed Postgres/Redis/object storage HAS NO SUCH WORKLOADS, which is why the
# degradation scenario reports `unknown` rather than `pass` when it cannot find one — "we could
# not take it away" is not "it degrades correctly".
WORKLOADS = {
    "api": "acp-api",
    "discovery": "acp-worker-discover",
    "assess": "acp-worker-assess",
    "remediate": "acp-worker-remediate",
    "redis": "acp-redis",
    "postgres": "acp-postgres",
    "object-storage": "acp-objectstore",
    "ai-provider": "acp-ollama",
}

HEALTHY: dict[str, Any] = {
    "healthz": {"ok": True, "service": "acp", "version": "2026.9.8.1",
                "commit": "1" * 40, "built_at": "2026-09-08T09:00:00Z", "version_stamped": True},
    "readyz_checks": {"database": "ok", "redis": "ok", "object_storage": "ok",
                      "ai_provider": "ok", "pdf_engine": "ok"},
    # Per role: replicas, ready, heartbeat age, and the slot count the tier advertises. A worker
    # with pods but no heartbeat is the case scenario 2 exists for — a Deployment reporting 3/3
    # while nothing has registered with the queue looks perfectly healthy in kubectl.
    "workers": {role: {"replicas": 2, "ready": 2, "heartbeat_age_seconds": 4, "slots": 4}
                for role in WORKER_ROLES},
    "queue": {"depth": 0, "oldest_wait_seconds": 0},
    # How many status polls a scan takes to finish. Small so the self-test is fast; the point is
    # that it is more than one, so "poll until terminal" is actually exercised.
    "scan_polls_until_complete": 2,
    "artifact_scheme": "s3",              # where remediated output lands (PRD §12)
    "duplicate_artifacts": False,         # scenario 6's failure mode
    "lose_work_on_restart": False,        # scenario 6's other failure mode
    "drains_on_scale_down": True,         # scenario 8
    "audit_events": ["scan.started", "scan.completed", "remediation.completed",
                     "deployment.installed", "capacity.changed"],
    # The redacted diagnostics export. Deliberately carries a field that LOOKS like a secret name
    # and a value that is a reference, so scenario 5 has something real to assert on.
    "support_bundle": {
        "redacted": True,
        "release": "2026.9.8.1",
        "secrets": {"postgres": "secretRef://acp/postgres-url", "redis": "secretRef://acp/redis-url"},
        "documents": {"count": 4, "names_included": False},
    },
    "backup": {"exists": True, "age_hours": 3, "restore_tested": False},
    "helm_revision": 3,
    "migrations_job": {"name": "acp-migrations-3", "succeeded": 1, "failed": 0},
    "previous_version": "2026.8.30.2",
    # Route-level overrides: {"GET /readyz": {"status": 503}} or {"error": "connection refused"}
    # or {"json": {...}}. One place to break one thing.
    "faults": {},
}


def world(**overrides: Any) -> dict[str, Any]:
    """The healthy target with `overrides` applied at the top level."""
    shape = copy.deepcopy(HEALTHY)
    shape.update(copy.deepcopy(overrides))
    return shape


@dataclass
class _Scan:
    scan_id: str
    files: list[str]
    polls: int = 0
    restarts: int = 0
    lost: bool = False
    finished_files: int = 0


class FakeBackend(ExecutionBackend):
    """An ExecutionBackend that answers from `world` and records everything.

    Its clock is FAKE and monotonic by construction: `sleep` advances it. That is not only about
    test speed — it makes `durationSeconds` in the report deterministic, so a test can assert on
    the report's shape without matching floats, and a self-test report is byte-comparable between
    runs except for its start timestamp.
    """

    kind = "fake"

    def __init__(self, shape: dict[str, Any] | None = None, *,
                 grants: frozenset[str] = frozenset(),
                 start: datetime | None = None) -> None:
        super().__init__(grants=grants)
        self.world = shape if shape is not None else world()
        self._clock = 0.0
        self._wall = start or datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
        self._scans: dict[str, _Scan] = {}
        self._next_id = 1
        # Dependency name -> replica count. Scaling one to zero is how the degradation scenario
        # takes it away, and `/readyz` reads this back.
        self._deps = {name: 1 for name in ("redis", "postgres", "object-storage", "ai-provider")}
        self._restarts: dict[str, int] = {}
        self._replicas = {role: self.world["workers"][role]["replicas"] for role in WORKER_ROLES}
        self._restored = False

    # -- clock --------------------------------------------------------------
    def utcnow(self) -> datetime:
        return self._wall + timedelta(seconds=self._clock)

    def monotonic(self) -> float:
        # Every call advances the clock a little, so a scenario that does real work has a
        # non-zero duration in the report without anybody sleeping.
        self._clock += 0.001
        return self._clock

    def _sleep(self, seconds: float) -> None:
        self._clock += seconds

    # -- fault plumbing -----------------------------------------------------
    def _fault(self, key: str) -> dict | None:
        return (self.world.get("faults") or {}).get(key)

    # -- HTTP ---------------------------------------------------------------
    def _http(self, method: str, path: str, body: Any) -> HttpResponse:
        route, params = _match(method, path)
        fault = self._fault(route) if route else None
        if fault:
            if "error" in fault:
                return HttpResponse(0, error=fault["error"])
            return HttpResponse(fault.get("status", 500),
                                json.dumps(fault.get("json", {"detail": "injected fault"})))
        if route is None:
            # An unmodelled path is a 404, which is what a real build that does not serve the
            # surface would answer. Scenarios turn that into `unknown` ("this build does not serve
            # X"), never into a pass, and never into a fail about the target's behaviour.
            return HttpResponse(404, json.dumps({"detail": f"no route {method} {path}"}))
        handler = getattr(self, f"_route_{route.split(' ')[0].lower()}_{_slug(route)}")
        return handler(params, body)

    # /healthz
    def _route_get_healthz(self, params, body) -> HttpResponse:
        return HttpResponse(200, json.dumps(self.world["healthz"]))

    # /readyz — the one route that reads the simulated dependency state
    def _route_get_readyz(self, params, body) -> HttpResponse:
        checks = dict(self.world["readyz_checks"])
        down = [name for name, n in self._deps.items() if n == 0]
        mapping = {"redis": "redis", "postgres": "database",
                   "object-storage": "object_storage", "ai-provider": "ai_provider"}
        for dep in down:
            checks[mapping[dep]] = "unavailable"
        ready = not down
        payload = {"ready": ready, "checks": checks,
                   "degraded": sorted(mapping[d] for d in down)}
        # 503 when not ready: a readiness probe that answers 200 while a dependency is gone is the
        # bug PRD §14 is about, and the degradation scenario asserts the status code, not just the
        # body, because Kubernetes routes traffic on the code.
        return HttpResponse(200 if ready else 503, json.dumps(payload))

    def _route_get_control_workers_capacity(self, params, body) -> HttpResponse:
        roles = {}
        for role in WORKER_ROLES:
            entry = dict(self.world["workers"][role])
            entry["replicas"] = self._replicas[role]
            entry["ready"] = min(entry.get("ready", 0), self._replicas[role])
            roles[role] = entry
        return HttpResponse(200, json.dumps({"roles": roles, "queue": self.world["queue"]}))

    def _route_post_scans(self, params, body) -> HttpResponse:
        files = list((body or {}).get("fixtures") or [])
        scan_id = f"acc-scan-{self._next_id}"
        self._next_id += 1
        self._scans[scan_id] = _Scan(scan_id, files)
        return HttpResponse(201, json.dumps({"scan_id": scan_id, "files_total": len(files)}))

    def _route_get_scans_status(self, params, body) -> HttpResponse:
        scan = self._scans.get(params["sid"])
        if scan is None:
            return HttpResponse(404, json.dumps({"detail": "no such scan"}))
        scan.polls += 1
        if scan.lost:
            # Work was lost: the scan never terminates and its progress went BACKWARDS. Both are
            # asserted, because a stall alone is indistinguishable from a slow cluster.
            return HttpResponse(200, json.dumps({
                "scan_id": scan.scan_id, "status": "running",
                "files_total": len(scan.files), "files_done": 0, "restarts": scan.restarts}))
        done = min(len(scan.files), scan.polls * max(1, len(scan.files)))
        complete = scan.polls >= int(self.world["scan_polls_until_complete"])
        scan.finished_files = len(scan.files) if complete else done
        return HttpResponse(200, json.dumps({
            "scan_id": scan.scan_id,
            "status": "complete" if complete else "running",
            "files_total": len(scan.files),
            "files_done": scan.finished_files,
            "restarts": scan.restarts}))

    def _route_get_scans_events(self, params, body) -> HttpResponse:
        return HttpResponse(200, "")     # only used via _sse; kept so the route is known

    def _route_post_scans_assess(self, params, body) -> HttpResponse:
        return HttpResponse(202, json.dumps({"job_id": f"assess-{params['sid']}"}))

    def _route_post_scans_remediate(self, params, body) -> HttpResponse:
        return HttpResponse(202, json.dumps({"job_id": f"remediate-{params['sid']}"}))

    def _route_get_scans_jobs(self, params, body) -> HttpResponse:
        return HttpResponse(200, json.dumps({"job_id": params["jid"], "status": "complete"}))

    def _route_get_scans_artifacts(self, params, body) -> HttpResponse:
        scan = self._scans.get(params["sid"])
        if scan is None:
            return HttpResponse(404, json.dumps({"detail": "no such scan"}))
        scheme = self.world["artifact_scheme"]
        artifacts = []
        for name in scan.files:
            entry = {"file": name, "authoritative": True,
                     "location": f"{scheme}://acp-artifacts/{scan.scan_id}/{name}",
                     "sha256": f"sha256:{abs(hash(name)) % (10 ** 12):012d}"}
            artifacts.append(entry)
            if self.world["duplicate_artifacts"] and scan.restarts:
                # The failure scenario 6 exists to catch: a restarted worker re-ran the document
                # and wrote a SECOND authoritative output. Nothing errors; there are simply two.
                artifacts.append(dict(entry, location=entry["location"] + ".retry"))
        return HttpResponse(200, json.dumps({"scan_id": scan.scan_id, "artifacts": artifacts}))

    def _route_get_admin_audit_events(self, params, body) -> HttpResponse:
        events = [{"type": t, "at": self.utcnow().isoformat(), "actor": "acceptance-suite"}
                  for t in self.world["audit_events"]]
        return HttpResponse(200, json.dumps({"events": events}))

    def _route_get_admin_support_bundle(self, params, body) -> HttpResponse:
        return HttpResponse(200, json.dumps(self.world["support_bundle"]))

    # -- SSE ----------------------------------------------------------------
    def _sse(self, path: str, max_events: int, timeout: float) -> list[dict]:
        fault = self._fault("SSE " + re.sub(r"acc-scan-\d+", "{sid}", path))
        if fault:
            if "error" in fault:
                raise BackendError(fault["error"])
            return list(fault.get("events", []))
        m = re.match(r"^/scans/(?P<sid>[^/]+)/events$", path)
        if not m:
            raise BackendError(f"the fake target serves no event stream at {path!r}")
        scan = self._scans.get(m.group("sid"))
        if scan is None:
            raise BackendError("no such scan")
        total = max(1, len(scan.files))
        events = [{"event": "progress",
                   "data": {"scan_id": scan.scan_id, "files_done": i + 1, "files_total": total}}
                  for i in range(min(total, max_events - 1))]
        events.append({"event": "complete", "data": {"scan_id": scan.scan_id, "status": "complete"}})
        return events[:max_events]

    # -- kubectl / helm -----------------------------------------------------
    def _command(self, tool: str, args: list[str]) -> CommandResult:
        fault = self._fault(f"{tool} {' '.join(args[:2])}")
        if fault:
            return CommandResult(returncode=fault.get("returncode", 1),
                                 stderr=fault.get("stderr", "injected fault"),
                                 error=fault.get("error", ""))
        return self._kubectl(args) if tool == "kubectl" else self._helm(args)

    def _kubectl(self, args: list[str]) -> CommandResult:
        verb = next((a for a in args if not a.startswith("-")), "")
        rest = [a for a in args if not a.startswith("-")][1:]
        if verb == "get" and rest and rest[0].startswith("deploy"):
            return CommandResult(0, json.dumps(self._deployment_list()))
        if verb == "get" and rest and rest[0].startswith("job"):
            return CommandResult(0, json.dumps({"items": [self._job_object()]}))
        if verb == "rollout":
            target = _workload_arg(rest)
            self._restarts[target] = self._restarts.get(target, 0) + 1
            for scan in self._scans.values():
                scan.restarts += 1
                if self.world["lose_work_on_restart"]:
                    scan.lost = True
            return CommandResult(0, f"deployment.apps/{target} restarted\n")
        if verb == "scale":
            return self._scale(args, rest)
        if verb == "create":
            # backup / restore jobs are created from the chart's CronJob templates
            name = next((a.split("=")[-1] for a in args if a.startswith("--from=")), "acp-job")
            if "restore" in " ".join(args):
                self._restored = True
            return CommandResult(0, f"job.batch/{name.replace('cronjob/', '')} created\n")
        if verb in ("version", "api-resources", "describe", "logs", "get"):
            return CommandResult(0, "{}")
        return CommandResult(1, stderr=f"the fake target does not model `kubectl {verb}`")

    def _scale(self, args: list[str], rest: list[str]) -> CommandResult:
        replicas = next((int(a.split("=")[-1]) for a in args if a.startswith("--replicas=")), None)
        name = _workload_arg(rest).split("/")[-1]
        for dep, workload in WORKLOADS.items():
            if workload == name and dep in self._deps and replicas is not None:
                self._deps[dep] = replicas
                return CommandResult(0, f"deployment.apps/{name} scaled\n")
        for role in WORKER_ROLES:
            if WORKLOADS[role] == name and replicas is not None:
                previous = self._replicas[role]
                self._replicas[role] = replicas
                if replicas < previous and not self.world["drains_on_scale_down"]:
                    # Scale-down that abandons work: the in-flight scan stops progressing. PRD §11
                    # requires draining before scale-down, and nothing reports when it does not.
                    for scan in self._scans.values():
                        scan.lost = True
                return CommandResult(0, f"deployment.apps/{name} scaled\n")
        return CommandResult(1, stderr=f"no workload named {name!r} on this target")

    def _deployment_list(self) -> dict:
        items = []
        for role in WORKER_ROLES:
            items.append({
                "metadata": {"name": WORKLOADS[role],
                             "labels": {"app.kubernetes.io/part-of": "acp",
                                        "app.kubernetes.io/component": "worker",
                                        "acp.mova.io/role": role}},
                "spec": {"replicas": self._replicas[role]},
                "status": {"readyReplicas": self._replicas[role],
                           "replicas": self._replicas[role]},
            })
        items.append({
            "metadata": {"name": WORKLOADS["api"],
                         "labels": {"app.kubernetes.io/part-of": "acp",
                                    "app.kubernetes.io/component": "api"}},
            "spec": {"replicas": 2}, "status": {"readyReplicas": 2, "replicas": 2}})
        return {"items": items}

    def _job_object(self) -> dict:
        job = self.world["migrations_job"]
        return {"metadata": {"name": job["name"]},
                "status": {"succeeded": job["succeeded"], "failed": job["failed"]}}

    def _helm(self, args: list[str]) -> CommandResult:
        verb = args[0] if args else ""
        if verb == "list":
            return CommandResult(0, json.dumps([{
                "name": "acp", "revision": str(self.world["helm_revision"]),
                "app_version": self.world["healthz"]["version"], "status": "deployed"}]))
        if verb == "history":
            rev = int(self.world["helm_revision"])
            return CommandResult(0, json.dumps([
                {"revision": rev - 1, "app_version": self.world["previous_version"],
                 "status": "superseded"},
                {"revision": rev, "app_version": self.world["healthz"]["version"],
                 "status": "deployed"}]))
        if verb in ("upgrade", "rollback", "install"):
            self.world["helm_revision"] = int(self.world["helm_revision"]) + 1
            return CommandResult(0, f"Release \"acp\" has been upgraded. Happy Helming!\n")
        if verb in ("get", "status", "version", "template"):
            return CommandResult(0, "{}")
        return CommandResult(1, stderr=f"the fake target does not model `helm {verb}`")

    # -- fixtures -----------------------------------------------------------
    def _read_fixture(self, repo_relative: str) -> bytes:
        """Deterministic synthetic bytes, NOT the real file.

        The fake deliberately does not read the repository: a self-test that opened
        demo-fixtures/*.docx would pass or fail on whether those files happen to be checked out,
        which has nothing to do with the suite's logic. That the paths are real is asserted
        separately in tests/test_packaging_acceptance.py, where a missing fixture is a repository
        problem and should be reported as one.
        """
        return f"synthetic:{repo_relative}".encode("utf-8")

    def restored(self) -> bool:
        return self._restored


def _workload_arg(rest: list[str]) -> str:
    """The `deployment/<name>` argument, wherever it sits among the others.

    NOT `rest[-1]`, which is what this looked like at first and was wrong in a way that still
    reported success: `kubectl scale deployment/acp-worker-assess --replicas=4 -n acp` leaves the
    NAMESPACE as the last non-flag argument, so the fake scaled a workload called `acp` — found
    nothing, said so, and the scenario reported `unknown` for a target that had answered
    perfectly. A fake that mis-parses its own command line invents findings about the suite.
    """
    for item in rest:
        if "/" in item:
            return item
    return rest[0] if rest else ""


# ── routing ───────────────────────────────────────────────────────────────────
#
# Templates, not regexes at the call site: the route string is the key `faults` uses, so a test
# breaking "GET /readyz" names the same thing the fake matched.
_ROUTES: list[tuple[str, str]] = [
    ("GET /healthz", r"^/healthz$"),
    ("GET /readyz", r"^/readyz$"),
    ("GET /control/workers/capacity", r"^/control/workers/capacity$"),
    ("POST /scans", r"^/scans$"),
    ("GET /scans/{sid}/status", r"^/scans/(?P<sid>[^/]+)/status$"),
    ("GET /scans/{sid}/events", r"^/scans/(?P<sid>[^/]+)/events$"),
    ("POST /scans/{sid}/assess", r"^/scans/(?P<sid>[^/]+)/assess$"),
    ("POST /scans/{sid}/remediate", r"^/scans/(?P<sid>[^/]+)/remediate$"),
    ("GET /scans/{sid}/artifacts", r"^/scans/(?P<sid>[^/]+)/artifacts$"),
    ("GET /scans/jobs/{jid}", r"^/scans/jobs/(?P<jid>[^/]+)$"),
    ("GET /admin/audit-events", r"^/admin/audit-events(\?.*)?$"),
    ("GET /admin/support-bundle", r"^/admin/support-bundle(\?.*)?$"),
]

_HANDLER_SLUG = {
    "GET /healthz": "healthz",
    "GET /readyz": "readyz",
    "GET /control/workers/capacity": "control_workers_capacity",
    "POST /scans": "scans",
    "GET /scans/{sid}/status": "scans_status",
    "GET /scans/{sid}/events": "scans_events",
    "POST /scans/{sid}/assess": "scans_assess",
    "POST /scans/{sid}/remediate": "scans_remediate",
    "GET /scans/{sid}/artifacts": "scans_artifacts",
    "GET /scans/jobs/{jid}": "scans_jobs",
    "GET /admin/audit-events": "admin_audit_events",
    "GET /admin/support-bundle": "admin_support_bundle",
}


def _slug(route: str) -> str:
    return _HANDLER_SLUG[route]


def _match(method: str, path: str) -> tuple[str | None, dict[str, str]]:
    for route, pattern in _ROUTES:
        if not route.startswith(method + " "):
            continue
        m = re.match(pattern, path)
        if m:
            return route, {k: v for k, v in (m.groupdict() or {}).items() if v}
    return None, {}
