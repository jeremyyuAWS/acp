# Local models for ACP — what they can and cannot do

Measured 2026-08-08 on an Apple M5 Pro (48 GB unified memory), Ollama 0.32.6 native, all models
resident on GPU. Every draft goes through `api/ai.py` — the shipped path — not a hand-written
prompt, so these are statements about ACP, not about the models in the abstract.

---

## Read this first: models decide 25 of 61 cells

Of the 61 (criterion, format) pairs in `acp-core-17`:

| remediation lane | pairs | can a better model change it? |
|---|---|---|
| `assisted` | **25** | **yes** — the entire addressable set |
| `auto` | 19 | no — deterministic rule code |
| unlisted → human | 14 | no |
| `human` | 3 | no |

**41% of the matrix is model-dependent. The rest is engineering or human judgement.** Any slide
comparing models without this denominator overstates what model choice decides.

The nine criteria in play: **1.1.1, 1.3.1, 1.3.2, 1.3.3, 1.4.5, 2.4.4, 2.4.6, 3.1.2, 4.1.2.**

---

## Vision — WCAG 1.1.1 alt text

Test image: `frontend/public/samples/enrollment-notice.png` (880×380), a benefits notice — an
image OF TEXT, which is the case a hospital estate is full of.

**Accuracy is measurable here**, unusually. Because the image contains text, ground truth is its
own OCR, and the question "how many of the document's facts does the alt text carry?" is
countable rather than a matter of taste. Six facts: title, enrollment window, coverage types,
portal name, default-if-not-elected consequence, contact number.

| model | size | latency | words | facts conveyed | verdict |
|---|---|---|---|---|---|
| `moondream` ← **cloud default** | 1.7 GB | 1.7s | 9 | **0 / 6** | **states a false fact** |
| `llava:7b` | 4.7 GB | 2.7s | 4 | 1 / 6 | title only |
| `qwen2.5vl:7b` | 6.0 GB | 4.4s | 16 | 3 / 6 | usable alt |
| `qwen2.5vl:32b` | 21 GB | 16.7s | 33 | **5 / 6** | long description |

### The drafts, verbatim

> **moondream** — "Urnbation notice for open enrollment on march 1st, **2021**"
> **llava:7b** — "2026 Open Enrollment Notice"
> **qwen2.5vl:7b** — "The notice announces open enrollment from March 1 to March 31, 2026, for UT Southwestern benefits."
> **qwen2.5vl:32b** — "2026 Open Enrollment Notice details enrollment from March 1 to March 31, 2026, for medical, dental, and vision coverage via UT Southwestern Benefits Portal; defaults to prior year if not elected by deadline."

### What this means

**The model ACP deploys today scores 0 of 6 and asserts a fact that is wrong** — the document
says 2026, moondream says 2021. For a compliance document that is worse than no alt text: a
screen-reader user is told a false date with no signal that it was guessed. The `Urn…` prefix
recurs across unrelated images (three observations), so it is a defect of the model, not noise.

**The decisive step is moondream/llava → qwen2.5vl:7b**, not 7B → 32B. The first two describe the
MEDIUM ("a notice", "a screenshot"); only from 7B does the alt convey what the document SAYS.

**32B's extra facts may be the wrong goal.** WCAG 1.1.1 asks for a concise equivalent. 33 words
naming a portal and a fallback rule reads as an excellent LONG DESCRIPTION — a real accessibility
artifact, and not what belongs in an `alt` attribute. The honest reading of this table is that
7B is the right model and 32B argues for a product change (a separate long-description field),
not a bigger model.

---

## Text — 1.3.3, 2.4.4, 3.1.2, 4.1.2

**No accuracy column, deliberately.** There is no ground truth for "is this good link text", and
`scripts/bench_models.py` refuses to score for that reason: a number nobody can defend is worse
than none. What IS measurable is whether a draft was produced at all, and how long it took.

| model | size | drafts produced | latency range |
|---|---|---|---|
| `llama3.1:8b` ← **deployed** | 4.9 GB | **4 / 4** | 0.3 – 3.1s |
| `qwen3:14b` | 9.3 GB | 3 / 4 | 8.3 – 17.1s |
| `qwen3:32b` | 20 GB | **2 / 4** | 19.1 – 31.9s |

**Completion rate falls as size rises, and latency rises 10–100×.** The reasoning models spend
their generation budget on a thinking pass; where that pass runs long the answer is never
emitted and the draft comes back empty.

### Where bigger genuinely won

- **3.1.2 Language of Parts** — `qwen3:14b` returned correct markup, `<span lang="fr">…</span>`,
  where `llama3.1:8b` wrote prose describing what to do.
