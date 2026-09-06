"""One-release deploy probe executed inside the live, pre-readiness ACP container.

The caller transmits this file to the existing container as base64, so it does not depend on
the old image already containing the fix.  Output is deliberately one aggregate JSON record:
no URLs, credentials, job identifiers, owners, or payloads cross the exec boundary.
"""
import json
import os
import secrets

import psycopg2
import redis


redis_url = os.environ.get("REDIS_URL", "").strip()
database_url = os.environ.get("DATABASE_URL", "").strip()
if not redis_url or not database_url:
    raise RuntimeError("shared Redis and PostgreSQL must both be configured")

# A ping can succeed against a read-only or incorrectly permissioned endpoint.  Exercise the
# operation ACP actually needs for shared scan state, with a short-lived namespaced value.
redis_client = redis.Redis.from_url(
    redis_url,
    socket_connect_timeout=5,
    socket_timeout=5,
    decode_responses=True,
)
token = secrets.token_hex(16)
key = f"acp:deploy:legacy-bootstrap:{token}"
try:
    if not redis_client.set(key, token, ex=30):
        raise RuntimeError("Redis rejected the bootstrap write")
    if redis_client.get(key) != token:
        raise RuntimeError("Redis bootstrap read did not match its write")
finally:
    redis_client.delete(key)

with psycopg2.connect(database_url, connect_timeout=5) as database:
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'queued' AND COALESCE(attempts, 0) = 0),
              COUNT(*) FILTER (WHERE status = 'queued' AND COALESCE(attempts, 0) > 0),
              COUNT(*) FILTER (WHERE status = 'running')
            FROM jobs
            WHERE status IN ('queued', 'running')
            """
        )
        queued, retrying, running = (int(value or 0) for value in cursor.fetchone())

print(
    "ACP_LEGACY_BOOTSTRAP="
    + json.dumps(
        {
            "redis_write_read": True,
            "queued": queued,
            "retrying": retrying,
            "running": running,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
)
