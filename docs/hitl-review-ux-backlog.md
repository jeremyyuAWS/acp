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

- [x] **Auto-escalation before the card is shown.** *(shipped #1292)* Wired the existing
  `describe_image_structured` escalation (local → cloud when a customer provider is configured) into
  the **assess-time batch pre-draft** path, so "manual authoring required" becomes rare. Card shows
  the transparent numbered path ("✓ local attempted → no grounded description → escalated to
  {provider} → grounded"), never the failed attempt as a dead end.
- [x] **One-click "Improve" palette** *(shipped #1294)* — Shorter / More detail / Regenerate already
  in `ProposalEditors.jsx`; added **Mention the numbers · Ignore colours · Professional tone · Plain
  language**. `ai.py` maps all seven steer keys to distinct vision prompts; unknown keys fall back to
  the default prompt, not an error. Local model handles these today; premium models when configured.
- [x] **LLM-written guidance instead of the terse system string.** *(shipped #1296)* `guidanceSentence(card)`
  in `reviewCard.js` replaces "No faithful alt-text source in the document…" with a natural sentence:
  noun from file extension (slide/worksheet/page), image kind from `describedImageType`, draft status
  from proposals. "This slide has a comparison chart that screen-reader users cannot perceive. ACP
  drafted a description — review and approve it below." Deterministic; no model call.
- [x] **Empty-state honesty tie-in.** *(shipped — `emptyStateHonesty.test.jsx` + `EvidenceCard.jsx` #403-435)*
  `manualCloudHint` shows when `draftFailed && !escalation && cloudStatus !== null`. Two honest
  branches: cloud enabled but couldn't ground → names the provider; no cloud configured → links
  admin to Settings → AI Providers. Fetched lazily via `loadAiModels` (module-cached; one
  `/ai/status` call for the whole inbox).

## P2 — visual evidence + premium-model copilot (the differentiators)

- [x] **Describe THIS image, not the whole slide.** *(ADR 0018 Slices 2–3 shipped; zoom label
  context-aware via #1299)* `Thumbnail.jsx` fetches per-shape geometry via `getFileGeometry`, draws a
  red overlay on the exact object, renders that object's own page, and offers a CSS-crop close-up
  toggle. `EvidenceCard.jsx` passes `kindLabel={imgKind?.label?.toLowerCase()}` so the toggle reads
  "⤢ Zoom to chart" / "Hide chart" instead of generic text. **Remaining sub-item:** "Open slide"
  deep-link (source file + page anchor) — deferred; requires per-source-system URL construction
  (SharePoint / Drive / local).
- [x] **"Help me" copilot (premium models).** *(shipped #1301)* A "✨ Help me understand this image"
  button on 1.1.1 evidence-only cards (gated on `cloudEnabled`): calls `GET /ai/copilot` →
  `copilot_guidance()` in `ai.py` (cloud-only, traces via `_trace_ai("copilot", ...)`), returns
  1–2 sentences of interpretive guidance rendered in a clearly-distinct italic callout ("AI
  guidance — not a draft"). Never writes to the proposal value. Cloud status fetched eagerly for
  these cards so the button appears without a prior draft failure. Requires a customer cloud
  provider (BYOAI) — governed, opt-in, provenance-logged.
- [ ] **Reviewer-behaviour → automation-mode migration.** Feed HITL edit-rate / acceptance
  (`hitl_events`) back so a criterion with consistently low edit-distance surfaces as ready to move
  Human-Assisted → AI-Assisted (ties to the automation maturity funnel + ADR 0019 §8.5).

## Dependency — unblocks P1/P2 premium-model items (ADR 0019 Phase 2)

- [x] **Ship the OpenAI + Anthropic vision adapters.** *(shipped — #1246, polished #1258/#1260)*
  `OpenAIVisionProvider`, `AnthropicVisionProvider`, and `HuggingFaceVisionProvider` are all wired
  behind the `VisionProvider` Protocol in `api/providers.py`. `ADAPTER_READY` in `Settings.jsx` is
  now `{azure_openai, openai, anthropic, huggingface}`. Keys entered in the UI route vision through
  `active_vision_provider` / `cloud_vision_provider`. HuggingFace supports private
  OpenAI-compatible Inference Endpoints with bearer auth, secret-ref handling, safe synthetic
  connection testing, and Langfuse attribution. **Not yet proven in production** — an admin still
  needs to provision the endpoint, model, and secret, then enable and test in Settings → AI
  Providers. The active cloud-vision path remains Azure-hosted Ollama.

---

### Sequencing note
P0 is complete. P1's auto-escalation and P2's copilot depended on wired adapters (the former
dependency above) — those are now shipped. **The adapter blocker is cleared.** Next: wire
assess-time auto-escalation (P1 item 1) through `describe_image_structured` so the HuggingFace /
OpenAI / Anthropic adapters actually drive pre-drafting, with transparent provenance
("✓ local attempted → escalated to {provider} → grounded"). Then the one-click Improve palette
and the "Help me" copilot (P2) follow directly on top.
