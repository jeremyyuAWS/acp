# PRD — ACP v2 redesign

**Status:** in progress · **Source:** the v2 requirements list, 2026-08-07 · **Fork:** `frontend-v2/` (#139)

This is written from the raw requirements list rather than around it, so each line is traceable
back to something that was actually asked for. Where an item is done it says which PR did it, and
where a requirement turned out to mean something different from its wording, that is recorded
rather than quietly reinterpreted.

---

## 1. Problem

The app is too busy. An operator opening ACP meets nine workflow tabs, eleven settings tabs, and
eight stacked panels on the remediation screen — most of which are reference rather than work.
The decision that matters most, *what should this engagement assess*, was reachable only through
an admin screen nobody opens, after discovery had already run.

Two consequences drive everything below:

- **The critical choice happened too late.** Narrowing scope after a scan leaves the results on
  screen disagreeing with the scope beside them.
- **The product could state a verdict and not explain it.** "1.3.1 fails" with no way to ask what
  ACP actually checked.

## 2. Goals

1. Choosing what to assess happens **before** discovery, in one control.
2. That choice **carries through** discovery → assess → remediate → publish without re-plumbing.
3. Every screen shows **less**, and what remains is what an operator acts on.
4. Any criterion can answer **"what do you actually check?"** in the words of the engineer who
   maintains the detector.

## 3. Non-goals

- Migrating to Postgres. It is already a supported backend (`DATABASE_URL`, psycopg2 pool).
- Cross-tenant administration. The store defends tenant isolation in at least four places
  deliberately; a superuser view is a security decision, not a UI one, and is out of scope here.
- Scoring model quality. The comparison harness prints drafts and refuses to score them.

---

## 4. Requirements, and where each one landed

### 4.1 Shipped

| # | Requirement (as written) | Outcome | PR |
|---|---|---|---|
| 1 | Ability to select which rules need to run | The `scan_scope` setting — a per-criterion, per-format map | #145, #153 |
| 2 | Need to filter by file types | **Same mechanism.** Not a second control | #145, #153 |
| 3 | Remove permissions | Settings tab and panel removed | #151 |
| 5 | Need architecture for each rule Assess/Remediation | Per-rule detail generated from `docs/rules/*.md` | #155 |
| 6 | Show 17 rules | Criterion table defaults to the tracked 17; the pre-discovery scope grid offers `SCOPE_UNIVERSE ∩ TRACKED_17`, so the other 12 — AAA rules and viewer behaviours — are not rows to dismiss on the first screen an operator sees | #155, #168 |
| 7 | App is too busy | Nav 9→8, Settings 11→8, −661 lines | #151 |
| 9 | Make remediation collapsible | Four reference sections collapse; the work inbox does not | #154 |
| 12 | Remove Upload | Tab removed, capability folded into Discover | #151 |
| 13 | Remove Validation coverage | Removed | #151 |
| 14 | Business ontology remove | Editor removed; the data path is untouched | #151 |
| 18f | Keep scoring rules & File types tab | Kept | — |
| 18g | For the 14, more detail on Assessment and Remediation | Answered by #155 — e.g. 1.3.1 on DOCX now states the `Heading 1..9` level-skip rule | #155 |
| 18h | Take What's Changed out of Overview | Removed | #151 |
| 18a | Control plane: filter by dept, user, Enterprise | `/control/estate` + a Settings tab. It filters, it does not merely display: department and owner are inputs, and the tenant comes from the request and is never a parameter | #159, #160, #165 |
| 15 | File types and custom file-type exclusions | `FileTypeConfig` now WRITES `scan_scope`, so the toggles gate assessment and remediation instead of only filtering the Discover list — which is what the panel had always claimed | #166 |
| — | Scope visibility in Remediate and Publish | `ScopeBanner` names both the criterion scope and the run boundary, above the counts it qualifies | #164 |
| — | SharePoint alongside Google Drive | Sites, libraries, a picker in Discover, and server-side write-back that replaces the original after archiving it | #156, #157, #158, #167, #171 |

**Three requirements were one mechanism.** "Select which rules", "filter by file types" and
"pick the SCs" are all `scan_scope`, which already existed and already gated the pipeline. The
work was making it reachable and correct, not building it — see §5.

### 4.2 In progress

| # | Requirement | State |
|---|---|---|
| 8 | Remediation more intuitive | Collapsing shipped (#154). The rest is undefined — see §7 |
| 4 / 18c | List of users with access to ACP | **The tab is a mock.** `UserManagement.jsx` renders a hardcoded `SEED_USERS` array and imports nothing from `api.js`; there is no `/users` route on the backend. It looks authoritative and is not, which is worse than absent |

### 4.3 Already built — the requirement may have been about something narrower

| # | Requirement | What is actually there |
|---|---|---|
| 18e | Make Disposition policies work | **Built front and back, and this PRD was wrong to call it untouched.** `api/routes/disposition.py` + `api/disposition.py` (ADR 0003 Phase 3) with `tests/test_disposition_execute.py`; `Disposition.jsx` is 258 lines covering policy CRUD, preview, execute, the approval queue and the audit trail, reachable at Settings → Disposition. Policies are created disabled, approval-gated by default, and "delete" is always Drive trash. **What may have prompted the requirement:** in the SIM build every one of those clients returns synthetic data (`_simDisp`), so on a demo deployment the whole tab is theatre — which is exactly what "make it work" would describe |

### 4.4 Clarified rather than built

| # | Requirement | What it turned out to be |
|---|---|---|
| 18d | "Remediated storage - ollama" | Ollama is the **AI provider** (`api/ai.py`), not storage. It has always been the default. Now in the local compose stack with a model-comparison harness (#161) |
| 18b | Remove permissions tab | Duplicate of #3 |

---

## 5. The carry-through, and why it needed no re-plumbing

The scope gate lives in `_rule_outcome`, which is *"the one place a verdict is decided"*. It is
applied there before any lane branching, so:

| Stage | Inherits by |
|---|---|
| Assess | `in_scope()` inside `_rule_outcome` — an out-of-scope pair reads NOT_EVALUATED |
| Remediate | the deterministic fixers take the same `in_scope` predicate (`handlers.py:478`) |
| Publish | reads `get_certification_facts`, which is *"the SAME `_rule_outcome`"* |

`publish.py` never mentions scope, correctly — it cannot publish a verdict that was never
produced. **Gate once at the authoritative point; everything downstream inherits.**

---

## 6. Open work, in priority order

Everything the first version of this list held has since merged — scope visibility (#164), the
control plane surface (#165) and the two file-type controls (#166). What remains:

1. **Per-document filtering as a first-class carry-through.** Discover's `restrictedBySelection`
   narrows a run by marked document through a mechanism entirely separate from `scan_scope`.
   Every other filter — criteria, formats — funnels through the one gate in `_rule_outcome` and
   inherits assess, remediate and publish for free (§5). This one does not, so it is the single
   remaining gap in "the filter carries through everywhere".
2. **Make the Users tab real, or stop shipping it.** A hardcoded roster that reads as live data
   is a worse answer than an empty state. Needs a backend; none exists.
3. **Decide what the SIM build should claim.** Disposition, Rubric and Test users all return
   synthetic data there. That is defensible for a demo and indefensible if anyone reads a demo as
   a capability statement — and requirement 18e suggests somebody already did.

### A note on reading this document

§4.3 exists because this PRD asserted, for two weeks, that Disposition policies were untouched
while a full implementation sat in `api/routes/disposition.py` with tests. Nobody checked,
because the document was the thing being checked against.

So: **verify against the tree before planning from any row here.** A status column is a claim
about the past, and this repo moves faster than the claim does.

---

## 7. Open questions — blocked on a decision, not on effort

| Question | Why it needs an answer |
|---|---|
| "Fix Language -" | Truncated in the source notes. Cannot be scoped |
| "Need to flush out Publish so that the Remediation…" | Truncated |
| "Make this filter work:" | Truncated — appears to have had a screenshot attached |
| What does "more intuitive" mean beyond collapsing? | #154 shipped the collapsing. The rest is a design brief nobody has written |
| ~~Should either write-back button replace originals at all?~~ | **Answered: yes, replace, after archiving.** Both SPAs now write through `/sharepoint/upload` with `item_id`; the server archives to `_mova-originals/<date>/` and a failed archive aborts the write (#171, #172). Replacing keeps the item's URL, sharing links and version history, so people holding a link get the remediated file. **Drive is still the odd one out** — its archive is best-effort (`catch { }`), so a failed archive there is followed by the overwrite anyway. That is now the only inconsistency left, and it is the unsafe direction |
| Artifact-level provenance for SharePoint | Folder-scoped exclusion ships today and is the approach `provenance.py` rejects for Drive. The stronger version needs `Sites.Manage.All` |

---

## 8. Success criteria

- An operator can choose criteria and formats **before** the first scan, in one control, and see
  that choice reflected on every screen that reports against it.
- No screen shows a total whose denominator is not stated on the same screen.
- Any criterion in the table can answer "what do you check?" without leaving the page.
- Removing a surface never leaves prose pointing at it. *(#151 failed this — three dangling
  "Settings → …" references survived the deletion and were fixed in #154. It is a success
  criterion because it was missed once.)*

---

## 9. Numbers this product quotes, and which one is which

Recorded because the redesign added a fifth, and the defence against a sixth is that nothing may
retype one.

| Count | Name | Answers |
|---|---|---|
| ~38 | Traced | Did ACP look at this criterion on this format? |
| 29 | `SCOPE_UNIVERSE` | Which (criterion, format) pairs may an operator scope? |
| 20 | Document core | What does the product certify against? |
| **17** | **Tracked** (`MOVA_TRACKED`) | **What does this customer follow?** |
| 14 | Agreed scope (`engagement-14`) | What did we agree to assess for this engagement? |

17 = the document core minus 1.4.4, 1.4.10 and 1.4.12 — resize, reflow and text spacing, which
are viewer behaviours rather than properties of a static document. The relationship is pinned by
a test so a future reader does not "restore" them as an oversight.
