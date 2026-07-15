# ADR 0021 — Enterprise review memory (org style + derived preferences → grounded, curated draft guidance)

Status: **Accepted** (2026-07-12) — the Maturity Phase 3 ("Enterprise") arc. Phase 2 ("Trust metrics") is shipped: reviewer analytics, per-rule/per-format rollups, and the reject-reason enum (`hitl_events.reject_reason`, `hitl_analytics`). Phase 4 ("Audit trail") is shipped: the per-document provenance timeline. This ADR is the missing middle: turning the review signal Phase 2 already collects into **enterprise memory** that makes AI drafts match how *this organization's* reviewers actually approve — without fine-tuning, without fabricating anything, and without silently baking one reviewer's habit into "the org standard."
Date: 2026-07-12
Related: [ADR 0016](0016-evidence-based-confidence.md) (**the governing constraint** — a derived preference is a real, evidence-backed count or it does not exist; no fabricated confidence, no invented rule), [ADR 0019](0019-ai-provider-gateway-and-governance.md) (the AI seam memory injects into; local-first + provenance compose), [ADR 0102 prompt-version identity](../../docs) (`prompt_hash` — injecting memory changes the prompt, so provenance must track which memory shaped a draft), [ADR 0003](0003-document-lifecycle-model.md) (the org/owner scoping this extends), [ADR 0006](0006-pii-sensitive-data.md) (reviewer-behavior data is sensitive; aggregate signal, not dossiers)

## Context

The product's North Star is a **Visual Accessibility Copilot** whose drafts a human can verify and approve in seconds. Two things are already true:

1. **We generate drafts** — alt text, link text, section headings, slide titles, language tags, chart datasheets (the `propose_*` family in `api/proposals.py`, plus `ai.suggest_fix` / `describe_image_structured`).
2. **We record what the human did with each one** — `hitl_events` already persists, per decision: `ai_value` (what the model proposed), `final_value` (what the human approved), `edited` (did they change it), `reject_reason` (the Phase-2 enum: `too_vague`, `hallucinated`, `missed_text`, `incorrect_object`, `org_preference`, `other`), `rule_id`, `file`, `reviewer`. `hitl_analytics` already rolls this up per rule and per format, weakest-first.

**But that signal dead-ends in a dashboard.** A reviewer at an org that says "alt text under 120 characters, no 'image of', British spelling" edits every verbose AI alt-text down, ticks `org_preference` on the ones that miss — and the *next* document's drafts arrive exactly as verbose as before. The AI never learns that this org writes short, British, prefix-free alt text. Every reviewer re-teaches the model the same lesson by hand, forever. That is the opposite of a copilot; it is a very patient intern who never remembers yesterday.

The enterprise ask (the Phase 3 framing) is threefold:

- **Org style guide** — an organization has house rules for accessible content (length caps, tone, forbidden phrasings, terminology, spelling variant). Today they live in a reviewer's head or a PDF nobody reads.
- **Derived preferences** — beyond the written guide, reviewers reveal preferences through what they *edit and reject*. If 8 of 10 verbose alt-texts get shortened, "this org prefers short alt text" is a fact in the data, not an opinion.
- **Reviewer consistency** — across a team, the same finding should get equivalent treatment. Divergence ("reviewer A always rejects what reviewer B approves") is a real signal worth surfacing.

The naïve version of this is dangerous, and the ADR exists mostly to say how we avoid the danger:

- **Fine-tuning is the wrong tool.** It is opaque (you cannot show *why* a draft came out a way — fatal for a verifiable-evidence product), slow, per-provider, and it cannot obey the local-first / cloud-optional routing of ADR 0019. We are not fine-tuning.
- **Auto-learning is a bias amplifier.** If the AI learns from human edits and then humans approve AI drafts that already match their prior edits, one reviewer's idiosyncrasy — or one bad habit — becomes "the org standard" through a silent feedback loop. Left ungated, the system launders a single person's preference into an institutional rule.
- **Reviewer-level behavior is sensitive.** "Which reviewer rejects the most / edits the most" is one query away from a surveillance dossier. The enterprise buyer needs consistency signal, not a productivity panopticon.

