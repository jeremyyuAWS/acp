"""acpctl entry point.

    python -m acpctl validate  packaging/examples/standard-production.acp-deployment.yaml
    python -m acpctl plan      <spec>
    python -m acpctl inventory <spec> [--json]
    python -m acpctl values    <spec>
    python -m acpctl doctor    <spec> -n <namespace>
    python -m acpctl status    <spec> -n <namespace>
    python -m acpctl install   <spec> -n <namespace> --release-manifest <path> --yes
    python -m acpctl uninstall <spec> -n <namespace>

TWO OF THESE CAN CHANGE A CLUSTER, AND ONLY TWO. Everything above `install` reads or renders and
nothing else — `cluster.py` enforces that with a kubectl allow-list containing no mutating verb,
and the doctor and status tests assert the refusal. `install` and `uninstall` mutate through
`helm.py`, which has its OWN, narrower allow-list: helm plus four kubectl writes, nothing more.
The split is deliberate, so that adding an installer did not quietly retire the read-only
guarantee the other commands are built on. See packaging/docs/lifecycle.md.

Exit codes: 0 success, 1 refused/invalid/failed, 2 usage error or an unreachable cluster (which
is retryable and 1 is not). `validate` exits 1 on errors only — warnings are printed and do not
fail, because a check that fails on a legitimate choice gets ignored.
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
    "upgrade": "phase 5",
    "rollback": "phase 5",
    "backup": "phase 5",
    "restore": "phase 5",
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


def install_default_chart():
    """The shipped chart's path, for `--chart`'s default and its help text.

    Imported lazily like the two above. `install` pulls in helm.py, state.py and (through the
    preflight) cluster.py; making `acpctl validate` pay for that at import time would be a
    read-only command loading the module that holds every mutating call.
    """
    from .install import DEFAULT_CHART
    return DEFAULT_CHART


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


def cmd_adapter(args) -> int:
    """What the infrastructure adapter must provision for this document to be true.

    VALIDATES FIRST, LIKE `values` AND `inventory`, AND FOR A SHARPER REASON. The requirements are
    derived from the document's numbers — the Postgres ceiling comes from the fleet's connection
    demand, the identity grants from `secrets.workloadIdentity` — so an invalid document produces
    a requirements list that is confidently wrong about what to build. That is worse than a
    refusal: infrastructure gets created from it.
    """
    from .adapter_azure import report as azure_report

    document, result = _load_and_validate(args.spec)
    if not result.ok:
        _print_findings("Errors", result.errors, sys.stderr)
        print(f"\nrefusing to derive adapter requirements: {args.spec} is invalid", file=sys.stderr)
        return 1

    platform = document["runtime"]["platform"]
    if platform != "azure":
        print(f"acpctl adapter: only the azure adapter exists (PRD S21 phase 3); this document "
              f"declares platform '{platform}', and AWS/GCP are phase 4", file=sys.stderr)
        return 2

    rep = azure_report(document)
    if args.json:
        print(json.dumps({
            "requirements": [
                {"resource": r.resource, "setting": r.setting, "value": r.value,
                 "because": r.because, "source": r.source}
                for r in rep.requirements],
            "unowned": rep.unowned,
        }, indent=2))
        return 0

    print(f"Azure adapter requirements for {document['metadata']['name']} "
          f"({len(rep.requirements)}):\n")
    for requirement in rep.requirements:
        print(f"  {requirement.render()}")
    if rep.undecided:
        print(f"\n  UNDECIDED ({len(rep.undecided)}): a setting the adapter must choose and the "
              f"document does not state.")
    if rep.unverifiable:
        print(f"  VENDOR ({len(rep.unverifiable)}): rests on an Azure fact this repository "
              f"cannot check offline.")
    print(f"\n  Not expressed by the contract at all ({len(rep.unowned)}): "
          f"{', '.join(sorted(rep.unowned))}")
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


def _emit(outcome, args) -> int:
    """One printer for the two commands that change things.

    THE JSON GOES TO STDOUT ALONE, and the running commentary to stderr, because the state
    document is the machine-readable half and a pipeline doing `acpctl install … --json | jq`
    must not have to strip progress lines out of it. Without `--json` both go to stdout, which is
    what a person at a terminal wants.

    The reason line is printed on FAILURE to stderr and on success to stdout for the same reason
    every other command here does it: an operator redirecting stdout to a file still sees why
    something was refused.
    """
    if args.json and outcome.state is not None:
        print(json.dumps(outcome.state, indent=2, sort_keys=False))
    if outcome.code == 0:
        if outcome.reason:
            print(outcome.reason, file=sys.stderr if args.json else sys.stdout)
        return 0
    print(f"\nacpctl {args.command}: {outcome.reason}", file=sys.stderr)
    return outcome.code


def cmd_install(args) -> int:
    """Install the release this document describes, and record exactly what was installed.

    EXIT CODES, chosen for what a pipeline should do and matching doctor/status:

        0  installed and VERIFIED, or already installed and identical (a re-run is a no-op)
        1  refused, or failed, or succeeded-but-unverifiable — the last is deliberately not 0,
           because an installer that exits 0 for a result it could not observe is the failure
           this whole command set is written against
        2  a usage error, or the cluster could not be reached so nothing was established, or
           there was nobody to answer the confirmation prompt. Retryable; 1 is not.
    """
    from . import install as install_mod

    echo = (lambda line: print(line, file=sys.stderr)) if args.json else print
    outcome = install_mod.install(
        args.spec, namespace=args.namespace, release_name=args.release_name,
        release_manifest=args.release_manifest, allow_unpinned=args.allow_unpinned,
        adopt=args.adopt, skip_preflight=args.skip_preflight, assume_yes=args.yes,
        context=args.context, chart_dir=args.chart, echo=echo)
    return _emit(outcome, args)


def cmd_uninstall(args) -> int:
    """Preview — or, with --yes, perform — the removal of one installation.

    EXIT CODES:

        0  the preview was printed (nothing changed), or the removal completed
        1  refused, or the removal did not complete, or there was nothing here to remove — the
           last is a failure rather than a success, because "we removed nothing" is a different
           answer from "we removed it"
        2  a usage error (no --data-policy, no --confirm-name for a delete) or an unreachable
           cluster
    """
    from . import uninstall as uninstall_mod

    echo = (lambda line: print(line, file=sys.stderr)) if args.json else print
    outcome = uninstall_mod.uninstall(
        args.spec, namespace=args.namespace, release_name=args.release_name,
        data_policy=args.data_policy, assume_yes=args.yes, confirm_name=args.confirm_name,
        context=args.context, echo=echo)
    return _emit(outcome, args)


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
        "adapter",
        help="what the cloud adapter must provision for this document (derives only, creates "
             "nothing)")
    p.add_argument("spec")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_adapter)

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

    p = sub.add_parser(
        "install",
        help="install the release this document describes (CHANGES A CLUSTER — previews the "
             "plan and asks first)")
    p.add_argument("spec")
    # REQUIRED, WITH NO DEFAULT, unlike doctor and status which fall back to metadata.name. Those
    # two read; this one creates. A namespace defaulted from a document is one an operator did
    # not choose, and "installed into the wrong namespace" is not a mistake a read-only command
    # can make.
    p.add_argument("--namespace", "-n", required=True, help="namespace to install into")
    p.add_argument("--release-name", default=None,
                   help="helm release name (default: the document's metadata.name)")
    p.add_argument("--release-manifest", default=None,
                   help="the release's image digests, as YAML or JSON (see packaging/docs/"
                        "lifecycle.md); without it the install refuses unless --allow-unpinned")
    p.add_argument("--allow-unpinned", action="store_true",
                   help="install from tags when no digest is available — prints a warning and is "
                        "recorded in the installation state as pinned: false")
    p.add_argument("--adopt", action="store_true",
                   help="install into a namespace that already holds a different ACP installation")
    p.add_argument("--skip-preflight", action="store_true",
                   help="install without running the doctor checks first (recorded in the state)")
    p.add_argument("--yes", action="store_true",
                   help="skip the confirmation prompt; required when stdin is not a terminal")
    p.add_argument("--chart", default=str(install_default_chart()),
                   help="path to the ACP chart")
    p.add_argument("--context", default=None, help="kubeconfig context to use")
    p.add_argument("--json", action="store_true",
                   help="print the installation state as JSON on stdout")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser(
        "uninstall",
        help="remove an installation — PREVIEWS by default and changes nothing without --yes")
    p.add_argument("spec")
    p.add_argument("--namespace", "-n", required=True, help="namespace to remove from")
    p.add_argument("--release-name", default=None,
                   help="helm release name (default: the document's metadata.name)")
    p.add_argument("--yes", action="store_true", help="actually remove it; without this the "
                                                      "command previews and changes nothing")
    p.add_argument("--data-policy", default=None, choices=["retain", "delete"],
                   help="what happens to in-cluster PersistentVolumeClaims this release owns. "
                        "NO DEFAULT — required with --yes")
    p.add_argument("--confirm-name", default=None,
                   help="the release name, typed out; required by --data-policy delete")
    p.add_argument("--context", default=None, help="kubeconfig context to use")
    p.add_argument("--json", action="store_true",
                   help="print the final installation record as JSON on stdout")
    p.set_defaults(func=cmd_uninstall)

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
