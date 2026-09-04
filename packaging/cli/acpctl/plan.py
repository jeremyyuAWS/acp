"""Render the deployment plan a reviewer signs off before anything is provisioned.

PRD S10 fixes the contents: resources, images and digests, allocations, replica ranges, ingress
and egress, public endpoints, secret references, cost, destructive changes, migration
requirements and rollback implications. Every one of those has a section here, and the sections
a read-only plan cannot yet fill in SAY SO rather than being omitted — a plan with a silently
missing section reads as a plan with nothing to report.

READ-ONLY BY CONSTRUCTION. This module reaches nothing: no cloud API, no registry, no cluster. It
therefore cannot report a diff against a live installation, and it does not pretend to — the
"resources" section is stated as what a first install creates, and the destructive-change section
says plainly that a diff needs the live-state reader that lands with `acpctl install`.
"""
from __future__ import annotations

from typing import Any

from . import presets
from .inventory import build_inventory, connection_budget
from .spec import required_secret_names

_RULE = "─" * 78


def _h(title: str) -> str:
    return f"\n{title}\n{_RULE}"


def render(doc: dict[str, Any], warnings: list | None = None) -> str:
    rt = doc["runtime"]
    services = build_inventory(doc)
    out: list[str] = []

    out.append(f"ACP deployment plan — {doc['metadata']['name']} ({doc['metadata']['environment']})")
    out.append(_RULE)
    out.append(f"  release      {rt['version']}")
    out.append(f"  profile      {rt['profile']}")
    out.append(f"  platform     {rt['platform']}  [{presets.SUPPORT_STATUS[rt['platform']]}]")
    out.append(f"  region       {doc['metadata'].get('region', '(not stated)')}")
    out.append("  mode         PLAN ONLY — nothing is created, changed or contacted")

    # 1. Resources -------------------------------------------------------------
    out.append(_h("1. Resources this plan would create"))
    for s in services:
        marker = {"managed": "managed", "external": "external", "in-cluster": "create"}[s.provisioning]
        line = f"  [{marker:>8}] {s.name:<22} {s.kind}"
        if s.replicas:
            line += f"  replicas {s.replicas[0]}-{s.replicas[1]}"
        if s.resources:
            line += f"  {s.resources['cpu']} CPU / {s.resources['memory']}"
        out.append(line)
        if s.notes:
            out.append(f"{'':>13}{s.notes}")

    # 2. Images ----------------------------------------------------------------
    out.append(_h("2. Images"))
    out.append(f"  registry     {rt.get('imageRegistry', '(not stated — required at install)')}")
    imaged = [s for s in services if s.image]
    for s in imaged:
        out.append(f"  {s.image}:{s.image_version}")
        out.append(f"{'':>4}digest  <unresolved>")
    out.append("")
    out.append("  Digests are UNRESOLVED here. `acpctl plan` reaches no registry, and a plan that")
    out.append("  printed a tag as if it were a pin would defeat the reason PRD S5.1 requires")
    out.append("  digests. `acpctl install` resolves and verifies signatures before deploying.")

    # 3. Allocations -----------------------------------------------------------
    out.append(_h("3. CPU, memory and storage"))
    for s in services:
        if not s.resources:
            continue
        r = s.resources
        out.append(f"  {s.name:<22} {r['cpu']:>2} CPU  {r['memory']:>6}  "
                   f"scratch {r['ephemeralStorage']:>6}")
    capacity = doc.get("capacity", {})
    max_mb = capacity.get("maxSourceFileSizeMb", presets.DEFAULT_MAX_SOURCE_FILE_MB)
    concurrent = capacity.get("concurrentFilesPerWorker",
                              presets.DEFAULT_CONCURRENT_FILES_PER_WORKER)
    floor = presets.minimum_ephemeral_gib(max_mb, concurrent)
    out.append("")
    out.append(f"  Temporary-storage floor: {floor}Gi per worker, from {concurrent} concurrent "
               f"file(s) of up to {max_mb}MB")
    out.append(f"  (x{presets.RENDER_EXPANSION_FACTOR:g} render expansion, "
               f"x{presets.OUTPUT_FACTOR:g} output, x{presets.SAFETY_MARGIN:g} margin). Those "
               f"factors are DECLARED")
    out.append("  planning constants, not measurements — see packaging/cli/acpctl/presets.py.")
    out.append("  Worker scratch is disposable: no authoritative output may exist only there.")

    budget = connection_budget(doc)
    out.append("")
    out.append(f"  Postgres connections, worst case at max replicas: "
               f"{budget['worstCaseConnections']} of {budget['serverMaxConnections']} "
               f"({'within' if budget['withinBudget'] else 'OVER'} budget)")

    # 4. Scaling ---------------------------------------------------------------
    out.append(_h("4. Replica ranges and autoscaling"))
    for name, tier in [("api", doc["api"])] + [(n, doc["workers"][n]) for n in
                                               ("discover", "assess", "remediate")]:
        auto = tier.get("autoscale")
        signals = ", ".join(auto["signals"]) if auto else "fixed (no autoscaling declared)"
        out.append(f"  {name:<12} {tier['replicas']['min']}-{tier['replicas']['max']}   "
                   f"signal: {signals}")

    # 5. Network ---------------------------------------------------------------
    net = doc["network"]
    out.append(_h("5. Network"))
    public = [s.name for s in services if s.ingress == "public"]
    out.append(f"  public endpoints    {', '.join(public) if public else '(none)'}")
    if net["publicIngress"]:
        out.append(f"  public URL          {rt.get('publicUrl')}")
    out.append(f"  private workers     {net['privateWorkers']}")
    out.append(f"  worker ingress      {', '.join(s.name for s in services if s.ingress == 'none' and s.kind == 'service') or '(none)'} — none")
    egress = net.get("allowedEgress", [])
    out.append(f"  allowed egress      {', '.join(egress) if egress else 'deny-all'}")
    for source in doc.get("sources", []):
        out.append(f"  external data path  {source}")
    if doc["ai"]["mode"] != "local-only":
        out.append(f"  external data path  AI provider(s): "
                   f"{', '.join(doc['ai'].get('externalProviders', [])) or '(unnamed)'}")

    # 6. Secrets ---------------------------------------------------------------
    out.append(_h("6. Secret references"))
    out.append(f"  provider  {doc['secrets']['provider']}")
    for name in required_secret_names(doc):
        ref = doc["secrets"]["refs"].get(name, {})
        out.append(f"  {name:<32} -> {ref.get('name', '?')}/{ref.get('key', '?')}")
    out.append("")
    out.append("  References only. No secret value is read, resolved or printed by this command.")

    # 7. Cost ------------------------------------------------------------------
    out.append(_h("7. Estimated monthly cost"))
    out.append("  NOT AVAILABLE. No provider pricing source is wired up, and a made-up range is")
    out.append("  worse than no range — it would be quoted in a budget. PRD S3 lists cost")
    out.append("  estimation as a secondary goal; it lands with the provider adapters.")

    # 8. Destructive changes ---------------------------------------------------
    out.append(_h("8. Destructive changes"))
    out.append("  NONE DETERMINABLE. This command reads no live state, so it cannot diff against")
    out.append("  an existing installation. Treat this plan as a FIRST-INSTALL plan; upgrade")
    out.append("  diffing arrives with the live-state reader in `acpctl install`/`upgrade`.")

    # 9. Migrations ------------------------------------------------------------
    out.append(_h("9. Migrations"))
    out.append("  acp-migrations runs to completion before any application container starts.")
    out.append("  ADR 0045: every migration is additive (expand/contract, contract deferred to a")
    out.append("  later release once no old-code replica remains).")

    # 10. Rollback -------------------------------------------------------------
    out.append(_h("10. Rollback implications"))
    out.append("  Application rollback: redeploy the previous digest. Safe, because the schema is")
    out.append("  additive — old code meets a wider schema, never a narrower one.")
    out.append("  Schema rollback: NOT SUPPORTED and not needed under the additive rule. A plan")
    out.append("  that claimed reversible migrations would be claiming something ACP does not do.")
    out.append("  Mixed-version window: acp-web-api gets a weighted cutover; the worker tiers have")
    out.append("  no ingress and therefore cut over unprotected (ADR 0045 S6). A new API can")
    out.append("  enqueue to an old worker during that window.")

    if warnings:
        out.append(_h("Warnings"))
        for w in warnings:
            out.append(f"  ! {w.render()}")

    out.append("")
    return "\n".join(out)
