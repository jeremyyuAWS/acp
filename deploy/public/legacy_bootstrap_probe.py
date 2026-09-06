"""Compact fail-closed Redis and global queue probe for the pre-readiness image."""
import json
import os
import secrets

import psycopg2
import redis


redis_url = os.environ["REDIS_URL"]
database_url = os.environ["DATABASE_URL"]
redis_client = redis.Redis.from_url(
    redis_url, socket_connect_timeout=5, socket_timeout=5, decode_responses=True
)
token = secrets.token_hex(16)
key = f"acp:deploy:legacy-bootstrap:{token}"
try:
    assert redis_client.set(key, token, ex=30)
    assert redis_client.get(key) == token
finally:
    redis_client.delete(key)

with psycopg2.connect(database_url, connect_timeout=5) as database:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FILTER (WHERE status='queued' AND COALESCE(attempts,0)=0),"
            "COUNT(*) FILTER (WHERE status='queued' AND COALESCE(attempts,0)>0),"
            "COUNT(*) FILTER (WHERE status='running') FROM jobs "
            "WHERE status IN ('queued','running')"
        )
        queued, retrying, running = (int(value or 0) for value in cursor.fetchone())

result = {"redis_write_read": True, "queued": queued, "retrying": retrying, "running": running}
print("ACP_LEGACY_BOOTSTRAP=" + json.dumps(result, separators=(",", ":"), sort_keys=True))
