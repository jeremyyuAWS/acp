"""The execution backend — the one seam through which the suite touches anything.

EVERY EFFECT GOES THROUGH HERE: HTTP to the API, kubectl, helm, waiting, reading a fixture,
writing an artifact, and reading the clock. Nothing else in the package imports `subprocess`,
`urllib` or `time`, and tests/test_packaging_acceptance.py asserts that by making those explode
during a self-test run. The rule sounds fussy until you try to test scenario 6 — "restart each
worker tier mid-job and prove no work was lost" — without a cluster: with the seam, it is a
fixture; without it, it is a scenario nobody ever runs until certification day, which is the day
its bugs are least affordable.

TWO IMPLEMENTATIONS, ONE INTERFACE:

  * `SubprocessBackend` shells out to kubectl and helm and speaks HTTP with urllib. It is what a
    certification run uses.
  * `FakeBackend` answers from a described target (`fake_target.py`) and records every call. It is
    what `--self-test` and the whole test suite use, and it is why the report format can be
    exercised in CI with no cluster, no network, no helm and no kubectl present.

MUTATION IS GRANTED, NOT ASSUMED — and this is the difference between this suite and `acpctl`.
`acpctl` is read-only and enforces that with a verb allow-list (cluster.py), because a packaging
CLI that changes a customer's cluster is a different and much more dangerous tool. The acceptance
suite genuinely must restart workers, scale tiers, take dependencies away and restore backups: a
suite that only reads cannot answer the questions PRD §19 asks. So the boundary moves rather than
disappearing. The backend is CONSTRUCTED with the capabilities the target descriptor granted, and
every mutating call names the capability it needs:

    backend.kubectl(["rollout", "restart", ...], requires="workload-restart")

A call whose capability was not granted raises `NotAuthorized` — which is a programming error, not
an operating condition, because the runner should already have skipped that scenario. It is a
second lock on the same door: the first (skip on missing capability) keeps the report honest, and
this one keeps a buggy scenario from restarting pods on a target that never agreed to it.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# kubectl verbs that only read. Same list as acpctl's, and deliberately so: a read in this suite
# should be exactly as constrained as a read there.
READ_VERBS = frozenset({"version", "api-resources", "get", "describe", "logs"})

# helm subcommands that only read.
HELM_READ = frozenset({"version", "list", "status", "history", "get", "template"})


class NotAuthorized(RuntimeError):
    """A scenario asked for an effect the target descriptor did not grant.

    Never raised in a correct run: the runner skips a scenario whose capabilities are missing
    before its body executes. Raised loudly rather than degraded, because the alternative is a
    suite that quietly restarts pods on a cluster whose owner only agreed to a read-only pass.
    """


class BackendError(RuntimeError):
    """The backend itself could not perform the call — kubectl missing, DNS failure, timeout.

    Distinct from "the call returned something bad". A scenario turns this into `unknown`, never
    into `fail`: nothing about the TARGET was established by a call that did not happen.
    """


@dataclass
class HttpResponse:
    status: int
    body: str = ""
    error: str = ""          # transport failure; non-empty means `status` is meaningless

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300

    def json(self) -> Any | None:
        """The decoded body, or None when it is not JSON.

        None rather than an exception, because "the endpoint answered with an HTML error page"
        is a fact a scenario should report as `unknown`, not a traceback that loses the run.
        """
        try:
            return json.loads(self.body)
        except (ValueError, TypeError):
            return None


@dataclass
class CommandResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    error: str = ""          # the command could not be run at all

    @property
    def ok(self) -> bool:
        return not self.error and self.returncode == 0

    def json(self) -> Any | None:
        try:
            return json.loads(self.stdout)
        except (ValueError, TypeError):
            return None


class ExecutionBackend:
    """The interface. Subclasses implement `_http`, `_sse`, `_command`, `_read_fixture`.

    The public methods record the call in `self.log` first and then delegate, so the log is
    complete by construction rather than by every implementation remembering to append to it.
    """

    kind = "abstract"

    def __init__(self, *, grants: frozenset[str] = frozenset()) -> None:
        self.grants = frozenset(grants)
        self.log: list[dict[str, Any]] = []

    # -- authorisation ------------------------------------------------------
    def _authorize(self, requires: str | None, what: str) -> None:
        if requires is None:
            return
        if requires not in self.grants:
            raise NotAuthorized(
                f"{what} needs the {requires!r} capability and the target descriptor did not "
                f"grant it. The runner should have skipped this scenario; reaching here means a "
                f"scenario declared the wrong `requires` set.")

    # -- clock --------------------------------------------------------------
    def utcnow(self) -> datetime:
        raise NotImplementedError

    def monotonic(self) -> float:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        self.log.append({"kind": "sleep", "seconds": seconds})
        self._sleep(seconds)

    def _sleep(self, seconds: float) -> None:
        raise NotImplementedError

    # -- effects ------------------------------------------------------------
    def http(self, method: str, path: str, *, body: Any = None,
             requires: str | None = None) -> HttpResponse:
        self._authorize(requires, f"HTTP {method} {path}")
        self.log.append({"kind": "http", "method": method, "path": path,
                         "requires": requires})
        return self._http(method, path, body)

    def sse(self, path: str, *, max_events: int = 20, timeout: float = 30.0) -> list[dict]:
        """Read a Server-Sent Events stream until `max_events` or the timeout.

        Returns DECODED events. A transport failure raises BackendError rather than returning an
        empty list, because "the stream delivered nothing" and "we never opened the stream" lead
        to opposite conclusions about the target — the first is a failing SSE implementation and
        the second is a network problem on the machine running the suite.
        """
        self.log.append({"kind": "sse", "path": path, "max_events": max_events})
        return self._sse(path, max_events, timeout)

    def kubectl(self, args: list[str], *, requires: str | None = None) -> CommandResult:
        verb = next((a for a in args if not a.startswith("-")), None)
        if requires is None and verb not in READ_VERBS:
            raise NotAuthorized(
                f"kubectl {verb!r} changes the cluster; call it with requires=<capability> so the "
                f"target descriptor's grant is checked. Reads are {sorted(READ_VERBS)}.")
        self._authorize(requires, f"kubectl {verb}")
        self.log.append({"kind": "kubectl", "args": list(args), "requires": requires})
        return self._command("kubectl", args)

    def helm(self, args: list[str], *, requires: str | None = None) -> CommandResult:
        verb = next((a for a in args if not a.startswith("-")), None)
        if requires is None and verb not in HELM_READ:
            raise NotAuthorized(
                f"helm {verb!r} changes the release; call it with requires=<capability>.")
        self._authorize(requires, f"helm {verb}")
        self.log.append({"kind": "helm", "args": list(args), "requires": requires})
        return self._command("helm", args)

    def read_fixture(self, repo_relative: str) -> bytes:
        """One of the repository's synthetic fixtures, by repo-relative path.

        ROUTED THROUGH THE BACKEND so the fake can serve deterministic bytes without a filesystem,
        and so the set of files a certification run touches is visible in one log rather than
        spread through ten scenario bodies. PRD §13 and the suite's own rule: synthetic fixtures
        and test identities only — never a customer document.
        """
        self.log.append({"kind": "fixture", "path": repo_relative})
        return self._read_fixture(repo_relative)

    # -- to implement -------------------------------------------------------
    def _http(self, method: str, path: str, body: Any) -> HttpResponse:
        raise NotImplementedError

    def _sse(self, path: str, max_events: int, timeout: float) -> list[dict]:
        raise NotImplementedError

    def _command(self, tool: str, args: list[str]) -> CommandResult:
        raise NotImplementedError

    def _read_fixture(self, repo_relative: str) -> bytes:
        raise NotImplementedError

    # -- introspection used by the tests and the report ---------------------
    def call_kinds(self) -> set[str]:
        return {entry["kind"] for entry in self.log}


class SubprocessBackend(ExecutionBackend):
    """The real one: kubectl, helm and urllib against a live target.

    TIMEOUTS ARE NOT OPTIONAL. A certification run is unattended, and a hung kubectl turns a
    twenty-minute suite into a job somebody cancels the next morning with no report at all — which
    is strictly worse than a scenario that reports `unknown: timed out`, because the second one at
    least says what happened.
    """

    kind = "subprocess"

    def __init__(self, *, base_url: str, context: str = "", namespace: str = "",
                 headers: dict[str, str] | None = None, grants: frozenset[str] = frozenset(),
                 timeout: float = 60.0, repo_root: Path | None = None) -> None:
        super().__init__(grants=grants)
        self.base_url = base_url.rstrip("/")
        self.context = context
        self.namespace = namespace
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]

    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _http(self, method: str, path: str, body: Any) -> HttpResponse:
        if not self.base_url:
            return HttpResponse(0, error="the target descriptor has no baseUrl")
        url = f"{self.base_url}{path}"
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return HttpResponse(resp.status, resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # A 4xx/5xx is an ANSWER, not a transport failure: `/readyz` returning 503 is exactly
            # what the degradation scenario is looking for, and turning it into an error would
            # make that scenario report `unknown` for the case it exists to observe.
            return HttpResponse(exc.code, exc.read().decode("utf-8", "replace"))
        except Exception as exc:                      # noqa: BLE001 - reported, never raised
            return HttpResponse(0, error=f"{exc.__class__.__name__}: {exc}")

    def _sse(self, path: str, max_events: int, timeout: float) -> list[dict]:
        if not self.base_url:
            raise BackendError("the target descriptor has no baseUrl")
        url = f"{self.base_url}{path}"
        headers = {**self.headers, "Accept": "text/event-stream"}
        req = urllib.request.Request(url, headers=headers, method="GET")
        events: list[dict] = []
        deadline = time.monotonic() + timeout
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                current: dict[str, str] = {}
                for raw in resp:
                    line = raw.decode("utf-8", "replace").rstrip("\n")
                    if line == "":
                        if current:
                            events.append(_decode_sse(current))
                            current = {}
                        if len(events) >= max_events:
                            break
                    elif ":" in line:
                        key, _, value = line.partition(":")
                        current[key.strip()] = value.strip()
                    if time.monotonic() > deadline:
                        break
        except Exception as exc:                      # noqa: BLE001
            raise BackendError(f"{exc.__class__.__name__}: {exc}") from exc
        return events

    def _command(self, tool: str, args: list[str]) -> CommandResult:
        cmd = [tool]
        if tool == "kubectl" and self.context:
            cmd += ["--context", self.context]
        if tool == "helm" and self.context:
            cmd += ["--kube-context", self.context]
        cmd += args
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            return CommandResult(error=f"{tool} is not on PATH")
        except subprocess.TimeoutExpired:
            return CommandResult(error=f"{tool} timed out after {self.timeout}s")
        except OSError as exc:
            return CommandResult(error=f"could not run {tool}: {exc}")
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def _read_fixture(self, repo_relative: str) -> bytes:
        path = (self.repo_root / repo_relative).resolve()
        if not str(path).startswith(str(self.repo_root.resolve())):
            raise BackendError(f"fixture path escapes the repository: {repo_relative!r}")
        if not path.exists():
            raise BackendError(f"fixture {repo_relative!r} does not exist")
        return path.read_bytes()


def _decode_sse(fields: dict[str, str]) -> dict:
    """One SSE frame as a dict. `data:` is decoded as JSON when it is JSON, kept as text when not.

    Both shapes occur in this application's streams, and a scenario that assumed JSON would report
    `unknown` on a perfectly working text stream.
    """
    out: dict[str, Any] = {k: v for k, v in fields.items() if k != "data"}
    raw = fields.get("data", "")
    try:
        out["data"] = json.loads(raw)
    except (ValueError, TypeError):
        out["data"] = raw
    return out
