# Remediation reliability

This change addresses the September 11 SharePoint scan's observed vision capacity rejections, Redis connection failures, telemetry ingestion errors, and misleading progress presentation.

## Vision routing

Assessment can use the existing governed OpenAI or Anthropic vision adapter. In Settings, enable the provider with its model and secret reference, then select it as the vision provider (`ai_vision_provider`). A configured secret alone never activates cloud processing. Cloud admission has its own bounded semaphore, so a busy local GPU cannot reject the cloud fallback.

Remediation uses the accepted run's cloud consent, permitted providers, model positions and spending limit. Image calls use provider-native image blocks and the same durable spending reservations as the text waterfall. Actual model, provider, tokens, cost and call identity are recorded. Model confidence remains a draft estimate; approval and independent verification remain separate recorded decisions.

The server's `ACP_BOUNDED_TEXT_PROFILE` or `ACP_BOUNDED_TEXT_MODELS_JSON` must provide unexpired image-capable primary and fallback models. The existing `anthropic-balanced` and `openai-balanced` catalogs identify supported image positions. A text-only third position is not used for images. This feature does not change an existing run's accepted budget or local-only policy.

Local vision waits up to 30 seconds for admission by default (`ACP_VISION_QUEUE_TIMEOUT`), instead of 0.25 seconds. Cloud concurrency defaults to four per process (`ACP_CLOUD_VISION_MAX_CONCURRENCY`). Explicit rate-limit rejections have bounded retries. Calls with uncertain paid usage are not repeated blindly.

## Recorded outcomes

Verified-cleared repair records now serialize `verified: true`. This describes the saved repair record, not whole-document compliance or publication. Reruns still clear obsolete saved repair records.

Finding outcomes reconcile against the assessment independently for each document. Missing or duplicate identities and inconsistent populations show recorded versus assessed counts. They do not hide other documents' confirmed outcomes or contribute invented counts to the live totals.

A corrected copy retained in ACP with source delivery pending is shown as saved progress. An actual failed provider delivery remains an error. Neither state claims the source document was updated.

## Dependency outages

Redis is a progress cache; durable queue state remains authoritative. Failed cache connections are reset, and cross-replica status falls back to durable job records without guessing that an active job was interrupted.

Langfuse ingestion uses short timeouts, bounded attempts and a circuit breaker. Health distinguishes actual HTTP ingestion from SDK queue flushes. Repeated SDK error logs are suppressed while occurrence counts remain available. This protects remediation from telemetry outages; it does not repair the external telemetry service.

## Validation

Regression fixtures cover real repair serialization, partial document reconciliation, provider-native image requests, durable spending, saturated GPU fallback, cross-replica cache failure and telemetry ingestion failures. Frontend behavior is verified in Vitest DOM tests; the shared preview server does not serve isolated worktree changes.
