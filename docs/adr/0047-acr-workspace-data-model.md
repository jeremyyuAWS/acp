# ADR 0047 — Accessibility Conformance Report workspace: data model and the three decisions behind it

Status: Accepted
Date: 2026-09-01
Phase: 1 of 6 (see `docs/prd-acr-workspace.md` §22)

## Context

Customers buying or approving ACP ask for an Accessibility Conformance Report (ACR) — the
VPAT-structured document procurement, legal and compliance teams file. Today that evidence is
scattered across scan results, remediation records, manual testing and team knowledge, and
`docs/conformance-report.md` is a hand-written markdown snapshot with no evidence links, no
version identification and no reviewer sign-off.

The risk this ADR exists to manage is not "we lack a document". It is that a generated ACR is a
**compliance claim about a product, sent to people who will rely on it**. Every design choice
below is chosen to make an unsupported claim hard to produce, including by accident.

## Decision 1 — the ACR criteria catalog is NEW, generated, and separate from the rule catalog

This repo already has a WCAG catalog: `config/rule-catalog.json`. It is the wrong one, and reusing
it would have been the natural mistake.

|                     | `config/rule-catalog.json`               | `config/wcag-2.2-aa.json` (new) |
|---------------------|------------------------------------------|---------------------------------|
| Standard            | WCAG **2.1**                             | WCAG **2.2**                    |
| Axis                | per document format (docx/pptx/xlsx/pdf) | none — the criterion itself     |
| Subject             | **a customer's files**                   | **ACP's own web UI**            |
| Scope               | the Core-17 subset ACP detects           | all 55 A+AA criteria            |

`docs/conformance-report.md` already draws this line in prose: *"this report covers the
conformance of the platform's own web UI, not the conformance of customer documents it
remediates."* Merging the two catalogs would let a finding about someone's Word file become
evidence for a claim about ACP's UI — the unsupported compliance claim the PRD's problem statement
opens by naming. `tests/test_acr_no_regression.py` enforces the separation at the schema level: no
ACR table may carry `scan_id` or reference `file_records`/`issue_records`.

The catalog is **generated** from the W3C Recommendation by `scripts/gen_wcag_catalog.py`, not
hand-transcribed, because a missing criterion or a wrong level is invisible at every stage until a
customer's reviewer finds it: the matrix renders, the report publishes, and nothing errors.

Two facts the generator established by running, both of which contradicted a first draft written
from memory:

* WCAG 2.2 A+AA is **55 criteria — 31 Level A, 24 Level AA**.
* **4.1.1 Parsing is still IN the 2.2 document**, titled "Parsing (Obsolete and removed)", with no
  `conformance-level` marker. Its levelless presence is therefore a *sharper* 2.1-vs-2.2
  discriminator than absence would be — in 2.1 the same criterion carries "(Level A)". The
  generator asserts exactly that, and excludes it from the catalog.

## Decision 2 — "an automated pass is not a pass" reuses the existing coverage gate

PRD §4.3 requires that an automated pass never produce "Supports". This repo solved that problem
already, on the right axis, and **ADR 0031** wrote up the reasoning: certification is gated by
*coverage*, not *confidence*. `assessment.CAN_CERTIFY_PASS` is exactly `{Coverage.FULL}` — a clean
automated result certifies a pass **iff the technique reaches the whole criterion**. Accuracy and
completeness are different properties; a perfect score on the subset a detector examines says
nothing about the part it never looked at.

`api/acr_rules.py` imports that frozenset rather than re-deriving the idea. Two consequences are
worth stating because both look like defects from outside:

* **axe-core's coverage is never FULL for any criterion.** It is PARTIAL where it has rules and
  DECLARED/UNSUPPORTED where it has none. So under this rule **no criterion ever auto-drafts
  "Supports" from automation alone.** That is PRD §4.3 working, not a missing feature.
* The draft-suggestion path fires only once *human* evidence supplies the remainder. A criterion
  resting at `needs_review` with a green axe run is the correct state, not a stuck one.

A related bug this design surfaced during implementation: an automated `pass` beside a **blocked**
human keyboard test originally drafted "Supports", because the rule asked "did anything pass?".
It now asks whether the *human* result is a pass (`acr_rules.has_human_pass`). A tester who could
not complete a test has evaluated the criterion; they have not established that it conforms.

## Decision 3 — ACR authority is its own role table, and `OPEN_ACCESS` does not confer it

PRD §21.11 requires that only an approver may publish. ACP's default access model
(`ACP_OPEN_ACCESS=1`) makes `core.is_admin()` return **True for any authenticated, admitted
user** — deliberately, because the rest of the product has no separate admin view. Measured on
unmodified `main`:

```
OPEN_ACCESS           = True
is_admin(owner)       = True
is_admin(random user) = True     <-- anyone who can sign in
is_owner(random user) = False
```

