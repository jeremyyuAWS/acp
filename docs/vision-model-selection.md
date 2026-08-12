# Vision model selection for alt-text (2026-08-12 bake-off)

ACP's AI proposal lane drafts alt text for images that have none (WCAG 1.1.1). Those drafts are
never auto-applied — they route to human review — but a *wrong* or *garbage* draft still costs a
reviewer time and can land nonsense in a compliance artifact. This note records which vision model
we run and why, so the decision is not re-litigated.

## The bake-off

Five Ollama vision models on eight **document** images with recorded ground truth (bar / line / pie
charts, a flowchart, a data table, a labelled diagram, a wordmark, a scatter plot with an outlier).
The existing synthetic corpora were unusable for this — solid-colour placeholders don't discriminate
models — so the test images were generated fresh with matplotlib/PIL. Each model got ACP's alt-text
prompt on every image; outputs were scored /16 against the ground truth for accuracy, completeness,
conciseness, and hallucination. One RTX 3090 (24 GB) on RunPod, ~$0.04 total.

| Model | Score | Verdict |
|---|---|---|
| **qwen2.5vl:7b** | ~15.5 / 16 (97%) | Accurate, complete, zero hallucinations — caught every value and the BP outlier |
| minicpm-v | ~9.5 / 16 (59%) | Good on structure, but misses data, hallucinates ("five medications" — there were 3), and runs verbose |
| granite3.2-vision | ~7.5 / 16 (47%) | Concise but shallow, and a disqualifying hallucination (a payer-mix pie described as "healthcare spending") |
| moondream | ~3 / 16 (19%) | **Broken** — empty on 3 images, title-only on 3, and garbage on 2 (`~~~~~~Moviaio~~~~~~`, `!!!Readings #1!`) |
| llama3.2-vision:11b | DNF | Every call 500'd on this setup — inconclusive, not evaluated |

## Decisions

1. **`qwen2.5vl:7b` is the vision model.** It won decisively; nothing in the field beat it. When the
   GPU lane lands, deploy qwen (it fits comfortably: ~8 GB alongside `llama3.1:8b` ~6 GB).
2. **Do not rely on `moondream` for alt text.** It is the small CPU-deploy default (fast, fits an
   8 GB CPU server) but its output is unusable on real document images. It remains the code/env
   default only because qwen is impractical on the CPU server; the real switch happens with the GPU
   migration. `moondream` is fine as a warm-probe target, not as an alt-text author.
3. **Garbage defers to a human, model-agnostically.** `ai._is_usable_alt` requires a draft to clear a
   floor of real alphabetic content (min length, majority-alphabetic, ≥2 content words) or
   `describe_image` returns `None` — the same human-review defer an empty reply already triggers. This
   protects against any weak model, so the pipeline is safe whether it runs `moondream` today or
   `qwen2.5vl:7b` tomorrow. Shipped 2026-08-12.

## Why review still matters

`granite3.2-vision` confidently mislabelled a payer-mix pie chart as "healthcare spending" with wrong
numbers — a fluent, plausible hallucination no automated check would catch. It is exactly why ACP
keeps AI alt text behind human review rather than auto-applying it.
