# ACP packaging

One application package, deployed consistently to Kubernetes — on AKS, EKS, GKE or a customer's
own cluster — with Docker Compose as the evaluation option. See
[ADR 0048](../docs/adr/0048-portable-deployment-packaging.md) for the architecture and the
decisions behind it, and [`docs/service-inventory.md`](docs/service-inventory.md) for what an
installation actually consists of at each profile.

**This release is read-only.** It defines the contract and the tools that read it. It provisions
nothing, and it does not touch the existing Azure Container Apps deployment in `deploy/public/`
or the Compose stack in `deploy/compose/` — those keep working exactly as they do today and are
not retired until a replacement demonstrates parity.

## Layout

```
packaging/
  schema/acp-deployment.schema.json   the published contract
  cli/acpctl/                         validate · plan · inventory · values
  examples/                           one document per deployment profile
  docs/service-inventory.md           GENERATED — scripts/gen_service_inventory.py
```

## Using it

```bash
export PYTHONPATH=packaging/cli

python -m acpctl validate  packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl plan      packaging/examples/standard-production.acp-deployment.yaml
python -m acpctl inventory packaging/examples/regulated.acp-deployment.yaml --json
python -m acpctl values    packaging/examples/regulated.acp-deployment.yaml
```

`validate` exits 0 on success and 1 on any error; warnings are printed and never fail. The other
eight commands from the PRD's command list exit 2 and name the phase they belong to, rather than
accepting arguments and doing nothing.

## The four profiles

| Profile | Platform | Data services | Notable requirements |
|---|---|---|---|
| `evaluation` | `compose` only | embedded | single machine, no HA |
| `standard` | any Kubernetes | managed or self-hosted | ≥2 API replicas, ≥7-day backups |
| `regulated` | any Kubernetes | managed or self-hosted | local-only AI, local telemetry, customer-managed keys, ≥30-day backups |
| `high-availability` | any Kubernetes | HA required | ≥2 replicas per critical tier, PDBs |

A profile's name is enforced, not decorative: `regulated` with external AI, or
`high-availability` without HA Postgres, is a validation error.

## Adding a rule

Semantic rules live in `cli/acpctl/spec.py` and policy tables in `cli/acpctl/presets.py`. Every
rule needs a test in `tests/test_packaging_validate.py` that **makes it fire** — take a valid
example, break exactly one thing, assert the rule id. A rule with no failing case is a claim, not
a check.

Changing the contract or an example means regenerating the inventory:

```bash
python scripts/gen_service_inventory.py           # rewrite
python scripts/gen_service_inventory.py --check   # what CI runs
```
