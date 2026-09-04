"""acpctl entry point. Read-only in this release: nothing here provisions, mutates or contacts.

    python -m acpctl validate  packaging/examples/standard-production.acp-deployment.yaml
    python -m acpctl plan      <spec>
    python -m acpctl inventory <spec> [--json]
    python -m acpctl values    <spec>

Exit codes: 0 valid, 1 invalid (or plan refused), 2 usage error. `validate` exits 1 on errors
only — warnings are printed and do not fail, because a check that fails on a legitimate choice
gets ignored.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__, spec as spec_mod
from .inventory import inventory_as_dict
from .plan import render as render_plan
from .values import build_values, render_values_yaml

# PRD S10's full command list. Unimplemented commands are REJECTED with a message naming the
# phase they belong to, never accepted-and-ignored.
NOT_YET_IMPLEMENTED = {
    "install": "provisioning — phase 3+, deliberately out of the first slice (PRD S23.6)",
    "upgrade": "phase 5",
    "rollback": "phase 5",
    "backup": "phase 5",
    "restore": "phase 5",
    "uninstall": "phase 5",
    "support-bundle": "phase 5",
}


# The release `init` writes when none is given. A single place, so the default cannot disagree
# between the CLI's help text and the generated document.
DEFAULT_RELEASE = "2026.9"


def init_profiles():
    from .init_doc import PROFILES
    return PROFILES


def init_platforms():
    from .init_doc import PLATFORMS
    return PLATFORMS


def _print_findings(kind: str, findings: Sequence, stream) -> None:
    if not findings:
        return
    print(f"\n{kind} ({len(findings)}):", file=stream)
    for f in findings:
        print(f"  {f.render()}", file=stream)


def _load_and_validate(path: str) -> tuple[dict | None, spec_mod.Result]:
    document = spec_mod.load_document(path)
    result = spec_mod.validate(document)
    return document, result


def cmd_init(args) -> int:
    """Generate a deployment document that is valid the moment it is written.

    STDOUT BY DEFAULT, AND THAT IS THE READ-ONLY BOUNDARY RATHER THAN AN EXCEPTION TO IT. Every
    other acpctl command writes nothing at all, and tests/test_packaging_cli.py enforces that by
    patching `open`. `init` is the first command with any reason to produce a file — so it
    produces TEXT, and writing is opt-in with `-o`. `acpctl init > acp.yaml` is the ordinary use,
    and the read-only test covers `init` without `-o` alongside the rest.

    With `-o` it REFUSES TO OVERWRITE. The one file this tool can write is the record of a
    deployment, quite possibly one already installed and edited; silently replacing it would
    destroy the only description of a running system. There is deliberately no --force: removing
    the file yourself is one command, and it is a decision worth making explicitly.

    The generated document is validated BEFORE it is emitted. A generator whose output its own
    validator rejects is worse than no generator, so that cannot reach the operator even if the
    defaults are wrong.
    """
    from . import init_doc

    try:
        document = init_doc.build(
            profile=args.profile, platform=args.platform, name=args.name,
            environment=args.environment, release=args.release, region=args.region,
            public_url=args.public_url, registry=args.registry)
    except init_doc.InitError as exc:
        print(f"acpctl init: {exc}", file=sys.stderr)
        return 1

    # The generator's promise, checked rather than asserted. If the defaults ever stop satisfying
    # the contract, the failure surfaces here — naming the rules — instead of in the operator's
    # first `validate`.
    result = spec_mod.validate(document)
    if not result.ok:
        _print_findings("Errors", result.errors, sys.stderr)
        print("\nacpctl init generated a document that does not satisfy the contract. This is a "
              "bug in acpctl, not in your arguments — please report it with the flags you used.",
              file=sys.stderr)
        return 1

    text = init_doc.render(document, path_hint=args.output or "<spec>")

    if not args.output:
        print(text, end="")
        _print_findings("Warnings", result.warnings, sys.stderr)
        return 0

    target = Path(args.output)
    if target.exists():
        print(f"acpctl init: {target} already exists — refusing to overwrite it.\n"
              "That file is the record of a deployment and may describe something already "
              "installed. Move it aside, or write to a different path.", file=sys.stderr)
        return 1
    try:
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"acpctl init: could not write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {target}", file=sys.stderr)
    _print_findings("Warnings", result.warnings, sys.stderr)
    print(f"\nNext: python -m acpctl validate {target}", file=sys.stderr)
    return 0


def cmd_validate(args) -> int:
    _, result = _load_and_validate(args.spec)
    _print_findings("Errors", result.errors, sys.stderr)
    _print_findings("Warnings", result.warnings, sys.stdout)
    if result.ok:
        print(f"\n{args.spec}: valid ({len(result.warnings)} warning(s))")
        return 0
    print(f"\n{args.spec}: INVALID — {len(result.errors)} error(s)", file=sys.stderr)
    return 1


def cmd_plan(args) -> int:
    document, result = _load_and_validate(args.spec)
    if not result.ok:
        # A plan built from an invalid spec is a plan for something that will not deploy.
        _print_findings("Errors", result.errors, sys.stderr)
        print(f"\nrefusing to plan: {args.spec} is invalid", file=sys.stderr)
        return 1
    print(render_plan(document, result.warnings))
    return 0


def cmd_inventory(args) -> int:
    document, result = _load_and_validate(args.spec)
    if not result.ok:
        _print_findings("Errors", result.errors, sys.stderr)
        print(f"\nrefusing to build an inventory: {args.spec} is invalid", file=sys.stderr)
        return 1
    data = inventory_as_dict(document)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=False))
        return 0
    print(f"{data['release']}  profile={data['profile']}  platform={data['platform']} "
          f"[{data['supportStatus']}]")
    for service in data["services"]:
        replicas = service.get("replicas")
        scale = f"{replicas['min']}-{replicas['max']}" if replicas else "-"
        print(f"  {service['name']:<24} {service['kind']:<11} {service['provisioning']:<11} "
              f"ingress={service['ingress']:<9} replicas={scale}")
    budget = data["connectionBudget"]
    print(f"\n  postgres connections worst case: {budget['worstCaseConnections']}/"
          f"{budget['serverMaxConnections']}")
    return 0


def cmd_values(args) -> int:
    document, result = _load_and_validate(args.spec)
    if not result.ok:
        _print_findings("Errors", result.errors, sys.stderr)
        print(f"\nrefusing to render values: {args.spec} is invalid", file=sys.stderr)
        return 1
    print(render_values_yaml(document))
    return 0


def cmd_doctor(args) -> int:
    """Can this cluster run what the document describes?

    EXIT CODES ARE THE SCRIPTABLE PART, so they are chosen for what a pipeline should do:

        0  no blockers. Warnings may still be printed and are worth reading.
        1  at least one blocker, OR a blocking check that could not be run. The second is not a
           softer case than the first: the checks that cannot run are the ones whose failures are
           silent, so "we could not tell whether KEDA is installed" must not exit 0 next to
           "KEDA is installed".
        2  the cluster could not be reached at all, so NOTHING was established. Distinct from 1
           because a pipeline should retry this and must not retry a real blocker.
    """
    from . import cluster as cluster_mod
    from . import doctor as doctor_mod

    document, result = _load_and_validate(args.spec)
    if not result.ok:
        _print_findings("Errors", result.errors, sys.stderr)
        print(f"\nrefusing to diagnose: {args.spec} is invalid", file=sys.stderr)
        return 1

    values = build_values(document)
    namespace = args.namespace or (document.get("metadata") or {}).get("name") or "acp"
    facts = cluster_mod.gather(namespace=namespace, context=args.context)
    report = doctor_mod.diagnose(values, facts, namespace=namespace)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_doctor(report, spec=args.spec)

    if not report["reachable"]:
        return 2
    return 0 if report["ok"] else 1


def cmd_status(args) -> int:
    """Is the running installation healthy, and is it still what the document describes?

    EXIT CODES, chosen for what a pipeline should do:

        0  installed, healthy, and matching the document
        1  installed but degraded or drifted, OR a blocking check that could not run, OR nothing
           is installed here at all — the last is a definite answer to a question the operator
           asked, not an absence of one
        2  the cluster could not be reached, so nothing was established. Retryable; 1 is not.
    """
    from . import cluster as cluster_mod
    from . import installation as installation_mod
    from . import status as status_mod

    document, result = _load_and_validate(args.spec)
    if not result.ok:
        _print_findings("Errors", result.errors, sys.stderr)
        print(f"\nrefusing to read status: {args.spec} is invalid", file=sys.stderr)
        return 1

    values = build_values(document)
    namespace = args.namespace or (document.get("metadata") or {}).get("name") or "acp"

    # Reachability is established by the same probe doctor uses, so the two commands agree about
    # what "the cluster is not there" means — and so status does not report an empty installation
    # for a cluster it simply could not contact.
    probe = cluster_mod.gather(namespace=namespace, context=args.context)
    if not probe.reachable:
        report = status_mod.report({}, installation_mod.InstallationFacts(), namespace=namespace,
                                   reachable=False, unreachable_reason=probe.unreachable_reason)
    else:
        facts = installation_mod.gather(namespace=namespace, context=args.context)
        report = status_mod.report(values, facts, namespace=namespace)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_status(report, spec=args.spec)

    if not report["reachable"]:
        return 2
    return 0 if report["ok"] else 1


def _print_status(report: dict, *, spec: str) -> None:
    print(f"acpctl status — {spec}")
    print(f"namespace: {report['namespace']}")
    print()
    for check in report["checks"]:
        from .doctor import Check
        print(Check(**check).render())
    print()
    if not report["reachable"]:
        print("NOTHING WAS CHECKED — the cluster could not be reached. This is not a healthy "
              "installation; it is no information at all.")
        return
    print(f"{report['blockers']} blocker(s), {report['warnings']} warning(s), "
          f"{report['unknown']} could not be determined")
    if report["drifted"]:
        print("DRIFT: what is running is not what this document describes. The document is meant "
              "to be the record of what was installed, and the next change will be based on it.")
    if report["ok"] and not report["drifted"]:
        print("Healthy, and matching the document.")


def _print_doctor(report: dict, *, spec: str) -> None:
    print(f"acpctl doctor — {spec}")
    if report["reachable"]:
        print(f"cluster: Kubernetes {report.get('kubernetes', '?')}  "
              f"namespace: {report['namespace']}")
    print()
    for check in report["checks"]:
        from .doctor import Check
        print(Check(**check).render())
    print()
    if not report["reachable"]:
        print("NOTHING WAS CHECKED — the cluster could not be reached. This is not a pass.")
        return
    summary = (f"{report['blockers']} blocker(s), {report['warnings']} warning(s), "
               f"{report['unknown']} could not be determined")
    print(summary)
    if report["ok"]:
        print("No blockers. Read the warnings before installing.")
    else:
        print("Do not install until the blockers are cleared. A check that could not run counts "
              "as a blocker when what it guards fails silently.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acpctl", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Not yet implemented: " + ", ".join(sorted(NOT_YET_IMPLEMENTED)))
    parser.add_argument("--version", action="version", version=f"acpctl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "init", help="generate a valid deployment document (prints to stdout unless -o is given)")
    p.add_argument("--profile", default="standard", choices=sorted(init_profiles()))
    p.add_argument("--platform", default="kubernetes", choices=sorted(init_platforms()))
    p.add_argument("--name", default="acp", help="deployment name (default: acp)")
    p.add_argument("--environment", default="production")
    p.add_argument("--release", default=DEFAULT_RELEASE, help="ACP version to deploy")
    p.add_argument("--region", default=None)
    p.add_argument("--public-url", default=None, help="the hostname ACP will be served on")
    p.add_argument("--registry", default=None, help="image registry to pull from")
    p.add_argument("-o", "--output", default=None,
                   help="write to this path instead of stdout; refuses to overwrite")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("validate", help="check a deployment document against the contract")
    p.add_argument("spec")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("plan", help="render the reviewable deployment plan (creates nothing)")
    p.add_argument("spec")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("inventory", help="the normalized service inventory for a document")
    p.add_argument("spec")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser(
        "values", help="render Helm values for the shared ACP release (writes nothing)")
    p.add_argument("spec")
    p.set_defaults(func=cmd_values)

    p = sub.add_parser(
        "doctor", help="check a live cluster can run this document (reads only, changes nothing)")
    p.add_argument("spec")
    p.add_argument("--namespace", "-n", default=None,
                   help="namespace to check (default: the document's metadata.name)")
    p.add_argument("--context", default=None, help="kubeconfig context to use")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser(
        "status", help="health and drift of a running installation (reads only, changes nothing)")
    p.add_argument("spec")
    p.add_argument("--namespace", "-n", default=None,
                   help="namespace to read (default: the document's metadata.name)")
    p.add_argument("--context", default=None, help="kubeconfig context to use")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_status)

    for name, why in sorted(NOT_YET_IMPLEMENTED.items()):
        p = sub.add_parser(name, help=f"not yet implemented — {why}")
        p.add_argument("spec", nargs="?")
        p.set_defaults(func=_unimplemented, command_name=name, reason=why)
    return parser


def _unimplemented(args) -> int:
    print(f"acpctl {args.command_name}: not implemented in this release — {args.reason}",
          file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
