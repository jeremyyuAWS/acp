# ADR 0014 — Keep long-running scans authenticated (Drive token refresh)

Status: Accepted (Tier 1 shipped); Tier 2 (offline refresh) Proposed
Date: 2026-07-09

## Context

Drive scans authenticate with a per-user Google Identity Services (GIS) **access token**
passed as `x-drive-token`. GIS access tokens are short-lived (~1h) and, in the implicit
token flow the app uses, carry **no refresh token** — so the backend cannot refresh them
(`scanner._drive_service` / `handlers._drive_client` deliberately set a fake expiry and
never attempt the impossible refresh).

The fan-out scan captures the token once at kickoff (`register_scan_tokens`) and each
`scan_file` / `scan_batch` worker reads it from the ephemeral per-scan token store. On an
estate large enough that the scan runs **longer than the token's ~1h life**, the token
expires mid-run and every remaining file 401s → the tail of the scan is recorded as
`error` ("Drive authorization expired mid-scan"; audit P0 #2, already classified). Re-running
is cheap (ADR 0011 incremental fingerprinting skips already-scanned files) but not seamless.

Two facts make a clean fix possible without a heavyweight OAuth redesign:
1. The frontend GIS token client can **silently re-mint** an access token
   (`requestAccessToken({ prompt: '' })`) as long as the Google session is valid.
2. Scan workers re-read the token from the store on **every job**, so an in-flight update
   is picked up by subsequent batches.

## Decision

**Tier 1 — frontend keep-alive (shipped):** while a scan is running, the frontend silently
re-mints the Drive token every 20 min and pushes it to the backend, which updates the
running scan's token in the store. Subsequent worker jobs use the fresh token, so scans that
outlast the original token stay authenticated (as long as the tab stays open).

- Backend: `POST /scans/{sid}/drive-token` (owner-checked) → `register_scan_tokens(sid,
  drive=<x-drive-token>)`. Additive; no change to existing behaviour.
- Frontend: `driveAuth.refreshDriveToken()` (a shared, lazily-inited GIS token client,
  independent of the picker components) + an App-level 20-min interval that, when
  `GET /scans/active` shows a running scan, refreshes and POSTs the token. Best-effort and
  GIS-gated — a no-op without `VITE_GOOGLE_CLIENT_ID`, so it can never break a scan.

Chosen because it fits the existing architecture (frontend already silent-refreshes; backend
already has a per-scan token store), needs no new OAuth client secret, and touches no
security-sensitive server code.

**Tier 2 — server-side offline refresh (proposed, the complete fix):** move Drive auth to the
GIS **authorization-code flow with `access_type=offline`**, exchange the code server-side (needs
a `GOOGLE_CLIENT_SECRET`) for a **refresh token**, persist it, and build
`google.oauth2.credentials.Credentials` **with** the refresh token + token URI + client
id/secret so `google-auth` auto-refreshes on expiry. This covers the case Tier 1 cannot — a
scan running for hours with the **tab closed**. Gated because it requires a client secret, a
code-exchange endpoint, secure at-rest storage of refresh tokens, and an auth/security review.

## Consequences

- **Tier 1:** long scans survive token expiry while the initiating tab is open — the common
  large-estate case. Cross-replica correctness depends on the token store being shared
  (Redis; ADR 0013 §2) — with the in-memory fallback the refresh must land on the same
  replica the workers run on (true at single-replica demo scale).
- **Tier 1 limitation (honest):** if the user closes the tab, no keep-alive runs and a
  multi-hour scan can still lose its token → the graceful "sign in & re-run" path (with
  incremental skip) remains the fallback. Tier 2 removes this.
- No change to the `/api/v1` shape beyond the additive endpoint; no storage-schema change;
  tokens still live only in the ephemeral store, never the durable jobs table (audit P1 scrub
  stands).
- **Verification:** the backend endpoint is unit-testable; the GIS silent-refresh path can only
  be exercised against a live Google client in a browser — validate it in the cloud acceptance
  run (scan a >1h estate, confirm the tail no longer errors).
