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
| 6 | Show 17 rules | Criterion table defaults to the tracked 17 | #155 |
| 7 | App is too busy | Nav 9→8, Settings 11→8, −661 lines | #151 |
| 9 | Make remediation collapsible | Four reference sections collapse; the work inbox does not | #154 |
| 12 | Remove Upload | Tab removed, capability folded into Discover | #151 |
| 13 | Remove Validation coverage | Removed | #151 |
| 14 | Business ontology remove | Editor removed; the data path is untouched | #151 |
| 18f | Keep scoring rules & File types tab | Kept | — |
| 18g | For the 14, more detail on Assessment and Remediation | Answered by #155 — e.g. 1.3.1 on DOCX now states the `Heading 1..9` level-skip rule | #155 |
| 18h | Take What's Changed out of Overview | Removed | #151 |

**Three requirements were one mechanism.** "Select which rules", "filter by file types" and
"pick the SCs" are all `scan_scope`, which already existed and already gated the pipeline. The
work was making it reachable and correct, not building it — see §5.

### 4.2 In progress

| # | Requirement | State |
|---|---|---|
| 18a | Control plane: filter by dept, user, Enterprise | Tenant column (#159) and scoped aggregates (#160) merged. Route and Settings surface outstanding |
| 8 | Remediation more intuitive | Collapsing shipped (#154). The rest is undefined — see §7 |
| 4 / 18c | List of users with access to ACP | The Users tab exists; making it authoritative is not started |
| 15 | File types and custom file-type exclusions | `FileTypeConfig` exists; its relationship to `scan_scope`'s format axis is unresolved — two controls, one concept |

### 4.3 Not started

| # | Requirement | Note |
|---|---|---|
| 18e | Make Disposition policies work | Untouched |
| — | Scope visibility in Remediate and Publish | See §6 — the mechanism carries, the *statement* does not |

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

1. **Scope visibility in Remediate and Publish.** Neither screen names the active scope — zero
   references to `activeScope` in either. An operator sees counts with no statement of what is
   being counted. Discover, Assess, Overview and Transparency all state it. Small: the sentence
   already exists and is exported.
2. **Control plane surface.** Route + Settings tab over the aggregates merged in #160.
3. **Unify the two file-type controls.** `FileTypeConfig` and `scan_scope`'s format axis are
   different answers to one question, and an operator can set them to disagree.
4. **Per-document filtering as a first-class carry-through.** Discover's `restrictedBySelection`
   narrows a run by marked document; it is a separate mechanism from `scan_scope` and the two are
   not unified.
5. **Disposition policies.**

---

## 7. Open questions — blocked on a decision, not on effort

| Question | Why it needs an answer |
|---|---|
| "Fix Language -" | Truncated in the source notes. Cannot be scoped |
| "Need to flush out Publish so that the Remediation…" | Truncated |
| "Make this filter work:" | Truncated — appears to have had a screenshot attached |
| What does "more intuitive" mean beyond collapsing? | #154 shipped the collapsing. The rest is a design brief nobody has written |
| Should either write-back button replace originals at all? | SharePoint now archives before overwriting (#158); Drive's archive is still best-effort. Making them consistent is a product decision |
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
| 14 | Agreed scope (`deva-final`) | What did we agree to assess for this engagement? |

17 = the document core minus 1.4.4, 1.4.10 and 1.4.12 — resize, reflow and text spacing, which
are viewer behaviours rather than properties of a static document. The relationship is pinned by
a test so a future reader does not "restore" them as an oversight.
