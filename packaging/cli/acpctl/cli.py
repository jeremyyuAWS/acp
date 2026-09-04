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
from typing import Sequence

from . import __version__, spec as spec_mod
from .inventory import inventory_as_dict
from .plan import render as render_plan
from .values import render_values_yaml

# PRD S10's full command list. Unimplemented commands are REJECTED with a message naming the
# phase they belong to, never accepted-and-ignored.
NOT_YET_IMPLEMENTED = {
    "init": "guided configuration (PRD S10) — phase 2",
    "install": "provisioning — phase 3+, deliberately out of the first slice (PRD S23.6)",
    "status": "reads a live installation — phase 2",
    "doctor": "reads a live installation — phase 2",
    "upgrade": "phase 5",
    "rollback": "phase 5",
    "backup": "phase 5",
    "restore": "phase 5",
    "uninstall": "phase 5",
    "support-bundle": "phase 5",
}


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acpctl", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Not yet implemented: " + ", ".join(sorted(NOT_YET_IMPLEMENTED)))
    parser.add_argument("--version", action="version", version=f"acpctl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

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
