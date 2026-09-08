# The portable acceptance suite

One command, one report, one rule:

> **A target is eligible for a claim only when every scenario mandatory for that claim has
> `state: "pass"`.** A `skip` is not a pass. An `unknown` is not a pass.

```bash
export PYTHONPATH=packaging/acceptance

python -m acp_acceptance.run --self-test --out /tmp/self-test.json
python -m acp_acceptance.run --target packaging/acceptance/example-target.yaml --out report.json
python -m acp_acceptance.run --target <descriptor> --claim supported --out report.json
python -m acp_acceptance.run --list
```

**No target has passed this suite. Every platform in
[`presets.SUPPORT_STATUS`](../cli/acpctl/presets.py) other than `compose` remains `planned`, and
nothing in this directory changes that.** What exists here is the suite and its report format,
exercised end to end against a fake target and against no real deployment. A `supported` claim is
made by attaching a report — produced by this suite, naming a real cluster and a digest-pinned
release, with `supportedEligible: true` — not by having written the suite that would produce one.

## Why the report is the product

`--self-test` prints ten green lines, and green lines are not the deliverable. Every run writes an
**`ACPAcceptanceReport`** ([`report.schema.json`](report.schema.json)) naming the target, the
release and its digests, every scenario with its state, timing and evidence, and the eligibility
decision with the reason it was reached. That file is what other workstreams consume — the
certification matrix is meant to be generated from a directory of them — and it is what somebody
reads six months later when they need to know what "supported on EKS" was actually measured on.

## The four states

| State | Means | Counts as a pass |
|---|---|---|
| `pass` | the scenario ran and the target did the right thing | yes |
| `fail` | the scenario ran and the target did not | no |
| `skip` | the **target** cannot host this scenario — a capability was not granted | **no** |
| `unknown` | the **suite** could not establish an answer — a probe errored, a surface is absent, a timeout | **no** |

`acpctl doctor` established the reasoning ([its three outcomes](../cli/acpctl/doctor.py)): a check
that could not run has established nothing, and folding it into "pass" because nothing went wrong
is how a report comes to mean the opposite of what it says. The suite adds a fourth state because,
unlike a preflight check, it can legitimately be pointed at a target that was never meant to host
half of it — and "we did not try" and "we tried and could not tell" send a reader to different
places.

**A run in which everything skipped reports `mvpEligible: false`, with a reason naming the skipped
ids.** That is the failure this format exists to prevent, and it is the easiest one to ship by
accident: a green report produced by a suite that did nothing looks exactly like a real pass.

## The ten scenarios

Ids are stable; the suite is registry-driven, so they are also the `--scenario` arguments.

### Mandatory for a Kubernetes MVP claim

| Id | What it proves |
|---|---|
| `api-readiness` | `/healthz` and `/readyz` answer, and the build **names the commit it came from**. A target that cannot say what it is running turns every later line of the report into a claim about an unidentified release. |
| `worker-registration` | discover, assess and remediate have each **registered and are heartbeating** — not merely that pods are Ready. A worker with the wrong role, or one that cannot reach Redis, is Ready by every Kubernetes measure and processes nothing. |
| `queue-and-progress` | submitted work is queued, processed, and reported **live over SSE**. A proxy that buffers `text/event-stream` leaves every UI at "starting…" on an installation whose jobs all succeed. |
| `fixture-workflow` | four synthetic documents go discover → assess → remediate, and every authoritative artifact lands in **durable** storage. PRD §12: output on a worker's own disk is correct right up to the next reschedule, and then silently gone. |
| `audit-and-diagnostics` | operational events are recorded, and the diagnostics export contains **none of this run's own credentials** — checked by looking for them, not by trusting the export's `redacted: true`. |
| `worker-restart` | each of the three tiers is restarted mid-job with **no lost work and no duplicate authoritative output**. The duplicate is the dangerous half: two corrected files, both written successfully, and the user downloads whichever is listed first. |

### Additionally mandatory for a `supported` claim

