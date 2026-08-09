# Audit — per-user data isolation (`owner`)

**Date:** 2026-08-08 · **Scope:** can one authenticated user read another's documents, scans or
remediated files? · **Result: no.** Five links checked, all sound. Two configuration foot-guns
found that are not live in production.

The question matters because the customer is a hospital and the documents are PHI. An IDOR here
is not a data-quality bug, it is patient-record disclosure.

## The chain, link by link

### 1. `owner` cannot be influenced by a request

`api/routes/scans.py:19`

```python
def _owner(request: Request) -> str:
    return getattr(request.state, "user_email", None) or "demo"
```

`request.state.user_email` is written in exactly one place — the access-gate middleware in
`api/app.py`, after `verify_gis_token` (or `verify_entra_token`) returns an email AND
`email_allowed()` passes. **No query parameter, path segment, header or body field reaches it.**
Every route uses this helper; none accepts an owner from the caller.

### 2. Production runs the mode that sets it

The middleware branches `if ACCESS_CODE: … elif GOOGLE_CLIENT_ID: …`. Only the second branch sets
`user_email`. Read from the running container:

| variable | value |
|---|---|
| `ACP_GOOGLE_CLIENT_ID` | set |
| `ACP_ACCESS_CODE` | **empty** |
| `ACP_ALLOWED_EMAILS` / `ACP_ALLOWED_DOMAINS` | set |

`ACCESS_CODE` empty means the first branch is not taken, so the token path runs and `user_email`
is populated per user.

### 3. The whole-gate bypass is off, twice over

`app.py:41` returns early for a matching `X-E2E-Key`, skipping auth AND the allowlist. It is
fail-closed in `core.py:43-59`:

```python
IS_PROD = ACP_DEPLOY_ENV|ACP_ENV in ("production","prod")
TEST_BYPASS_ENABLED = ACP_ENABLE_TEST_BYPASS truthy AND not IS_PROD
E2E_KEY = ACP_E2E_KEY if TEST_BYPASS_ENABLED else None
```

Measured on the running container: `ACP_ENABLE_TEST_BYPASS` **absent**, `ACP_DEPLOY_ENV`
**`production`**. Either alone disables it; both hold. `E2E_KEY` resolves to `None`, so the header
is inert.

### 4. The store enforces ownership, not just the routes

- `list_scans` — filters in SQL: `WHERE … AND owner_email=%s`
- `get_scan` — `if owner is not None and run["owner_email"] != owner: return None`
- `get_scan_diff` — rejects unless BOTH scans belong to the caller

### 5. The one unscoped query is gated by its callers

`get_scan_traces(scan_id, file)` takes no `owner`. Both call sites resolve ownership first and
404 before reaching it — `scan_traces` (`:488`) and `scan_digest` (`:565`) each call
`get_scan(sid, owner=_owner(request))` and raise if it returns `None`.

## Two foot-guns, neither live

**A. Basic-auth mode has no per-user isolation.** With `ACP_ACCESS_CODE` set, the middleware
verifies the shared password and never sets `user_email` — so `_owner()` returns `"demo"` for
everybody and all users share one estate. That is correct for a single-tenant demo and wrong for
a hospital. Production does not use it (`ACP_ACCESS_CODE` is empty), but nothing in the code
prevents someone enabling it later.

**B. The compose stack defaults to demo mode.** `deploy/compose/docker-compose.yml` sets
`ACP_GOOGLE_CLIENT_ID: ${ACP_GOOGLE_CLIENT_ID:-}` — empty unless supplied, with the comment "No
GIS/ADC locally → runs in demo mode". **A customer-VPC deployment from that compose file would
have no per-user isolation at all**, and nothing would say so. Given ADR 0001 contemplates
customer-VPC installs, this is the one worth acting on.

## Recommendations

1. **Make isolation-off loud.** At startup, when neither `ACP_GOOGLE_CLIENT_ID` nor an Entra
   issuer is configured, log that every user shares the `demo` estate. It is the right behaviour
   for a demo and a serious misconfiguration for a tenant; the app should say which it is.
   *Cheap, and it is the difference between a documented mode and a silent one.*
