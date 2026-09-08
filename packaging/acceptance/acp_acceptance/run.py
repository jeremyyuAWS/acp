"""`python -m acp_acceptance.run` — one command, one report.

    export PYTHONPATH=packaging/acceptance

    python -m acp_acceptance.run --self-test --out /tmp/self-test.json
    python -m acp_acceptance.run --target aks-certification.yaml --out report.json
    python -m acp_acceptance.run --target aks-certification.yaml --claim supported --out report.json
    python -m acp_acceptance.run --list

EXIT CODES, and the distinction between 1 and 2 is the point:

    0   every scenario mandatory for the requested claim passed
    1   MANDATORY FAILURE — a mandatory scenario ran and the target failed it. Somebody must fix
        the target (or the suite is right and the target is not eligible).
    2   COULD NOT RUN — no mandatory scenario failed, but not all of them passed: they skipped for
        want of a capability, or reported unknown. Nothing was established, and this is the
        retryable one. Same meaning `acpctl doctor` gives its exit 2.
    3   usage error, an unreadable descriptor, or a report that does not satisfy its own schema.

`--self-test` exits 0 when the ten scenarios pass, and that 0 means THE SUITE WORKS — never that
a target is eligible. A synthetic run's report forces both eligibility booleans false whatever the
scenarios did; see report.support_claim.

Collapsing 1 and 2 into "non-zero" would make a CI gate treat "your cluster loses work when a
worker restarts" and "you did not grant fault injection" as the same event, and the second is not
a defect in anything.

THE REPORT IS ALWAYS VALIDATED against packaging/acceptance/report.schema.json before it is
written. A report is consumed by other workstreams; emitting one that does not satisfy the
published contract is a suite bug, and it exits 3 rather than being written and discovered later.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import SUITE_VERSION
from .backend import ExecutionBackend, SubprocessBackend
from .context import ArtifactSink
from .fake_target import FakeBackend
from .report import PASS, FAIL, dump, validate_report
from .runner import run_suite
from .scenarios import REGISTRY, mandatory_for
from .target import CAPABILITIES, Release, Target, TargetError, load_target

EXIT_OK, EXIT_MANDATORY_FAILURE, EXIT_COULD_NOT_RUN, EXIT_USAGE = 0, 1, 2, 3

# The synthetic target `--self-test` runs against. It grants everything, so all ten scenarios
# execute — the point of the mode is to exercise the WHOLE suite and the report format, including
# the destructive scenarios that no real target can be asked to host casually.
#
# ITS NAME AND DISTRIBUTION SAY WHAT IT IS — and that is the WEAKEST of the three markers, which
# is why there are three. A self-test report is a valid ACPAcceptanceReport, and a reader scanning
# `supportClaim` would never see a target name; the first draft of this file emitted
# `mvpEligible: true` from a run that measured nothing. So the report also carries
# `synthetic: true` at the top level (required by the schema), and support_claim forces both
# eligibility booleans false while it is set. The scenario states stay `pass`, because they did
# pass and exercising them is the entire point: a self-test that produced a deliberately-failing
# report would not exercise the format at all.
SELF_TEST_TARGET = Target(
    name="self-test",
    platform="kubernetes",
    distribution="fake-backend",
    kubernetes_version="1.29.4",
    namespace="acp-self-test",
    base_url="http://fake.invalid",
    release=Release(
        version="2026.9.8.1", revision=3, pinned=True,
        components={name: {"repository": f"registry.invalid/{name}",
                           "digest": "sha256:" + "0" * 64}
                    for name in ("acp-web-api", "acp-discovery-worker", "acp-assess-worker",
                                 "acp-remediate-worker", "acp-migrations", "acp-preflight")},
        previous_version="2026.8.30.2"),
    capabilities=frozenset(CAPABILITIES),
)


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, and 2 means "could not run" here.

    A CI gate that retries on 2 would loop forever on a misspelled flag. Overriding `error` is
    the whole fix, and it is worth the four lines: exit codes are the only thing an automated
    caller reads.
    """

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m acp_acceptance.run",
                description="Run the ACP portable acceptance suite and write a structured report.")
    p.add_argument("--target", help="path to an ACPAcceptanceTarget descriptor (YAML)")
    p.add_argument("--out", help="where to write the report; '-' for stdout")
    p.add_argument("--claim", choices=("mvp", "supported"), default="mvp",
                   help="which claim's mandatory scenarios gate the exit code (default: mvp)")
    p.add_argument("--scenario", action="append", metavar="ID",
                   help="run only this scenario (repeatable). The report still measures the full "
                        "mandatory lists, so a subset can never look eligible.")
    p.add_argument("--self-test", action="store_true",
                   help="run the whole suite against the built-in fake target: no cluster, no "
                        "network, no kubectl, no helm")
    p.add_argument("--list", action="store_true", help="list the scenarios and exit")
    p.add_argument("--quiet", action="store_true", help="suppress the human-readable summary")
    return p


