"""Shared, expiring GPU admission; no document data or endpoint credentials enter Redis.

The caller retains its process-local ceiling and releases this lease in ``finally``.
Lease duration MUST exceed the entire admitted provider request deadline. Capacity
exhaustion and coordination failure are not provider failures or circuit evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import threading
import time
import uuid
from urllib.parse import urlsplit


# Redis server time avoids clock skew between workers. A unique token prevents an
# expired worker from releasing its successor's slot. Atomic prune/count/add means
# all replicas observe one ceiling, rather than each receiving its own allowance.
ACQUIRE_SCRIPT = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[3])
local ttl = tonumber(ARGV[2]) + 1000
if redis.call('PTTL', KEYS[1]) < ttl then
  redis.call('PEXPIRE', KEYS[1], ttl)
end
return 1
"""

RENEW_SCRIPT = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local expiry = redis.call('ZSCORE', KEYS[1], ARGV[2])
if not expiry or tonumber(expiry) <= now then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[1]), ARGV[2])
local ttl = tonumber(ARGV[1]) + 1000
if redis.call('PTTL', KEYS[1]) < ttl then redis.call('PEXPIRE', KEYS[1], ttl) end
return 1
"""


@dataclass
class VisionLease:
    admitted: bool
    reason: str  # admitted, local_only, capacity_exhausted, coordination_unavailable
    client: object | None = None
    key: str = ""
    token: str = ""
    lease_ms: int = 0
    ownership_lost: bool = False
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def renew(self) -> bool:
        """Renew only a live owned token; never resurrect an expired GPU slot."""
        if self.client is None or not self.token or self._stop.is_set():
            return False
        try:
            renewed = bool(self.client.eval(RENEW_SCRIPT, 1, self.key,
                                            self.lease_ms, self.token))
        except Exception:
            # A brief outage can recover before TTL. Do not recreate a missing key.
            return False
        if not renewed:
            self.ownership_lost = True
            self._stop.set()
        return renewed

    def _start_renewal(self):
        def heartbeat():
            last_success = time.monotonic()
            interval = max(0.1, self.lease_ms / 3000)
            while not self._stop.wait(interval):
                if self.renew():
                    last_success = time.monotonic()
                elif time.monotonic() - last_success >= self.lease_ms / 1000:
                    self.ownership_lost = True
                    self._stop.set()
        threading.Thread(target=heartbeat, name='vision-lease-heartbeat', daemon=True).start()

    def release(self) -> bool:
        """Best effort only: a failed release is recovered by lease expiration."""
        self._stop.set()
        if self.client is None or not self.token:
            return True
        token, self.token = self.token, ""
        try:
            self.client.zrem(self.key, token)
            return True
        except Exception:
            # Never leak Redis URLs, credentials, or provider input in diagnostics.
            return False


def admission_key(endpoint: str, model: str) -> str:
    # All models on one endpoint contend for its GPU. Authentication rotation must
    # not create another allowance; neither credentials nor query strings identify
    # capacity. Paths distinguish separately deployed endpoints behind one host.
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or '').lower()
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port
    if port is not None and not ((parsed.scheme.lower() == 'https' and port == 443)
                                 or (parsed.scheme.lower() == 'http' and port == 80)):
        host += ':' + str(port)
    canonical = parsed.scheme.lower() + '://' + host + parsed.path.rstrip('/')
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return "acp:vision:admission:v1:" + digest


class VisionAdmission:
    def __init__(self, client=None, *, capacity=1, required=True,
                 clock=time.monotonic, sleep=time.sleep, poll_seconds=0.1):
        self.client = client
        self.capacity = max(1, int(capacity))
        self.required = required
        self.clock = clock
        self.sleep = sleep
        self.poll_seconds = max(0.01, float(poll_seconds))

    def acquire(self, endpoint: str, model: str, *, wait_seconds: float,
                lease_seconds: float) -> VisionLease:
        if self.client is None:
            return VisionLease(not self.required,
                               "coordination_unavailable" if self.required else "local_only")
        deadline = self.clock() + max(0.0, float(wait_seconds))
        token = uuid.uuid4().hex
        key = admission_key(endpoint, model)
        lease_ms = max(1000, int(float(lease_seconds) * 1000))
        while True:
            try:
                admitted = self.client.eval(ACQUIRE_SCRIPT, 1, key,
                                            self.capacity, lease_ms, token)
            except Exception:
                return VisionLease(False, "coordination_unavailable")
            if admitted:
                lease = VisionLease(True, "admitted", self.client, key, token, lease_ms)
                lease._start_renewal()
                return lease
            remaining = deadline - self.clock()
            if remaining <= 0:
                return VisionLease(False, "capacity_exhausted")
            self.sleep(min(self.poll_seconds, remaining))


_CONFIG_LOCK = threading.Lock()
_CONFIGURED = None


def configured_admission() -> VisionAdmission:
    """Redis configured => shared admission required; ACA never silently goes local.

Standalone developer runs without Redis retain their local gate. This client is
separate from job-state Redis so a GPU queue cannot reconfigure that dependency.
"""
    global _CONFIGURED
    with _CONFIG_LOCK:
        if _CONFIGURED is not None:
            return _CONFIGURED
        url = os.environ.get("REDIS_URL", "").strip()
        required = bool(url or os.environ.get("CONTAINER_APP_NAME"))
        try:
            capacity = max(1, int(os.environ.get("ACP_VISION_SHARED_MAX_CONCURRENCY", "1")))
        except ValueError:
            capacity = 1
        client = None
        if url:
            try:
                import redis
                client = redis.Redis.from_url(url, decode_responses=True,
                                              socket_timeout=1, socket_connect_timeout=1,
                                              retry_on_timeout=False)
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Vision coordinator configuration unavailable; shared dispatch remains disabled")
        _CONFIGURED = VisionAdmission(client, capacity=capacity, required=required)
        return _CONFIGURED
