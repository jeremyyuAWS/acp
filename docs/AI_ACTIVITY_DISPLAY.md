# AI activity display

The Remediate AI activity tab reads the owner-scoped, exact-run waterfall and metrics endpoints. It now shows a dashboard without requiring the user to open a model drawer. A selected model drawer uses the same chart presentation with exact stage/provider/model filters.

| Display | Evidence and meaning |
| --- | --- |
| Model activity bars | Durable attempt history joined to the spending ledger; reservations and released reservations excluded. Fallback and verification-driven retry calls appear under their actual provider/model. |
| Pace gauge and line | Settled attempt completions per minute, not findings repaired. The gauge scale is the highest observed minute in the displayed window, not a service capacity target. Missing minute observations remain gaps. |
| Model cost donut | Settled model-linked charges only. Percentages require complete attribution and a balanced total. Incomplete or single-model data uses an amount list. Reserved money is separate. |
| Individual model usage | Provider-reported input/output tokens retained in immutable attempt results. Missing or invalid token counts remain unavailable. Active calls do not report zero tokens as completed usage. |
| Average attempt time | Valid created-to-updated attempt timestamps. Includes dispatch, response, validation and settlement; does not claim pure provider latency or GPU throughput. The sample count is visible. |
| Output outcome bars | Settled attempt validation outcomes, not verified findings or approved proposals. Repair verification and publication remain separate stages. |

No prompts, model outputs, document text, filenames, pricing references or secret credentials are exposed by the metrics endpoint. Owner/run scoping, stale response guards, hidden-tab polling pause, and authorization-denial clearing are preserved.

The metric window is bounded to 1,000 retained records. Exceeding it marks coverage partial and withholds whole-run pace, spend percentages and output totals. Legacy calls lacking durable run history are not guessed into this run from scan-wide traces or chronological proximity. They remain unavailable rather than inventing attribution. Pure provider latency, cache-token breakdown and token throughput are not claimed because this retained contract does not establish them.

AI-disabled runs retain the explicit disabled explanation and do not render charts that suggest a provider is working. Actual local and cloud model identities are displayed from retained history, never from current configuration alone.
