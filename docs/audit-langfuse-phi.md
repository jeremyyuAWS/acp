# Audit — what Langfuse captures (P0.2)

**Date:** 2026-08-09 · **Question:** does PHI leave the trust boundary via tracing, and is there a
BAA question? · **Result: the specific fear is unfounded, four content-derived fields do leave the
app, and Langfuse is self-hosted in every deployment shape — so this is a data-retention question,
not a third-party-disclosure one.**

The backlog framed it as *"tracing records prompts by default, and ACP's prompts carry document
text and OCR output."* The first half is true of Langfuse's auto-instrumentation. ACP does not use
it — `api/lf.py` hand-builds every span, and the prompt is deliberately reduced to a length.

## 1. Prompts do NOT leave. Only their size does

`api/ai.py:211` is the only caller that traces a model call:

```python
_lf.trace_ai_call(surface, mdl, latency_ms, ok=ok, prompt_chars=len(prompt or ""),
                  completion=completion, scan_id=scan_id, file=file)
```

and `api/lf.py:364` puts that count, not the text, on the span:

```python
input={"prompt_chars": prompt_chars, "model": model},
```

So document text and OCR output — the things the backlog was worried about — are never sent. That
is the single most important line in this audit, and it appears to be deliberate rather than
lucky: a count is a strange thing to compute unless you are avoiding the string.

Likewise the PII span (`lf.py:204`) sends `sensitive_data_types` — the *types* and their counts,
e.g. `{"ssn": 3}` — and never the matched values.

## 2. Four content-derived fields DO leave

| what | where | bound |
|---|---|---|
| **Filename** | every trace, span, tag and metadata block | none |
| Model completion | `lf.py:365` `output={"completion": …}` | 1500 chars |
| Reviewer's approved value | `lf.py:386` `approved_value` | 500 chars |
| Reviewer's free-text note | `lf.py:386` `note=body.reviewer_note` | **none** |

**Filenames are the largest exposure by volume, and the least obvious.** In a hospital estate they
routinely carry the patient — `Smith_John_MRN0114233_intake.docx`. Every trace name, every
`file:` tag, and most metadata blocks carry one, on every scan, whether or not AI ran. Nothing
else on this list fires unless a model or a reviewer was involved.

The other three are genuinely content-derived: a completion for `describe_image` is a description
of a patient document's image; an approved alt text is a human's sentence about that image; and a
reviewer note is free text with no truncation and no schema.

## 3. Langfuse is SELF-HOSTED — in both deployment shapes

This is what makes the BAA question narrower than it looks.

* **Compose / customer-VPC** (`deploy/compose/docker-compose.yml:56`) —
  `LANGFUSE_HOST: http://langfuse:3000`, a container in the same stack. Traces do not leave the
  customer's network at all.
* **Azure** (`deploy/public/deploy.sh:37`) — `https://acp-langfuse.…azurecontainerapps.io`, an
  ACP-operated Container App in the same Azure environment as the API. Not Langfuse Cloud.

So no data is disclosed to Langfuse-the-company under either shape. What remains is ordinary
retention: a second store, inside the boundary, holding filenames and some model/reviewer text,
with its own access control and its own lifetime.

**One thing to check before a hospital deployment**, and the reason this section is not simply
"fine": `deploy.sh:38` hard-codes a default public key for the shared `acp-compliance` demo
project. A deployment that does not override `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` sends
its traces into the project the demo views. The secret key is *not* baked in (`LF_SK` must come
from the environment), so the practical failure is a deployment that sets no Langfuse credentials
and traces nowhere — but the default host and key pointing at shared infrastructure is worth
making explicit rather than leaving to whoever runs the script.

## 4. It is off unless three variables are set

`lf.py:19` — `_ENABLED = bool(_HOST and _PK and _SK)`, and every entry point returns early when
disabled. Absent credentials means no tracing at all, not degraded tracing.

## Recommendations

