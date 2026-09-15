# Optional Quality-first remediation

Quality-first is a per-plan opt-in beside Local models and Local + cloud models. Existing saved plans retain their meaning. The accepted plan freezes `quality_first: true`; document input continues to use the existing automatic selection and supported full-PDF path.

The option uses the existing verified GPT-4.1 / Sonnet 5 quality profile for supported text, image, and document requests, keeping the owner-selected provider first for general requests. Native PDF retains its explicit native profile ordering. Both cloud providers must already be permitted and configured. The existing catalog expiry, endpoint validation, durable budget reservations, response validation, retries, and approval choices remain in force. Model availability or budget failure leaves work unresolved rather than using Ollama. This does not promise every accessibility issue can be fixed or that these are the newest available models.

The default mixed mode may still try a local draft. Quality-first skips that attempt, blocks local vision fallback, and rejects a quality transport if its endpoint is not classified as cloud. No global provider, sign-in, credential, or publishing settings change. Readiness checks validate configuration without paid generation; real account model access remains a dispatch-time check.

## Workflow cards

Overview intentionally omits the shared workflow-stage stack. Its implementation remains available on the other tabs. Cards begin collapsed unless their stage is processing on that stage's tab (Release maps to Publish). Collapsed headers retain live state and heartbeat; users can open details manually. Tab navigation resets manual disclosure, while collapse alone preserves mounted detail subscriptions.

## Release scope

Deploy application and stage workers together so the API and workers understand the same accepted policy. No database migration or new credential is required. Roll back by restoring the prior image across those roles; avoid rolling back while a Quality-first run is queued or active because the prior worker does not understand the new selection.
