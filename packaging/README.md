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
python -m acpctl doctor    packaging/examples/standard-production.acp-deployment.yaml
```

`validate` exits 0 on success and 1 on any error; warnings are printed and never fail. The
remaining commands from the PRD's command list exit 2 and name the phase they belong to, rather
than accepting arguments and doing nothing.

## `doctor` — can this cluster run it?

The only command that leaves the machine. It reads a live cluster through `kubectl`, so it
inherits your kubeconfig, context and credentials, and it **changes nothing**: an allow-list
refuses any kubectl verb that is not `version`, `api-resources` or `get`, and that refusal is
tested against a dozen mutating verbs. Phase 0 kept the read-only promise by patching `open` in a
test, which cannot see a subprocess — this is the replacement, not an addition to it.

```bash
python -m acpctl doctor packaging/examples/standard-production.acp-deployment.yaml -n acp-prod
python -m acpctl doctor <spec> --context staging --json
```

| Exit | Meaning |
|---|---|
| 0 | no blockers (warnings may still be printed, and are worth reading) |
| 1 | a blocker, **or** a blocking check that could not be run |
| 2 | the cluster could not be reached, so nothing was established — retryable |

### It exists for two silent failures

Most misconfigurations announce themselves. These two do not, and the chart renders both:

- **A `ScaledObject` with no KEDA** is an object nothing reconciles. No error, no event, no
  status. The worker tiers sit at their floor while the queue grows, and it looks like ACP being
  slow.
- **A `NetworkPolicy` under a CNI that does not implement them** is accepted by the API server and
  enforces nothing. A regulated install can pass review with completely open pod networking.

Everything else `doctor` checks is ordinary preflight. Those two are why there is a command.

### Three outcomes, not two

`pass`, `fail`, and **`unknown`** — and the third is what keeps the report honest. A check that
could not run has established nothing, so folding it into "pass" because nothing went wrong is how
a report comes to mean the opposite of what it says. An `unknown` on a check guarding a silent
failure counts as a blocker.

`doctor` cannot prove NetworkPolicy enforcement — no API reports it — so it infers from the CNI
and says so in the finding rather than implying certainty. It does not connect to Postgres, Redis
or object storage either; that would mean shipping credentials to a laptop. The connection-budget
rule in `spec.py` is the static half of that question.

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