## Decision

**Build an org-scoped, human-curated review memory that shapes draft *prompts* — never model weights — where every applied rule is either explicitly authored by an admin or derived from a real count of reviewer decisions, is shown on the card that used it, and is a proposal to a human before it ever influences a draft.**

The one-sentence contract: **memory changes what we *ask* the model, transparently and with the org's consent; it never changes the model, and it never invents a preference the data doesn't show.**

### A. What the memory is — three tiers, one store, all org-scoped

A single `org_memory` concept with a `kind`:

1. **`style` (authored)** — an admin writes an explicit house rule: a length cap, a forbidden phrase (`"image of"`, `"click here"`), a required spelling variant, a tone note, a terminology mapping. Scoped to an org, optionally to a `rule_id` (1.1.1) and/or `format`. This is a policy the org owns; it applies immediately because a human wrote it.
2. **`derived` (proposed from behavior)** — a nightly derivation job reads `hitl_events` and surfaces *candidate* rules backed by a count: "reviewers shortened 8 of the last 10 alt-text drafts (median −34 chars) → propose a ≤120-char guideline for 1.1.1." A `derived` rule is **inert until an admin accepts it** (see §D). Accepting it makes it a `style` rule with a recorded provenance (the count that justified it).
3. **`glossary` (authored)** — org-specific term expansions / preferred phrasings (an abbreviation the org's screen-reader users know, a brand's preferred product noun). A narrow, high-value special case of `style` kept separate because it is a lookup, not a constraint.

All three are **org-isolated by construction** — keyed on the org/owner scope ADR 0003 already carries. No memory crosses a tenant boundary; there is no shared/global memory in v1 (that would need a separate ADR and a separate consent posture).

### B. Data model (additive, rule-5 clean)

A new table, plus a derivation job — nothing existing changes shape:

```
CREATE TABLE org_memory (
  id TEXT PRIMARY KEY,
  org TEXT NOT NULL,           -- the ADR 0003 org/owner scope
  kind TEXT NOT NULL,          -- 'style' | 'derived' | 'glossary'
  rule_id TEXT,                -- NULL = applies to all rules
  format TEXT,                 -- NULL = applies to all formats
  guidance TEXT NOT NULL,      -- the compact instruction injected into the prompt
  status TEXT NOT NULL,        -- 'active' | 'proposed' | 'archived'
  evidence TEXT,               -- for 'derived': the JSON count that justifies it (ADR 0016)
  author TEXT,                 -- admin who authored/accepted it
  created_at TEXT, updated_at TEXT
)
```

- `guidance` is short and human-readable — it *is* the prompt fragment ("Keep alt text under 120 characters. Do not begin with 'image of' or 'picture of'. Use British spelling.").
- `evidence` is populated only for a `derived`/accepted rule and holds the real count (`{"rule":"1.1.1","edited":8,"of":10,"median_delta_chars":-34,"window_days":30}`). ADR 0016: the number on the card is this number, never a manufactured confidence.
- The derivation job writes `status='proposed'` rows; admin acceptance flips one to `status='active'`. No row is ever auto-`active` except an admin-authored `style`/`glossary`.

The raw learning signal is **already in `hitl_events`** — this ADR reads it, it does not add new capture. That is the whole reason Phase 3 is cheap now and would have been expensive a month ago.

### C. How memory feeds generation — retrieval + prompt injection at the ADR 0019 seam

Draft generation gains one pre-generation step, inside the AI seam ADR 0019 already defines:

