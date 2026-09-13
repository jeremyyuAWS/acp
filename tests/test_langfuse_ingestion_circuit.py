"""SDK queue flush can succeed even when ingestion failed; observe actual HTTP outcomes."""
import httpx
import pytest
import lf


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in ('_ingestion_failures', '_ingestion_successes', '_ingestion_consecutive_failures',
                 '_ingestion_skipped'):
        monkeypatch.setattr(lf, name, 0)
    monkeypatch.setattr(lf, '_ingestion_retry_mono', 0.0)
    monkeypatch.setattr(lf, '_ingestion_last_error', None)
    monkeypatch.setattr(lf, '_ingestion_last_error_at', None)


def test_http_500_opens_circuit_without_delaying_or_queueing_new_observations(monkeypatch):
    calls = []
    inner = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500))
    transport = lf._ingestion_transport(inner)
    transport.handle_request(httpx.Request('POST', 'https://telemetry.invalid/ingest'))
    monkeypatch.setattr(lf, '_ENABLED', True)
    monkeypatch.setattr(lf, '_client', object())
    assert lf.client() is None
    assert lf.exporter_health()['state'] == 'degraded'
    assert lf.exporter_health()['ingestion_last_error'] == 'http_500'
    with pytest.raises(httpx.ConnectError):
        transport.handle_request(httpx.Request('POST', 'https://telemetry.invalid/ingest'))
    assert len(calls) == 1
    assert lf.exporter_health()['telemetry_calls_skipped'] == 1


def test_connection_failure_is_sanitized_and_success_after_cooldown_recovers(monkeypatch):
    def fail(request):
        raise httpx.ConnectError('secret endpoint and document content', request=request)
    transport = lf._ingestion_transport(httpx.MockTransport(fail))
    with pytest.raises(httpx.ConnectError, match='Telemetry endpoint unavailable'):
        transport.handle_request(httpx.Request('POST', 'https://telemetry.invalid/ingest'))
    assert lf.exporter_health()['ingestion_last_error'] == 'connection_error'
    monkeypatch.setattr(lf, '_ingestion_retry_mono', 0.0)
    transport.inner = httpx.MockTransport(lambda request: httpx.Response(200))
    transport.handle_request(httpx.Request('POST', 'https://telemetry.invalid/ingest'))
    assert lf.exporter_health()['ingestion_successes'] == 1
    assert not lf.exporter_health()['ingestion_circuit_open']
    assert lf._ingestion_consecutive_failures == 0


def test_sdk_uses_one_attempt_short_timeout_and_bounded_export_thread(monkeypatch):
    import langfuse
    seen = {}
    monkeypatch.setattr(lf, '_ENABLED', True)
    monkeypatch.setattr(lf, '_client', None)
    monkeypatch.setattr(langfuse, 'Langfuse', lambda **options: seen.update(options) or object())
    lf.client()
    assert seen['max_retries'] == 1
    assert seen['timeout'] == 2
    assert seen['threads'] == 1
    seen['httpx_client'].close()


def test_sdk_repeated_errors_are_bounded_and_content_free(monkeypatch):
    import logging
    logger = logging.getLogger('langfuse')
    monkeypatch.setattr(lf, '_sdk_error_filter', None)
    lf._bound_sdk_error_logging()
    error_filter = lf._sdk_error_filter
    try:
        passed = []
        for _ in range(16):
            record = logging.LogRecord('langfuse', logging.ERROR, '', 0, 'secret payload', (), None)
            if error_filter.filter(record):
                passed.append(record.getMessage())
        assert len(passed) == 5
        assert all('secret' not in message for message in passed)
    finally:
        logger.removeFilter(error_filter)


@pytest.mark.parametrize('reason,expected', [('http_401', 'http_401'), ('connection_error', 'connection_error'), ('secret payload', 'sdk_error')])
def test_worker_sdk_log_carries_only_sanitized_transport_reason(monkeypatch, reason, expected):
    import logging
    monkeypatch.setattr(lf, '_ingestion_last_error', reason)
    monkeypatch.setattr(lf, '_sdk_error_filter', None)
    logger = logging.getLogger('langfuse')
    lf._bound_sdk_error_logging()
    try:
        record = logging.LogRecord('langfuse', logging.ERROR, '', 0, 'secret payload', (), None)
        assert lf._sdk_error_filter.filter(record)
        assert 'reason=' + expected in record.getMessage()
        assert 'secret' not in record.getMessage()
    finally:
        logger.removeFilter(lf._sdk_error_filter)


@pytest.mark.parametrize('kind,expected', [('tls', 'tls_error'), ('dns', 'dns_error'), ('timeout', 'timeout_error')])
def test_transport_classifies_safe_network_error_type_without_exception_content(kind, expected):
    import socket
    import ssl
    cause = {'tls': ssl.SSLError('secret endpoint'), 'dns': socket.gaierror('secret endpoint'), 'timeout': TimeoutError('secret endpoint')}[kind]
    def fail(request):
        raise httpx.ConnectError('secret payload', request=request) from cause
    transport = lf._ingestion_transport(httpx.MockTransport(fail))
    with pytest.raises(httpx.ConnectError, match='Telemetry endpoint unavailable'):
        transport.handle_request(httpx.Request('POST', 'https://telemetry.invalid/ingest'))
    assert lf.exporter_health()['ingestion_last_error'] == expected
