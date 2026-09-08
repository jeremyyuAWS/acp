# How configuration reaches the application

**Who this is for.** An operator who has a `acp-deployment.yaml`, ran `acpctl values`, installed the
chart, and now needs a variable the application reads to actually be set. It answers one question:
given a name in `api/`, what do I put in the document?

**The short answer for a credential is: declare it as a secret reference and you are done.** The
chart projects every entry of `secrets.refs` as its own environment variable, on every workload.
Nothing else is needed and no template changes.

## The three ways a variable arrives

**1. The chart computes it.** `ACP_RELEASE`, `ACP_DEPLOY_ENV`, `ACP_DEPLOY_PROFILE`, `ACP_PLATFORM`,
`OTEL_SERVICE_NAME`, `OLLAMA_BASE_URL`, `ACP_AI_LOCAL_ONLY`, `PORT`, `ACP_WORKERS`,
`ACP_WORKER_ROLE`, `ACP_SHUTDOWN_DRAIN_SECONDS`. These are facts about the installation, so the
document does not name them and cannot override them.

Some of that group is conditional and reads as unconditional if you only check one render:
`OLLAMA_BASE_URL` needs `ai.ollama.enabled`, `ACP_AI_LOCAL_ONLY` needs `ai.mode: local-only`,
`OTEL_SERVICE_NAME` needs OpenTelemetry on, and `ACP_DB_MAX_CONN` appears only for a tier that
pins `connectionPool` — none of the shipped examples does, so it is absent from every stock
render. A variable missing from your pods is not necessarily a defect; check the condition first.

**2. A document field the chart reads.** `objectStorage.account` becomes `ACP_BLOB_ACCOUNT`;
`observability.langfuse.host` becomes `LANGFUSE_HOST`. These are endpoints rather than credentials,
so they are values in the document rather than references to a secret store.

**3. A secret reference, projected by name.** Every key under `secrets.refs` is rendered as an
environment variable whose name is the key **uppercased with hyphens replaced by underscores**, its
value read from the referenced Secret:

```yaml
secrets:
  refs:
    applicationinsights-connection-string: {name: kv-acp, key: appinsights}
    #   ^ arrives in every container as APPLICATIONINSIGHTS_CONNECTION_STRING
```

**This loop is generic. Declaring the reference IS the wiring** — there is no allow-list of names
in the chart, no per-variable template, and `acpctl validate` accepts references beyond the ones a
configuration requires. So a name the application reads that is not in the list below is set by
adding one line to `secrets.refs`.

Two consequences worth knowing before you rely on it:

- **The name is the application's, spelled its way.** `acp-blob-account` and `acp_blob_account` are
  different keys and only one produces `ACP_BLOB_ACCOUNT`. A misspelled reference is not an error
  anywhere: it creates a variable nothing reads, beside the one that is still unset.
- **The projection reaches every workload**: the API, all three worker tiers, and the migration
  and preflight Jobs. There is no way to give one tier a credential and not another. Ollama and
  Grafana are the exception — they run third-party images that read none of these names, and get
  their own configuration.

## Names the application reads that the chart does not set

Each of these is read by `api/`, set by `deploy/public/*.sh` on the Container Apps deployment, and
absent from the Helm render. `tests/test_packaging_seams.py` asserts all three facts per entry, so
this table cannot quietly become a list of solved problems.

| Variable | What its absence costs | How to set it |
|---|---|---|
| `ACP_ALLOWED_EMAILS` | the sign-in allow-list is empty — fail-closed, and load-bearing the moment the access gate is armed | `secrets.refs.acp-allowed-emails` |
| `ACP_GOOGLE_ADC` | the image entrypoint writes no `/tmp/adc.json`, so Drive service-account access is silently unavailable | `secrets.refs.acp-google-adc` |
| `RUNPOD_API_KEY` | the credential half of the serverless vision provider | `secrets.refs.runpod-api-key` |
| `RUNPOD_ENDPOINT_ID` | the address half; without both, provider selection falls through to the local CPU floor rather than reporting a provider that could not be reached | `secrets.refs.runpod-endpoint-id` |
| `HITL_WEBHOOK_URL` | no POST when a human-in-the-loop item queues | `secrets.refs.hitl-webhook-url` |
| `ACP_VISION_PROVIDER` | GPU vision is never selected at deploy time, whatever the two RunPod values say | **no path — see below** |

Five of the six are reachable today and the gap is that nobody wrote this page. The sixth is a
real structural gap.

## The one that has no path: a non-secret application value

`ACP_VISION_PROVIDER` is a provider name, not a credential. Routing it through `secrets.refs` would
work — the projection does not care — and would put a non-secret in a Secret, which is the habit
that makes a secret store useless. **The deployment document has no field for an application
variable that is not a secret and not one of the endpoints in group 2 above.**

What this costs is narrower than it looks, and worth stating exactly rather than dramatically.
`api/providers.py` reads `ACP_VISION_PROVIDER` as the DEPLOY-TIME DEFAULT (ADR 0022); an admin
setting `ai_vision_provider` in the application's own store overrides it, and that path is
unaffected. So GPU vision is configurable on a Helm installation — by a post-install admin action
that nothing in this package performs, documents elsewhere, or verifies. The document cannot
express it, and an installation that sets both RunPod values and nothing else gets the local CPU
floor with no error.

Adding a general `extraEnv` escape hatch to `acp-deployment.yaml` would close it and is not a
change to make quietly: a field that can set any variable can also contradict the rest of the
document, and PRD §2.8 puts contract changes behind an API version. It is recorded here as the
decision it is rather than taken.