1. **Retrieve.** Before building a proposer prompt, fetch the `active` `org_memory` rows for `(org, rule_id, format)` — a plain indexed lookup, most-specific-first (rule+format > rule > format > org-wide). **No vector store, no RAG framework** (rule 8 — minimal deps): the key space is tiny and structured. A handful of short rules is the whole retrieval result.
2. **Inject.** Compose the retrieved `guidance` into the existing prompt as an explicit constraints block ("House style for this organization: …"). This touches `ai._suggest_prompt` / `describe_image*` and the `propose_*` prompts through one shared helper (`memory.guidance_for(org, rule_id, format) -> str`), so a proposer opts in with one call and every proposer stays otherwise unchanged.
3. **Record what shaped the draft.** The applied memory rule ids ride along in the draft's provenance envelope (ADR 0019 `{result, provenance, trust}`), and because the prompt changed, the `prompt_hash` (ADR 0102) changes with it. The card shows "House style applied: ≤120 chars, no 'image of'" as a chip the reviewer can expand — the memory is *visible*, never a hidden hand.

Deterministic proposers (chart datasheet, language tag, the one-click layout cards) ignore memory — there is nothing to steer; their output is data, not prose. Memory only touches *prose* drafts, where org voice is real.

### D. The curation gate — the anti-drift, anti-bias control (the load-bearing decision)

**A derived preference is a proposal to a human, never an auto-applied rule.** This single constraint is what separates "enterprise memory" from "silent bias laundering":