| Id | What it proves |
|---|---|
| `dependency-degradation` | Redis, Postgres, object storage and the AI provider each taken away: the installation **reports not-ready rather than absorbing it**, and recovers when they return. An API answering 200 without Postgres keeps receiving traffic. |
| `scale-updown` | new replicas **register** after a scale-up, and a scale-down with work in flight **drains rather than abandoning it** (PRD §11). |
| `upgrade-from-previous` | the previous supported release upgrades to this one **by digest**, migrations run, and the installation is ready afterwards (PRD §15, §20.7). An upgrade against a mutable tag has not demonstrated the requirement whatever it does. |
| `backup-restore` | a backup is taken, **an actual restore is performed**, and a document workflow runs afterwards. PRD §16: a backup is not healthy until a restore has succeeded. |

## The target descriptor

[`example-target.yaml`](example-target.yaml) is the annotated form. Two things about it matter more
than the rest:

- **`capabilities` is a grant, not a description.** The execution backend is constructed with
  exactly that set, and a scenario reaching for an effect that was not granted raises rather than
  performing it. Five of them are destructive — they restart workers mid-job, scale tiers with work
  in flight, take Redis away, and restore a backup over the running installation. Grant them on a
  certification cluster, never on production.
- **Credentials never reach the report.** The `target` block is an allow-list of five fields, and
  the assembled report is then grepped for every credential value the descriptor carried; a run
  that would emit one **fails instead of writing the file**. Two mechanisms, because the first is
  a discipline and the second is a check — a field added next quarter that carries a token past
  the allow-list still trips the grep.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | every scenario mandatory for the requested `--claim` passed |
| 1 | **mandatory failure** — a mandatory scenario ran and the target failed it |
| 2 | **could not run** — nothing failed, but not everything passed: skips or unknowns. Retryable, and the same meaning `acpctl doctor` gives its exit 2 |
| 3 | usage error, an unreadable descriptor, or a report that does not satisfy its own schema |

1 and 2 are separate because a CI gate must not treat "your cluster loses work when a worker
restarts" and "you did not grant fault injection" as the same event.

## `--self-test`: the suite with no infrastructure

`--self-test` runs all ten scenarios against a **fake target** — a small state machine in
[`fake_target.py`](acp_acceptance/fake_target.py) where a scan progresses, a rollout restart resets
pods, and scaling a dependency to zero makes `/readyz` report it unavailable. No cluster, no
network, no `kubectl`, no `helm`. `tests/test_packaging_acceptance.py` asserts that by making
`subprocess.run` and `urllib.request.urlopen` raise for the duration of a self-test run.

This is not a demo mode. It is how the report format is exercised: a format debugged during a
certification window is a format whose bugs are found at the least affordable moment. Its report is
a valid `ACPAcceptanceReport` and it says `mvpEligible: true`, because the fake target passes — the
only thing between that file and a certification matrix is that its `target.name` is `self-test`
and its distribution is `fake-backend`.

What it does **not** prove is anything about any real target. The fake's responses are what ACP's
API and kubectl are *documented* to return, not a recording of a real deployment — the same
limitation [`tests/packaging_kubectl_fake.py`](../../tests/packaging_kubectl_fake.py) states for
its own fixtures.

## Adding a scenario

Data plus a function, and nothing else:

```python
@scenario(id="my-scenario", title="…", claim="mvp", requires=["api", "kubectl"],
          proves="the one-line claim this makes")
def my_scenario(ctx) -> Outcome:
    ...
    return Outcome.passed("what was observed", evidenceKey=value)
```

The registry order is the execution order, the mandatory lists are derived from `claim`, and the
report's `suite` block is derived from the registry — so a scenario cannot be mandatory in the code
and optional in the report.

Three rules a new scenario has to hold to:

1. **Every effect goes through `ctx.backend`.** Nothing else in the package imports `subprocess`,
   `urllib` or `time`, and a test enforces it. A scenario that shells out directly is a scenario
   that can only be exercised on a cluster.
2. **Mutations name their capability**: `ctx.backend.kubectl([...], requires="scale-control")`.
   A call whose capability was not granted raises.
3. **Give it a failing case in the tests.** `fake_target.world(...)` takes overrides and `faults`
   for exactly that. A scenario nobody has watched fail is a claim, not a check — the same rule
   [`packaging/README.md`](../README.md) states for validation rules.