def _print_registry() -> None:
    print(f"acp acceptance suite {SUITE_VERSION} — {len(REGISTRY)} scenarios\n")
    for scn in REGISTRY.values():
        gate = "mandatory for MVP" if scn.claim == "mvp" else "mandatory for `supported`"
        needs = ", ".join(sorted(scn.requires)) or "nothing"
        print(f"  {scn.id}\n      {scn.title}\n      {gate}; needs: {needs}\n      {scn.proves}")


def _render(report: dict) -> str:
    mark = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP", "unknown": "????"}
    lines = []
    if report.get("synthetic", True):
        # SAID FIRST, AND SAID ON THE TERMINAL. The report file carries `synthetic: true` and a
        # supportClaim that refuses both claims, but a run is usually read as ten green lines in a
        # scrollback and remembered an hour later. "mvpEligible: true" glimpsed there is how a
        # simulation becomes a status update.
        lines += ["SYNTHETIC RUN — the fake backend, not a cluster. This exercises the suite and "
                  "the report format; it is not acceptance evidence for any target.", ""]
    lines += [f"target: {report['target']['name']} "
             f"({report['target']['platform']}/{report['target']['distribution'] or 'n/a'}), "
             f"release {report['release']['version'] or 'unknown'}"
              f"{'' if report['release']['pinned'] else ' (NOT pinned by digest)'}", ""]
    for entry in report["scenarios"]:
        lines.append(f"  [{mark[entry['state']]}] {entry['id']}: {entry['detail']}")
    s = report["summary"]
    lines += ["", f"  {s['pass']} pass · {s['fail']} fail · {s['skip']} skip · "
                  f"{s['unknown']} unknown"]
    claim = report["supportClaim"]
    lines += [f"  mvpEligible: {str(claim['mvpEligible']).lower()} · "
              f"supportedEligible: {str(claim['supportedEligible']).lower()}",
              f"  {claim['reason']}"]
    return "\n".join(lines)


def _exit_code(report: dict, claim: str) -> int:
    """0 / 1 / 2, from the states of the requested claim's mandatory scenarios."""
    mandatory = list(report["suite"]["mandatoryForMvp"])
    if claim == "supported":
        mandatory += list(report["suite"]["mandatoryForSupported"])
    by_id = {s["id"]: s["state"] for s in report["scenarios"]}
    if all(by_id.get(sid) == PASS for sid in mandatory) and mandatory:
        return EXIT_OK
    if any(by_id.get(sid) == FAIL for sid in mandatory):
        return EXIT_MANDATORY_FAILURE
    return EXIT_COULD_NOT_RUN


def _backend_for(target: Target, *, self_test: bool) -> ExecutionBackend:
    if self_test:
        return FakeBackend(grants=frozenset(target.capabilities))
    headers = {}
    token = target.credentials.get("bearerToken", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for name, header in (("monitorKey", "X-Monitor-Key"), ("e2eKey", "X-E2E-Key")):
        if target.credentials.get(name):
            headers[header] = target.credentials[name]
    return SubprocessBackend(
        base_url=target.base_url, context=target.kubeconfig_context,
        namespace=target.namespace, headers=headers,
        grants=frozenset(target.capabilities))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        _print_registry()
        return EXIT_OK

    if args.self_test and args.target:
        print("error: --self-test runs against the built-in fake target; passing --target as well "
              "would produce a report that names a real cluster and measured none of it.",
              file=sys.stderr)
        return EXIT_USAGE
    if not args.self_test and not args.target:
        print("error: pass --target <descriptor.yaml>, or --self-test to exercise the suite "
              "against the fake target.", file=sys.stderr)
        return EXIT_USAGE

    if args.self_test:
        target = SELF_TEST_TARGET
    else:
        try:
            target = load_target(args.target)
        except (TargetError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    unknown = [sid for sid in (args.scenario or []) if sid not in REGISTRY]
    if unknown:
        print(f"error: no such scenario(s): {', '.join(unknown)}. Known: "
              f"{', '.join(REGISTRY)}", file=sys.stderr)
        return EXIT_USAGE

    out_path = None if args.out in (None, "-") else Path(args.out)
    sink = ArtifactSink(directory=out_path.parent if out_path else None)

    run = run_suite(target=target, backend=_backend_for(target, self_test=args.self_test),
                    artifacts=sink, scenario_ids=args.scenario)

    errors = validate_report(run.report)
    if errors:
        print("error: the suite produced a report that does not satisfy its own schema — that is "
              "a bug in the suite, and the report was not written:", file=sys.stderr)
        for path, message in errors[:10]:
            print(f"  {path or '(root)'}: {message}", file=sys.stderr)
        return EXIT_USAGE

    text = dump(run.report)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    elif args.out == "-":
        sys.stdout.write(text)

    if not args.quiet:
        print(_render(run.report), file=sys.stderr if args.out == "-" else sys.stdout)
        if out_path is not None:
            print(f"\nreport: {out_path}", file=sys.stdout)
    return _exit_code(run.report, args.claim)


if __name__ == "__main__":
    raise SystemExit(main())
