"""Workers share one bounded GPU allowance, with crash/clock/outage recovery."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import vision_admission as admission


@pytest.fixture(autouse=True)
def deterministic_heartbeat(monkeypatch):
    # Server time is advanced explicitly in expiry fixtures; test renewal below
    # directly rather than racing real daemon scheduling against virtual time.
    monkeypatch.setattr(admission.VisionLease, '_start_renewal', lambda self: None)


class AtomicRedis:
    """Deterministic Redis contract fixture with an independent server clock."""
    def __init__(self):
        self.now = 10_000
        self.members = {}
        self.lock = threading.Lock()
        self.fail = False

    def eval(self, script, count, key, *args):
        assert count == 1
        if self.fail:
            raise RuntimeError('redis://sensitive-secret unavailable')
        with self.lock:
            items = self.members.setdefault(key, {})
            if script == admission.RENEW_SCRIPT:
                lease_ms, token = args
                if token not in items or items[token] <= self.now:
                    return 0
                items[token] = self.now + lease_ms
                return 1
            assert script == admission.ACQUIRE_SCRIPT
            capacity, lease_ms, token = args
            for old in list(items):
                if items[old] <= self.now:
                    del items[old]
            if len(items) >= capacity:
                return 0
            items[token] = self.now + lease_ms
            return 1

    def zrem(self, key, token):
        if self.fail:
            raise RuntimeError('sensitive release failure')
        with self.lock:
            return self.members.get(key, {}).pop(token, None) is not None


def acquire(gate, endpoint='https://gpu.example', model='llava:13b', **kw):
    return gate.acquire(endpoint, model, wait_seconds=kw.get('wait', 0),
                        lease_seconds=kw.get('lease', 5))


def test_independent_worker_instances_share_one_atomic_ceiling():
    redis = AtomicRedis()
    gates = [admission.VisionAdmission(redis, capacity=2) for _ in range(20)]
    with ThreadPoolExecutor(max_workers=20) as pool:
        leases = list(pool.map(acquire, gates))
    assert sum(lease.admitted for lease in leases) == 2
    assert sum(lease.reason == 'capacity_exhausted' for lease in leases) == 18
    for lease in leases:
        lease.release()
    assert acquire(gates[0]).admitted


def test_crashed_worker_expiry_and_late_release_cannot_remove_successor():
    redis = AtomicRedis()
    gate = admission.VisionAdmission(redis)
    crashed = acquire(gate, lease=2)
    assert not acquire(gate).admitted
    redis.now += 2000
    successor = acquire(gate)
    assert successor.admitted
    crashed.release()
    assert not acquire(gate).admitted
    successor.release()
    successor.release()  # Idempotent cleanup.
    assert acquire(gate).admitted


def test_capacity_wait_has_its_own_deadline_and_can_recover():
    redis = AtomicRedis()
    now = [0.0]
    def sleep(seconds):
        now[0] += seconds
        redis.now += int(seconds * 1000)
    gate = admission.VisionAdmission(redis, clock=lambda: now[0], sleep=sleep)
    assert acquire(gate, lease=2).admitted
    exhausted = acquire(gate, wait=0.5)
    assert exhausted.reason == 'capacity_exhausted'
    assert now[0] == pytest.approx(0.5)
    assert acquire(gate, wait=2).admitted


def test_same_gpu_models_and_rotated_credentials_share_capacity_and_keys_are_private():
    redis = AtomicRedis()
    gate = admission.VisionAdmission(redis)
    endpoint = 'https://user:private-password@gpu.example'
    assert acquire(gate, endpoint=endpoint).admitted
    assert not acquire(gate, endpoint=endpoint + '/').admitted
    assert not acquire(gate, endpoint=endpoint, model='moondream').admitted
    assert not acquire(gate, endpoint='https://rotated:different@gpu.example:443/?token=new#x').admitted
    assert acquire(gate, endpoint='https://other.example').admitted
    assert 'private-password' not in repr(redis.members)


def test_configured_outage_fails_closed_without_provider_failure():
    redis = AtomicRedis()
    redis.fail = True
    lease = acquire(admission.VisionAdmission(redis))
    assert not lease.admitted
    assert lease.reason == 'coordination_unavailable'
    assert 'sensitive' not in repr(lease)
    assert not acquire(admission.VisionAdmission()).admitted
    local = acquire(admission.VisionAdmission(required=False))
    assert local.admitted and local.reason == 'local_only'


def test_release_outage_is_bounded_and_recovers_by_expiry():
    redis = AtomicRedis()
    gate = admission.VisionAdmission(redis)
    lease = acquire(gate, lease=1)
    redis.fail = True
    assert lease.release() is False
    redis.fail = False
    assert not acquire(gate).admitted
    redis.now += 1000
    assert acquire(gate).admitted


def test_heartbeat_extends_only_owned_live_lease_and_stops_on_release():
    redis = AtomicRedis()
    gate = admission.VisionAdmission(redis)
    lease = acquire(gate, lease=2)
    redis.now += 1500
    assert lease.renew()
    redis.now += 1500
    assert not acquire(gate).admitted  # Original lease would have expired.
    lease.release()
    assert not lease.renew()
    assert acquire(gate).admitted


def test_heartbeat_cannot_resurrect_expired_token_or_replace_successor():
    redis = AtomicRedis()
    gate = admission.VisionAdmission(redis)
    expired = acquire(gate, lease=1)
    redis.now += 1000
    successor = acquire(gate)
    assert not expired.renew()
    assert expired.ownership_lost
    assert not acquire(gate).admitted
    successor.release()


def test_transient_renewal_outage_can_recover_before_expiry():
    redis = AtomicRedis()
    lease = acquire(admission.VisionAdmission(redis), lease=2)
    redis.fail = True
    assert not lease.renew() and not lease.ownership_lost
    redis.fail = False
    redis.now += 500
    assert lease.renew()
    lease.release()


@pytest.mark.parametrize('url,aca,required', [('', '', False), ('', 'acp-assess', True),
                                          ('redis://configured', '', True)])
def test_environment_requires_coordination_for_aca_or_configured_redis(monkeypatch,
                                                                     url, aca, required):
    monkeypatch.setattr(admission, '_CONFIGURED', None)
    monkeypatch.setenv('REDIS_URL', url)
    monkeypatch.setenv('CONTAINER_APP_NAME', aca)
    monkeypatch.setenv('ACP_VISION_SHARED_MAX_CONCURRENCY', 'invalid')
    gate = admission.configured_admission()
    assert gate.required is required
    assert gate.capacity == 1
    assert admission.configured_admission() is gate
