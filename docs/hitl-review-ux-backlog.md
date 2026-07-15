# HITL review-card UX backlog — "AI Work Inbox"

Reframe of the Human-review card from *exposing ACP's internals* → *guiding the reviewer to one
confident action*. The architecture is ~90% there (reviewType, trust states, provenance, assess-time
pre-draft, gateway escalation all exist); this closes the ~40% UX gap on top of it. Grounded in the
current code so each item is a change, not a wish.

**The reviewer's four questions, answered top-to-bottom:** (1) what's wrong · (2) where · (3) what
ACP recommends · (4) what to click. Everything else (model, provider, OCR, validator, trace) is
audit detail behind **Details ▾**, never competing for attention.

**Guiding principle:** ACP is an *AI accessibility copilot that presents the best evidence-backed
recommendation possible* — local-first, auto-escalating to customer-approved premium models when
needed, reducing every human review to a simple, confident decision. LLMs assist the reviewer; they
don't just generate text.

---

## P0 — leads with intent, one action, no blank box (mostly rendering of data we already have)

- [x] **Review-Intent sentence at the very top of every card.** *(shipped f7ae0de)* `reviewIntent`
  renders one task-first plain-language line keyed off `reviewType` (proposal / confirm / author),
  flavoured by the finding's noun, above any audit detail.
- [x] **One primary button, labelled by workflow** *(shipped f7ae0de)* — `primaryActionLabel`:
  proposal → **Approve AI fix** · author → **Approve description** · confirm → **Confirm fix**;
  "I'll fix it" / reject-with-reason demoted to secondary.
- [x] **Kill the "Draft with AI" button — auto-generate the preview.** *(shipped 11075eb)* An
  undrafted value-fix now drafts itself when the card scrolls into view (IntersectionObserver +
  once-guard), through a shared 2-concurrent gate (`autoDraft.js`) so the whole-queue render never
  stampedes the model. The single-box + "Draft all" buttons are gone (passive "Drafting…" status);
  the per-image button becomes "↻ Draft this image" retry, with "↻ Try again" / "Draft remaining N"
  for vision-outage recovery. Never overwrites reviewer text, never re-drafts a pre-drafted card.
- [x] **Never a bare "Type the value…" box.** *(shipped f7ae0de)* `authoringScaffold` replaces the
  empty textarea with a per-SC **suggested outline** when there's no draft, so a reviewer authoring
  from scratch gets a guided task instead of "good luck"; it disappears the moment they type. (Now
  the auto-draft covers most of these before a human ever sees the empty box.)
- [x] **Progressive disclosure.** *(shipped 7d52776)* The card leads with the decision (intent,
  why-safe, editor/recommendation, what-to-do, how-to-confirm) and collapses the machinery under a
  single native **Details ▾**: trust-state enums, provenance (model/zone) + audit-trail toggle &
  table, clustered detection evidence, and "why human review". Collapsed by default; reorganisation
  of already-computed data, no new endpoints.
- [x] **Positive evidence framing — "Why this is safe to approve."** *(shipped 283a522)* New
  `whySafeToApprove(card)` composes an affirmative, above-the-fold confidence list from real trust
  signals (re-scan passed · deterministic sign-off · grounded-in-source wording · no prior value).
  Two honest gates (irreducibly-human criteria + visual-only drafts never show green) keep it from
  contradicting "Why human review?" or painting a false green (ADR 0016). Rendered as a green
  callout under the intent sentence in EvidenceCard.
- [x] **Rename the section: Human Review → AI Work Inbox.** *(shipped 283a522)* Renamed across the
  reviewer-facing surfaces (Remediate h2 + rail, HitlBell, ReviewCenter, Upload, Publish). The
  lifecycle-stage / report-lane labels stay "Human review" — they name human judgement as a
  *pipeline stage*, still accurate and distinct from the inbox brand.
- [x] **Move audit jargon out of the primary flow** *(shipped 7d52776)* — the trust enums
  ("AI/heuristic detection", "not yet written to document"), provenance, detection evidence and
  "why human review?" all dropped under the Details ▾ disclosure above. The task-first intent
  sentence carries the primary ask; nothing decision-critical is buried.

## P1 — auto-escalation + copilot rewriting (needs the gateway + the refine palette)

- [ ] **Auto-escalation before the card is shown.** Wire the existing `describe_image_structured`
  escalation (local → cloud when a customer provider is configured) into the **assess-time batch
  pre-draft** path, so "manual authoring required" becomes rare. Card shows the transparent numbered
  path ("✓ local attempted → no grounded description → escalated to {provider} → grounded"), never
  the failed attempt as a dead end.
- [ ] **One-click "Improve" palette** (extend the #131 refine, which already has Shorter / More
  detail / Regenerate): add **Mention the numbers · Ignore colours · Professional tone · Plain
  language**. Local model handles these today; premium models when configured.
- [ ] **LLM-written guidance instead of the terse system string.** Replace "No faithful alt-text
  source in the document…" with a natural, generated sentence: "This slide has a comparison chart
  that screen-reader users currently can't perceive. ACP couldn't verify a grounded description, so
  it needs your wording." (Deterministic template first; premium-model phrasing when available.)
- [ ] **Empty-state honesty tie-in.** When escalation is OFF and local produced nothing, the card
  says *why* it's manual (not "Ollama not running") and links the admin to enable a governed cloud
  provider (Settings → AI Providers).

## P2 — visual evidence + premium-model copilot (the differentiators)

- [ ] **Describe THIS image, not the whole slide.** Use ADR 0018 shape geometry to crop/bounding-box
  the specific flagged image on the slide render (the card currently shows the whole slide at page
  size). Add zoom + "open slide". Label it "Describe this chart."
- [ ] **"Help me" copilot (premium models).** A button that returns *guidance*, not another alt
  draft: "This chart compares compliance scores across departments — focus on the trend, not the
  colours." A better use of Claude/GPT than a second text generator. Requires a customer cloud
  provider (BYOAI) — governed, opt-in, provenance-logged.
- [ ] **Reviewer-behaviour → automation-mode migration.** Feed HITL edit-rate / acceptance
  (`hitl_events`) back so a criterion with consistently low edit-distance surfaces as ready to move
  Human-Assisted → AI-Assisted (ties to the automation maturity funnel + ADR 0019 §8.5).

## Dependency — unblocks P1/P2 premium-model items (ADR 0019 Phase 2)

- [ ] **Ship the OpenAI + Anthropic vision adapters.** The Settings → AI Providers tab already lists
  them and stores keys as secret-refs, but `ADAPTER_READY = {azure_openai}` — only Azure is wired.
  Add `OpenAIVisionProvider` / `AnthropicVisionProvider` behind the existing `VisionProvider`
  Protocol (`api/providers.py`) + the `active_vision_provider` / `cloud_vision_provider` selectors,
  as opt-in `pyproject.toml` extras. Then OpenAI/Anthropic keys entered in the UI actually route
  vision + power auto-escalation and the "Help me" copilot.

---

### Sequencing note
P0 is almost entirely **frontend reorganisation of data the card already receives** — highest
leverage, lowest risk, shippable without the GPU or any new provider. P1's auto-escalation and P2's
copilot depend on a reachable premium model (the adapter dependency). So: land P0 first (the card
*feels* like a copilot), then the adapters, then P1/P2 light up the escalation + copilot on top.