- The derivation job never writes an `active` rule. It writes `proposed` rows with their evidence, surfaced in a Settings → **Review Memory** panel: "We noticed reviewers shorten alt text (8/10, −34 chars median). Adopt a ≤120-char guideline? [Accept] [Dismiss] [Edit]."
- **Minimum evidence.** A candidate needs a floor of decisions (e.g. ≥ N edits/rejects of the same shape within a window) before it is even proposed — one reviewer editing one draft never becomes a rule.
- **Recency + decay.** Derivation windows on recent behavior and decays old signal, so a preference the org has moved past stops being proposed. Accepted `style` rules persist until an admin archives them (org policy shouldn't silently expire), but the *derived proposals* track current behavior.
- **Reversible.** Any `active` rule can be archived; archiving takes effect on the next draft. Prompt-hash provenance means you can always tell which drafts a now-archived rule shaped.

This is the failure-mode answer (rule 10): the feedback loop is broken by a human gate, single-reviewer idiosyncrasy is filtered by the evidence floor, and stale preference is filtered by decay. The system proposes; the org decides.

### E. Honesty + provenance (ADR 0016, non-negotiable)

- **Every number is real.** A `derived` proposal shows the actual count from `hitl_events` — never a fabricated confidence, never a "94% of reviewers prefer…" that no query produced. If the count is 8 of 10, the card says 8 of 10.
- **Every applied rule is visible.** A draft shaped by memory says so, on the card, expandable to the exact guidance and (for derived rules) the evidence that justified it. No invisible influence on a value a human is about to certify.
- **Provenance is complete.** `prompt_hash` changes when memory changes the prompt (ADR 0102), so the audit timeline (Phase 4) can show "draft generated with house style v3" and reconstruct exactly what the model was asked.

### F. Privacy + scope — consistency signal, not a dossier

- **Org-isolated.** Memory never crosses tenants. A tenant's reviewer behavior shapes only that tenant's drafts.
- **Aggregate, not individual, by default.** Derived rules are computed over the org's decisions in aggregate. The `reviewer` column exists (it is already in `hitl_events`) but drives **consistency** surfacing, not ranking — see §G. There is no "reviewer productivity leaderboard," and this ADR forbids building one on this data.
- **Reviewer data is ADR-0006-sensitive.** Access to per-reviewer views is admin-gated and framed as calibration, not surveillance.

### G. Reviewer consistency (the profiles layer — deliberately minimal in v1)

The "reviewer profiles" ambition is real but is the easiest place to build something creepy or unfair, so v1 scopes it tightly to **team consistency, not individual scoring**:

- Surface where the *team* diverges: a rule where approve/reject rates split sharply across reviewers is a calibration flag ("1.1.1 alt text: reviewer decisions disagree — align on a house rule?"), which naturally feeds a §A `style` rule.
- Do **not** build per-reviewer preference injection in v1 (drafts tuned to *who is reviewing*). It risks entrenching one person's idiosyncrasy and fragmenting the org's voice, and it needs a consent/fairness posture this ADR does not resolve. It is a Non-goal here and a candidate for a later ADR if the org asks for it.

## Consequences

- **The review signal stops dead-ending.** Phase 2's reject-reason and edit data becomes a live input to generation, so the copilot actually improves with use — the North Star's "learning" claim becomes true, and provably so (every improvement is a visible, evidence-backed rule).
- **No fine-tuning, no new heavy dependency.** Memory is a table + a lookup + a prompt fragment. It composes with ADR 0019's local-first routing (the same injected prompt goes to Ollama or a cloud provider), obeys ADR 0016 (real counts only), and rides ADR 0102 provenance. Minimal-deps (rule 8) is preserved — no vector store in v1.
- **The enterprise story gets concrete.** "Your org's house style, applied automatically, learned from your reviewers, fully auditable, and never leaving your tenant" is a differentiator that a fine-tuned black box cannot claim.
- **Bias is gated, not eliminated — and that is the honest posture.** A curated rule can still encode a bad org preference (an org that insists on verbose alt text will get verbose drafts). The system's job is to make that preference *explicit, evidence-backed, and reversible*, not to overrule the org. The gate stops *silent* drift; it does not adjudicate taste.
- **A visible product surface.** A new Settings → Review Memory panel (authoring + accepting proposals) and a per-card "house style applied" chip. Rule-5 flag: this adds a place org policy lives, so it is an admin-facing UX addition, not just plumbing.
- **Migration is additive.** One new `org_memory` table, one nightly derivation job reading existing `hitl_events`, one shared `guidance_for` helper the proposers opt into. Nothing existing changes shape; keyless/local builds with no memory rows behave exactly as today (empty retrieval → unchanged prompt → byte-identical draft).

## Rollout (staged — each independently shippable, behind flags)

1. **Store + authored style.** `org_memory` table + admin CRUD (`GET/PUT /org-memory`, admin-gated like `/ai/providers`) + the `guidance_for` helper wired into **one** proposer (alt text, the highest-volume prose draft) behind `ACP_REVIEW_MEMORY`. Proves injection + provenance + the visible chip end-to-end on one rule before spreading. Empty store = unchanged behavior.
2. **Spread injection.** Opt the remaining prose proposers (link text, section headings, slide titles, sensory, reading-level) into `guidance_for`. Deterministic proposers stay out. Still authored-only.
3. **Derivation job (proposals only).** The nightly job reads `hitl_events`, emits `status='proposed'` candidates with evidence and the min-evidence floor + decay window. Surfaced in Settings → Review Memory as accept/dismiss/edit. **No auto-activation.** This is the switch that makes memory *learn*; everything before it is authored-only groundwork.
4. **Consistency flags.** Team-divergence surfacing (§G) that feeds candidate `style` rules. Individual-reviewer tuning stays a Non-goal.

## Non-goals

- **Fine-tuning or any weight update.** Memory shapes prompts, never models. If a customer wants a fine-tuned model, that is ADR 0063's finetune-provider surface, not this.
- **Auto-applying derived rules.** A behavior-derived preference is always a human-gated proposal (§D). There is no path where reviewer edits silently become an active rule.
- **Cross-tenant / global memory.** All memory is org-isolated in v1. A shared "best-practice" corpus is a separate ADR with its own consent posture.
- **Per-reviewer draft tuning / reviewer scoring.** v1 surfaces team *consistency*, not individual preference injection or productivity ranking (§G). Deferred, ADR-gated.
- **A vector store / RAG framework.** Retrieval is a small structured key lookup; adding embedding infrastructure for a handful of short rules violates minimal-deps (rule 8).
- **Fabricated confidence on a proposal.** A derived rule shows its real count or is not proposed (ADR 0016). No manufactured percentages, ever.
- **Changing what conformance means.** Memory affects draft *wording*, never whether a finding fires or whether a fix clears the re-scan. The detectors and the verify-guard are untouched.
```
