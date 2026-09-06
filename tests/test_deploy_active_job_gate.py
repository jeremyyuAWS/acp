"""Production deploys must not replace queue workers underneath live customer work."""
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]


def test_readyz_exposes_only_aggregate_durable_queue_activity():
    text = (ROOT / "api/routes/system.py").read_text()
    assert "core.store.job_stats(owner=None)" in text
    assert '"active"' in text and '"available"' in text
    assert '"payload"' not in text[text.index("_queue_stats ="):text.index("except Exception as exc", text.index("_queue_stats ="))]


def test_redeploy_refuses_when_queue_state_is_unknown_or_active():
    text = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = text.index('READY_BEFORE=')
    first_mutation = text.index('if [ "$BG" = 1 ]', gate)
    block = text[gate:first_mutation]
    assert "QUEUE_AVAILABLE" in block
    assert "ACTIVE_JOBS" in block
    assert "die " in block
    assert "ACP_DEPLOY_WITH_ACTIVE_JOBS" in block


def test_legacy_bootstrap_is_provenance_locked_and_checks_all_live_work():
    text = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = text.index('if [ "$REDIS_REPORTED" != true ]')
    normal = text.index('else\n  [ "$REDIS_CONFIGURED"', gate)
    block = text[gate:normal]
    assert 'LEGACY_GATE_COMMIT="e3689c2ce4d801e0ea08482bbc72ba9076ad4f18"' in block
    assert 'git merge-base --is-ancestor "$LIVE_SHA" "${LEGACY_GATE_COMMIT}^"' in block
    assert 'git merge-base --is-ancestor "$LEGACY_GATE_COMMIT" "$PIN"' in block
    assert "legacy_bootstrap_probe.py" in block
    assert "BOOTSTRAP_QUEUED + BOOTSTRAP_RETRYING + BOOTSTRAP_RUNNING" in block
    assert '[ "$ACTIVE_JOBS" = 0 ]' in block
    assert "one-time cutover requires a globally empty queue" in block


def test_legacy_probe_write_reads_redis_and_counts_queue_states(monkeypatch, capsys):
    class FakeRedis:
        def set(self, key, value, ex):
            self.value = value
            return ex == 30

        def get(self, key):
            return self.value

        def delete(self, key):
            return 1

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, query):
            assert "status = 'running'" in query
            assert "COALESCE(attempts, 0) = 0" in query
            assert "COALESCE(attempts, 0) > 0" in query

        def fetchone(self):
            return 2, 3, 4

    class FakeDatabase:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setenv("REDIS_URL", "redis://shared")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setattr("redis.Redis.from_url", lambda *_args, **_kwargs: FakeRedis())
    monkeypatch.setattr("psycopg2.connect", lambda *_args, **_kwargs: FakeDatabase())

    runpy.run_path(str(ROOT / "deploy/public/legacy_bootstrap_probe.py"))

    output = capsys.readouterr().out
    assert 'ACP_LEGACY_BOOTSTRAP={"queued":2,"redis_write_read":true,"retrying":3,"running":4}' in output


def test_emergency_override_is_explicitly_manual_in_the_workflow():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "deploy_with_active_jobs:" in workflow
    assert "ACP_DEPLOY_WITH_ACTIVE_JOBS:" in workflow
    assert "Emergency only" in workflow
