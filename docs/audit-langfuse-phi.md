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

1. **Decide the filename question first.** It is the only field that flows on every scan, and the
   only one whose sensitivity comes from the customer's naming convention rather than from
   ACP. Options, cheapest first: hash the filename into the trace and keep the plaintext only in
   the app's own database; or keep the extension and a per-scan index (`file 3 of 12 (.docx)`).
   Either keeps traces navigable while removing the patient identifier.
2. **Bound the reviewer note.** It is the one field with no truncation and no shape, so it is the
   one most likely to contain a sentence about a patient. Truncate as the neighbouring
   `approved_value` already does, or drop it from the trace and keep it in the HITL record.
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