- **1.3.3 Sensory Characteristics** — `qwen3:32b` returned `Click the [button label] button`,
  declining to guess a label it could not see. `llama3.1:8b` invented "Continue" — and leaked its
  own reasoning into the value: *"(Note: I assumed the label of the button is …"*, which would be
  written into the document verbatim.

That second row is the interesting one: the small model is more *usable* and the large model more
*honest*. Which is better is a product decision, not a benchmark result.

---

## Two defects found by running this at all

Both were invisible until models ran locally, and both would have made any model comparison wrong.

**1. `num_predict: 60` silenced every reasoning model** (`api/ai.py`). The cap was sized for the
answer alone. A reasoning model spends it thinking and emits nothing, so `suggest_fix` returns
`None` and the card reads "no draft" — indistinguishable from a model that cannot do the task.
Measured on `qwen3:14b` with ACP's own prompt: **`num_predict=60` → 0 characters in 2.2s;
`num_predict=400` → a correct rewrite in 14.0s.** Fixed in #198; 400 is still short for 32B,
which is why two of its four drafts are empty above.

**2. The benchmark read the wrong key.** `bench_models.py` took the draft from `value`/`alt`;
`ai.suggest_fix` returns it under `suggestion`. The text half of the harness had **never
displayed a single draft** — every row printed `None` while models answered correctly. Left
unfixed, this evaluation would have concluded that local models cannot do text remediation.

---

## Recommendations

1. **Change the vision default from `moondream`.** It scores 0/6 and asserts false facts on the
   document type this customer has. This is a shipping defect, not a tuning preference. Blocked
   on the 8 GiB Azure Consumption ceiling that forced it (ADR 0022 requires the CPU floor stay
   available), so it is an infrastructure decision.
2. **`qwen2.5vl:7b` is the target for alt text** — 3/6 facts at 4.4s, in 16 words. 32B's 5/6 at
   16.7s and 33 words is a better long description and a worse `alt`.
3. **Keep `llama3.1:8b` for text.** It is 10–100× faster and the only model that answered every
   criterion. Revisit if `num_predict` is raised further for 32B.
4. **Do not buy a bigger model.** Both curves flatten or invert. The constraint on those 25
   `assisted` pairs is policy — `R3 → R4` means ACP writing to a hospital's document unattended —
   and no model changes that. A better model makes the case defensible; it does not make it safe.

---

### Method and limits, for anyone who asks

- Single run per model, warm, one document. Latency is a data point, not a distribution.
- Fact coverage applies to 1.1.1 only, and only because the test image contains text. It does not
  generalise to photographs, where no ground truth exists.
- Drafts are produced through `api/ai.py`, so prompt shaping is ACP's, not the model's best case.
- Model sizes are the on-disk quantised footprints reported by `ollama list`.

---

## Addendum — the 15-document DOCX corpus (2026-08-08)

`scripts/gen_model_eval_corpus.py` builds 15 .docx fixtures, one issue per file;
`scripts/eval_models_docx.py` runs every model over them and scores against each fixture's
declared criteria. Five deterministic criteria act as controls and were **stable across every
model in both sweeps** — so the comparisons below are valid rather than assumed to be.

### Result: model choice does not change WHAT gets remediated on .docx

| sweep | models | outcome |
|---|---|---|
| vision | moondream, llava:7b, qwen2.5vl:7b, qwen2.5vl:32b | **identical across all 4** |
| text | llama3.1:8b, qwen3:14b, qwen3:32b | **identical across all 3** |

Every model fixed the same 5 deterministic criteria, fixed 1.1.1 on the OCR-groundable image,
raised 1 proposal for the textless image, and fixed nothing else.

### The text model is never called

Total wall-clock for all 15 documents:

    llama3.1:8b   0.5s        qwen3:14b   0.2s        qwen3:32b   0.2s

`qwen3:32b` needs 20–30s **per call**. 0.2s across fifteen documents means **zero calls**. DOCX
remediation does not invoke the text model at all — the assisted criteria (2.4.4, 1.3.3, 3.1.2,
1.4.5, 1.3.2) are detected during assessment and produce neither a fix nor a proposal during
remediation.

So text-model choice is irrelevant to .docx remediation **by construction**, not by coincidence.
The earlier text-ladder numbers measure what a model would draft **if asked**, through
`ai.suggest_fix` directly. Remediation does not ask.

### What this means for the model question

Model quality changes the **content** of exactly one .docx fix — the alt text — where it changes
it a great deal (0/6 facts for moondream, 5/6 for qwen2.5vl:32b, and moondream asserts a false
year). It changes **nothing** about which criteria are remediated.

A bigger model therefore cannot raise .docx remediation coverage. Raising coverage means wiring
the assisted criteria into the remediation path, which is a product decision about whether ACP
drafts unattended — and then a policy decision about whether it writes.