1. ~~**Decide the filename question first.**~~ **Done, 2026-08-09 — redacted by default.**
   A document now appears as `doc-3f9a2c.docx`: a keyed HMAC of the filename, truncated, plus the
   extension.

   **What it keeps.** The label is stable per (deployment, filename), so every span for a document
   still collapses onto one trace, a document is still followable across scans, and the extension
   still says what kind of file it is — most of what a filename was doing in a trace. What it
   stops is a trace reader learning a patient's name, and trace access is a wider circle than
   document access.

   **Keyed, not a bare digest.** An unkeyed hash is a dictionary: anyone who suspects a patient is
   in the estate could hash the likely filename and confirm it. `ACP_TRACE_SALT`, falling back to
   `LANGFUSE_SECRET_KEY` — already required for tracing to run at all, so a traced deployment
   always has one.

   **The trace ID was the real work.** It is `{scan_id}::{file}` and joins a file's spans, its AI
   calls, its HITL decisions and its score into one trace — built by string interpolation at four
   separate call sites. Redacting the display while leaving that would have looked fixed and
   leaked exactly as before, so every site now goes through one `_trace_id` helper. Nine call
   sites across four kinds of field (span name, id, tag, metadata) were involved;
   `tests/test_langfuse_redacts_filenames.py` drives each public entry point and asserts the
   patient's name appears nowhere in the captured payload. Mutation-checked: reverting the single
   tag site fails three tests.

   **Redaction is the DEFAULT, and the demo opts out** (`ACP_TRACE_FILENAMES=plain`, set in
   `deploy/public/deploy.sh`). The cost of the wrong default is asymmetric — an inconvenient demo
   versus patient names in an observability store — so it fails safe, the same shape as the E2E
   bypass in `core.py`. An unrecognised value also fails safe rather than falling through to
   plain.

   *Not addressed by this:* the `user:` tag and `user_id` still carry the signed-in operator's
   email. That is deliberate — it is the person running the scan, not a patient, and grouping
   traces by user is the point of it.
2. ~~**Bound the reviewer note.**~~ **Done, 2026-08-09 — as a length, not a truncation.**
   `trace_hitl_decision` now sends `note_chars` and never the text.

   **Truncating would have been theatre**, and the recommendation above was weaker than it should
   have been for suggesting it. PHI in a reviewer's note sits at the FRONT: *"Patient John Smith
   MRN 0114233 disputes…"* is forty-odd characters, so any cap that leaves the note readable
   leaves the identifier intact. A cap bounds volume, and volume was never the risk.

   Nothing is lost. The note is already persisted in `hitl_queue.reviewer_note`, the span still
   carries scan_id / file / rule_id / status, and the weak-rule rollup reads the structured
   `resolution` field rather than this free text — so the trace answers every question it did
   before, minus one it should not have been asked. It also brings the field into line with what
   the module already did for prompts (`prompt_chars`), which was the precedent rather than an
   invention.

   `approved_value` is deliberately left as a 500-char capped string: it is the text ACP writes
   INTO the document, authored to be published there, and seeing it is the point of tracing the
   decision at all.

   Pinned by `tests/test_langfuse_carries_no_free_text.py`, which asserts on the captured payload
   rather than the call shape — a test for "the key is now `note_chars`" would pass against a
   future version that helpfully added a `note_preview` beside it. Mutation-checked: reverting the
   one-line change fails three of the six tests. The file also pins the `prompt_chars` invariant
   this whole audit turned on, which nothing tested before.
3. **Make the Langfuse target explicit at deploy time** rather than defaulting to the shared demo
   project's host and public key.
4. **Record the retention period.** Self-hosted or not, this is a second copy of derived data;
   how long it lives should be a stated number, not whatever the container defaults to.

## What this audit does NOT cover

* **Langfuse's own access control** — who can read the self-hosted project's traces, and whether
  that set matches the app's allowlist. Different question, and the one that decides whether
  "inside the boundary" means much.
* **The `ai_calls` provenance rows** (`api/ai.py:217`) — a separate persisted record of model
  calls in ACP's own database. In scope for retention, out of scope for "does it leave".
* **Whether the compose stack's Langfuse is exposed** beyond the internal network.
