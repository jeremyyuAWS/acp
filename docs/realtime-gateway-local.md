# Canonical realtime gateway (local shadow service)

This is an additive, default-off service. It is not mounted by ACP's API, referenced by the
browser, or enabled in a deployment manifest. Existing production SSE routes remain unchanged.

The gateway consumes only the canonical owner-scoped streams defined in
`api/realtime_events.py`. Redis rows use fields `event` and `event_id`; SSE delivery binds the
Redis row ID as `stream_id` and uses the named `acp-event` frame. Resume replay is limited to 500
events. Missing, malformed, stale, ahead, or over-limit cursors reconcile instead of guessing.

Its temporary local HMAC credential carries an owner email, which is immediately converted to the
contract's non-reversible `owner_scope`. This authentication is intentionally not browser wiring;
a later slice must adapt ACP's existing signed-in owner before any route is mounted.

For local development only, set `ACP_REALTIME_V1_ENABLED=true`, a Redis URL, and an
`ACP_REALTIME_V1_AUTH_SECRET` of at least 32 characters, then run `python -m realtime_gateway`.