2. **Consider refusing Basic-auth mode when `IS_PROD`**, the same fail-closed shape the E2E
   bypass already uses. A production deployment that collapses every user to one owner is almost
   certainly a mistake.
3. **Minor hardening:** `get_scan` fetches the row and then compares `owner_email`, rather than
   filtering in SQL. Authorisation is correct — it returns `None` — but another owner's row is
   briefly read into memory. Moving the predicate into the query costs nothing.

## What this audit does NOT cover

- **Langfuse trace contents** — whether PHI leaves the boundary via tracing. Separate item (P0.2),
  now answered in [audit-langfuse-phi.md](audit-langfuse-phi.md).
- **Blob path traversal** — `{owner}/{scan_id}/{filename}`; `filename` comes from a path parameter
  and this audit did not check normalisation. **Checked on 2026-08-09 — see below. Traversal is
  safe; a different hole was in the same route.**
- **The worker tier** — background jobs resolve owner from the job payload, not a request, and
  were not traced here. Still open.

---

# Follow-up, 2026-08-09 — one real cross-owner disclosure, in the route this audit did not list

**The conclusion above stands for what it examined, and it missed a live vulnerability.** Both
halves matter. `_owner()` is sound and no request field steers it; the exposure was one endpoint
using an unscoped lookup to build a redirect.

`GET /scans/{scan_id}/files/{filename:path}/remediated` is not in `PER_SCAN_ENDPOINTS`
(`tests/test_foreign_scan_404.py`), so nothing checked it for foreign access. It ran:

```python
urls = store.get_remediation_urls(scan_id, filename)   # NO owner predicate
...
data = blob.download_remediated(owner, ...)            # correctly scoped -> None
if urls.get("drive_write_url"):
    return RedirectResponse(urls["drive_write_url"])   # somebody else's document
```

The blob read is scoped and did its job — a foreign document is simply absent under the caller's
prefix. That is precisely what made the bug reachable: `None` fell through to a Drive mirror URL
taken from a row the caller had no right to.

**Measured, not theorised.** With the real access gate and an allow-listed non-owner:
`307 -> https://drive.google.com/file/d/PRIVATE-PHI-DOC/view`. The owner's own request succeeded in
the same run, so the fixture was not vacuous.

Severity is bounded by needing the scan's UUID, but a UUID is not an access control — it appears
in logs, traces, shared links and support tickets. And the same fall-through made the endpoint an
oracle: `307` for a real file versus `404` for an invented one told a non-owner which documents a
scan contained.

**Fixed in two independent places**, each sufficient alone and each with its own test:

1. `routes/scans.py` resolves ownership first — `get_scan(scan_id, owner=…)`, 404 as `"scan not
   found"` verbatim (`tests/test_scan_not_found_detail.py` pins that string; it also means a
   non-owner cannot distinguish a foreign scan from a nonexistent one).
2. `store.get_remediation_urls` takes an optional `owner` and filters **in SQL**, so a foreign row
   is never read into memory. Optional only so the worker tier, which has no user context, is not
   forced to invent one.

Regression tests: `tests/test_remediated_download_isolation.py` — non-vacuity, the disclosure, the
oracle, the store layer alone, and the traversal case the original audit flagged.

**Path traversal was checked and is safe.** `_blob_path` is raw f-string concatenation and the
route uses a `:path` converter, so `..` reaches the key — but Azure blob names are flat strings
and `..` is never resolved, so it addresses a different blob rather than escaping the prefix.
Pinned anyway, since that is a property of the storage backend and not of this code.

**Recommendation 1 is now implemented.** `app._announce_isolation_mode()` prints at startup
whether per-user isolation is ON, and names the reason when it is off. Recommendation 2 (refuse
Basic-auth mode when `IS_PROD`) is deliberately **not** implemented: it is the right fail-closed
default for PHI, but it can lock out a running deployment, so it should be a decision rather than
a side effect. Recommendation 3 (move `get_scan`'s owner predicate into SQL) remains open.

*Verified on the deploy script rather than assumed:* `deploy/public/deploy.sh:215,218` sets
`ACP_GOOGLE_CLIENT_ID` and `ACP_ACCESS_CODE` mutually exclusively, blanking the access code in GIS
mode. That is why production takes the branch that stamps `user_email`, and it corroborates the
live-container reading in §2.
