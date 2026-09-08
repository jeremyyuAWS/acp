"""The portable acceptance suite — one command, one report, one eligibility rule.

WHAT THIS IS FOR. PRD §20.3 says every reference deployment "passes the same smoke suite", and
§7 says the packages "must document which combinations are production-supported versus preview".
Those two sentences are the same requirement read from opposite ends: a target is `supported`
because a suite ran against it and passed, not because somebody wrote an adapter for it. This
package is that suite, and `report.py` holds the rule that turns its results into the claim.

WHY THE REPORT IS THE PRODUCT, NOT THE PASS/FAIL. A suite that prints "OK" tells a reader
nothing they can audit six months later: which release, which cluster, which scenarios actually
ran, which were skipped because the target could not host them. So every run emits an
`ACPAcceptanceReport` (schema: report.schema.json) naming the target, the release digests, every
scenario with its state and timing, and the eligibility decision with the reason it was reached.
Other workstreams consume that file — the certification matrix in packaging/docs is meant to be
generated from a directory of them, not maintained by hand.

FOUR STATES, AND THE THREE THAT ARE NOT `pass`. `acpctl doctor` established the reasoning this
suite inherits (see packaging/cli/acpctl/doctor.py): a check that could not run has established
nothing, and folding it into "pass" because nothing went wrong is how a report comes to mean the
opposite of what it says. Here that splits in two, because the causes are different and an
operator does different things about them:

  * `skip`    — the target does not have the capability the scenario needs (no fault injection,
                no previous release to upgrade from). Known, declared, and not the target's fault.
  * `unknown` — the scenario ran and could not establish an answer: a probe errored, a surface
                the suite needs does not exist on this build, a timeout. Somebody must go and look.

NEITHER COUNTS AS A PASS FOR ELIGIBILITY, and that is the entire point of the artifact. A suite
where every scenario skipped must report "not eligible, because nothing ran" — a report that says
`supported` because it did nothing is the exact failure this format exists to prevent, and it is
the failure that is easiest to ship by accident.

TESTABLE WITHOUT INFRASTRUCTURE, BY CONSTRUCTION. Every effect the suite can have on the world —
HTTP, kubectl, helm, waiting, reading a fixture, writing an artifact — goes through the execution
backend in `backend.py`. The real one shells out; the fake one answers from a described target and
records every call. So the whole suite, including the mutating scenarios, runs in CI with no
cluster, no network, no helm and no kubectl, and `tests/test_packaging_acceptance.py` asserts on
the fake's log that nothing escaped. A suite that can only be exercised where it is deployed is a
suite whose report format is debugged in production.

WHY THE PACKAGE IS NESTED ONE LEVEL DEEP. `packaging/acceptance/acp_acceptance/` mirrors
`packaging/cli/acpctl/` for the reason tests/test_packaging_layout.py records: the directory that
goes on sys.path must not be `packaging/`, because `packaging` is a real PyPI distribution that
pip, setuptools and pytest plugins import, and shadowing it breaks unrelated tooling with nothing
pointing back here. Putting `packaging/` on sys.path would additionally make `schema`, `docs`,
`examples` and `cli` importable as top-level names — the same hazard one level down. So the
importable name is `acp_acceptance`, and `export PYTHONPATH=packaging/acceptance` is what puts it
there.

DEPENDENCY BUDGET: standard library and PyYAML, the same as `acpctl` (see cluster.py's docstring).
This ships in the air-gapped bundle (PRD §17), where the answer to a missing dependency is not
`pip install`.
"""
from __future__ import annotations

# The suite's own version, reported in every report under `suite.version`. It is NOT the ACP
# release version: a report has to say which suite produced it, because adding a mandatory
# scenario changes what a `supported` claim means and old reports must not silently inherit it.
SUITE_VERSION = "1.0.0"

REPORT_API_VERSION = "packaging.acp.mova.io/v1alpha1"
REPORT_KIND = "ACPAcceptanceReport"

__all__ = ["SUITE_VERSION", "REPORT_API_VERSION", "REPORT_KIND"]