Gating ACR publication on `is_admin` would satisfy the requirement on paper and not at all in
fact — and would pass a naive test, since on a dev box with no `ACP_OWNER_EMAIL` configured
`is_admin` returns True for everyone. So authority lives in the `acr_role` table, read through
`api/acr_authz.py`. `OPEN_ACCESS` does not confer it and `is_admin` does not confer it. The one
carve-out is the protected `ACP_OWNER_EMAIL` (`core.is_owner`), which must be able to grant the
first role or a fresh deploy has a feature nobody can ever administer.

`tests/test_acr_authorization.py` runs with `OPEN_ACCESS=1` explicitly set, because that is the
configuration the gate exists to survive, and it asserts the underlying gap directly so that if
`is_admin` ever stops being open the carve-out can be revisited rather than cargo-culted.

**This is the first place in ACP where being an admin is not sufficient.** That asymmetry is
deliberate and is recorded here so it is not later "fixed" for consistency.

### The tenancy departure this forced

Everywhere else in ACP, `owner_email` is **per-user data isolation** — `routes/scans.py` says so
in as many words. An ACR cannot work that way. PRD §6 names five distinct humans and §18
recommends that the approver not be the person who made most of the decisions; under per-user
tenancy a second person's request 404s at the ownership check before any role is consulted, so
the approver can never open the report they must approve.

ACR rows therefore live in **one namespace per deployment** (`routes/acr.py::_tenant`), keyed on
the protected owner. This was found by running the tests, not by design review: the role model was
built first, keyed on the caller, and every cross-user test returned 404 instead of 403. The roles
were not wrong; the namespace was.

Reads are open to any admitted user; every **write** is role-gated. That split is `core.py`'s own
reasoning applied here — OPEN_ACCESS gives everyone the same screens and the same non-destructive
features, and does not open the irreversible ones. An ACR reaches a customer's procurement file
and cannot be recalled.

## Schema

Seven tables, all additive, all app-level references rather than DB foreign keys (matching
`scan_inventory.scan_id`, `content_workspace_documents.workspace_id`, …).

| table | notes |
|---|---|
| `acr_report` | PRD §8 metadata, `catalog_hash`, `status`, `supersedes_id`, `revision` |
| `acr_criterion` | the matrix. **`final_status` and `workflow_state` are two columns** |
| `acr_evidence` | append-only; carries `coverage` for automated rows |
| `acr_manual_test` | Phase 3's plan instances; created now so Phase-1 evidence has somewhere to point |
| `acr_decision_log` | append-only audit (PRD §17); `decision_log`'s shape, without its scan anchor |
| `acr_snapshot` | immutable published snapshots + a recomputable content digest |
| `acr_role` | Decision 3 |

**Why `final_status` and `workflow_state` are separate columns.** PRD §9 permits ACP's internal
states ("Not evaluated", "Needs review") and forbids them appearing as VPAT conformance levels.
One column holding both vocabularies is exactly how "Not evaluated" ends up printed in a
customer's conformance table. The four-term constraint is enforced at *every* layer that can write
it — `acr_model.CriterionDecision`, `store.save_acr_decision`, `acr_validation.validate`, and
`acr_export_preview._conformance_cell` — because it is the one field whose wrong value is a false
compliance claim.

**Why staleness is derived, not stored.** A stored `is_stale` flag is wrong the instant the
report's product version is edited, with no write to any evidence row to trigger a recompute.
`acr_freshness.evaluate` takes the report and the evidence and returns the stale set;
`acr_rules` accepts it as a parameter and never consults a column.

**Why the snapshot digest is called a digest.** `api/report.py` already carries this instruction
for its own: *"It is a DIGEST, not a digital signature: no key, no non-repudiation. Never relabel
it."* Inherited verbatim.

**RESET.** All seven are classified as data, following this repo's rule that rules survive a reset
and records do not (`disposition_policy` survives, `disposition_audit` and `decision_log` are
wiped). `acr_role` goes too — a surviving approver grant is exactly the residue "completely fresh"
promises against, and it is safe only because the owner carve-out means nobody can be locked out.

## Consequences

* A conformance report cannot be published from automated evidence. That is the point, and it
  means the feature is only as useful as the manual testing that goes into it (Phase 3).
* The ACR namespace decision means every admitted user can read the report. If a deployment needs
  ACRs invisible to some signed-in users, that is a new requirement, not a bug in this one.
* The ITI VPAT® template is **not** vendored. Phase 1–4 ship a structural preview that says on its
  face that it is not a VPAT. Vendoring the template is a licensing decision for Phase 5 and gets
  its own ADR, following ADR 0029's precedent.

## Alternatives considered

* **Extend `assessment_policy` with WCAG 2.2.** Rejected: it would put "criteria ACP detects in
  customer files" and "criteria ACP's UI is judged against" in one table, which is the specific
  conflation most likely to produce a false claim.
* **Gate publication on `core.is_admin`.** Rejected: see Decision 3. It would have passed review.
* **Generalise platform roles.** Rejected for Phase 1: it touches every existing route and
  regresses PRD §21.18 risk for no ACR benefit.
* **Store staleness as a column.** Rejected: see above.
