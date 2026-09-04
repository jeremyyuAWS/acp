# ADR 0050 — Key Vault write-through: the product may accept a key value, and store none

Status: Accepted (2026-09-04). Amends [ADR 0019](0019-ai-provider-gateway-and-governance.md) §6.
Date: 2026-09-04
Related: [ADR 0019](0019-ai-provider-gateway-and-governance.md) (the gateway and the secret-ref
design this extends), [ADR 0049](0049-workspace-rbac-staged-rollout.md) (the admin gate this route
sits behind)

## Context

ADR 0019 §6 shipped a deliberate constraint: **the key value never enters the product.** Settings
→ AI providers stores the NAME of an ops-provisioned secret (`key_secret_ref`), `PUT /ai/providers`
rejects anything that looks like a pasted key, and the adapter resolves the value from
`os.environ` at call time. The reasoning holds: a key in Postgres is a key in every backup, every
replica, and every support dump.

The cost of that constraint is a workflow, and it is a real one. Turning on a provider requires an
ops team to provision a container secret and redeploy, then an admin to type its name. For a
customer who wants to try a hosted model this afternoon, "file a ticket with your platform team"
is the feature.

The proposal on the table was to accept the key in the UI and **encrypt it in the database**. That
was rejected:

- the app needs the plaintext to make a call, so the decryption key must itself live in an
  environment secret — you now provision **two** secrets instead of one, and the workflow this was
  meant to remove is still there;
- it moves a decryptable credential into every backup and replica, which is exactly what §6 avoids;
- anything holding both the database and the master key can recover the key, including an
  assistant with database access.

Encryption at rest answers one threat (someone reads the DB file) at the cost of the property that
made the original design defensible.

## Decision

**Accept the key value at ONE endpoint, and hand it straight to the deployment's Key Vault. Store
the resulting reference, never the value. Where no vault is configured, refuse.**

`key_secret_ref` gains a second kind of name, distinguished by prefix:

```
AZURE_OPENAI_API_KEY            -> read from os.environ      (unchanged; the only option without a vault)
keyvault:acp-ai-anthropic-key   -> read from the vault       (new)
```

- **`api/secret_store.py`** owns the seam: `active_secret_store()` returns a writable
  `AzureKeyVaultSecretStore` when `ACP_KEY_VAULT_URL` is set and the optional SDKs are installed,
  and otherwise a `NoWriteSecretStore` whose `write()` raises. Reads are cached (default 300s,
  `ACP_SECRET_CACHE_TTL_S`) because `_resolve_key` runs on the AI request path.
- **`POST /ai/providers/{provider}/secret`** is the only route that accepts a value. Admin-gated,
  mapped to `settings.view` in the capability table. It writes to the vault, upserts only the
  reference, and audits the reference.
- **The vault secret's name is derived** (`acp-ai-<provider>-key`), never supplied by the caller —
  a name over HTTP would let one admin overwrite another provider's secret, or something else in a
  shared vault, through a field that looks like a label.
- **The UI field is gated and write-only.** `GET /ai/providers` reports `secret_write.available`;
  the input renders only when it is true, is `type="password"`, is never prefilled (no read path
  returns a key, so there is nothing to prefill), and is cleared after every attempt — success or
  failure, because a live credential must not sit in a form for the rest of a session.
- **`PUT /ai/providers` is unchanged**, including its `^[A-Z][A-Z0-9_]{2,64}$` guard. A vault
  reference never travels through that route, so the guard that rejects a pasted key stays exactly
  as strict as it was.

## What this costs, stated plainly

**The key value now crosses one boundary it did not before: the browser → API request that sets
it.** That is the entire price of the feature. It is never echoed, never persisted, never logged,
and no read path returns it — but a request body carrying a credential exists where none did
before, and it will appear in any traffic capture an operator takes at that layer.

An operator who does not accept that leaves `ACP_KEY_VAULT_URL` unset. The endpoint then refuses
(422), the UI field never renders, and the product behaves exactly as it did before this ADR. The
refusal is the design: it keeps "we could not do this safely" from becoming "we did it unsafely".

## Consequences

- **A key written here is usable immediately**, with no redeploy: the read path resolves
  `keyvault:` references at call time. Under the container-secret design a newly provisioned
  secret needs a revision update before the app can see it.
- **The vault becomes a live dependency of the AI path** for providers configured this way. The
  cache bounds the blast radius (a vault outage is felt at most once per TTL per secret) and the
  failure mode is the existing one: no key resolves → the provider stays inert → local + human.
- **Rotation works from the UI**: a write overwrites the vault secret and clears the cache.
- **The Azure SDKs stay optional** (ADR 0019 rule 8). `azure-keyvault-secrets` and
  `azure-identity` are not in `api/requirements.txt`; a deployment that sets `ACP_KEY_VAULT_URL`
  without them is reported as not-writable with that reason, rather than failing at import.

## Verification, and the honest gap

`tests/test_provider_key_vault_write_through.py` (18 tests) pins the refusal, the derived name, the
charset, the cache, rotation, and — the load-bearing ones — that the value appears in **no**
response body, **no** config row, and **no** audit row. `frontend/src/aiProviderKeyWrite.test.js`
pins the gate, the write-only input, and that the key never rides along with the config PUT. Every
guard was bite-checked: turning the refusal into a fallback, echoing the value from the route, and
removing the UI gate each fail exactly the tests that forbid them.

**`AzureKeyVaultSecretStore` itself is not exercised against a real vault.** There is none in CI
and none in a development container, so every test drives a fake through the same Protocol. The
two SDK calls (`set_secret`, `get_secret`) are first executed for real by the first deployment that
configures `ACP_KEY_VAULT_URL`. That path is deliberately as small as possible, and the route
reports a vault refusal verbatim (`502` with the exception type) rather than as a generic failure,
because "the managed identity lacks `secrets/set`" is a fixable sentence and "it did not work" is
not.

## Deployment

1. Grant the app's managed identity the **Key Vault Secrets Officer** role (or `set` + `get` in an
   access policy) on the target vault.
2. Set `ACP_KEY_VAULT_URL=https://<vault>.vault.azure.net` on the container app.
3. Install the optional SDKs in the image: `azure-keyvault-secrets`, `azure-identity`.
4. Verify in Settings → AI providers: the paste field appears, and after storing a key the row
   reports `🔵 key present · key_vault`.

Skip all four and nothing changes.
