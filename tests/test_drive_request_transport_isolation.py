"""Real generated Drive requests must not share httplib2 transports across threads.

No network or production data: stub only the transport's wire operation, not
the SDK service/request construction used by Discovery.
"""
import sys
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httplib2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import scanner


def test_parallel_generated_drive_requests_have_distinct_transports(monkeypatch):
    barrier = threading.Barrier(4, timeout=5)
    seen = []
    closed = []
    lock = threading.Lock()

    def wire(http, uri, method="GET", body=None, headers=None, **kwargs):
        with lock:
            seen.append(http)
        barrier.wait()
        assert headers.get("authorization") == "Bearer synthetic-token"
        return httplib2.Response({"status": "200"}), b'{"files": []}'

    monkeypatch.setattr(httplib2.Http, "request", wire)
    monkeypatch.setattr(httplib2.Http, "close", lambda http: closed.append(http))
    svc = scanner._drive_service("synthetic-token")
    # Distinct SDK requests, as in the real folder walk; sharing only the service.
    def fetch(i):
        return svc.files().list(q=f"'{i}' in parents").execute(num_retries=0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, range(4)))
    assert results == [{"files": []}] * 4
    assert len({id(http) for http in seen}) == 4, "parallel requests share an unsafe HTTP transport"
    assert all(http.timeout == scanner._DRIVE_HTTP_TIMEOUT_S for http in seen)
    assert {id(http) for http in seen} <= {id(http) for http in closed}


def test_failed_request_closes_transport_and_next_execution_is_fresh(monkeypatch):
    seen, closed = [], []
    def wire(http, *args, **kwargs):
        seen.append(http)
        if len(seen) == 1:
            raise ValueError("synthetic transport failure")
        return httplib2.Response({"status": "200"}), b'{"files": []}'
    monkeypatch.setattr(httplib2.Http, "request", wire)
    monkeypatch.setattr(httplib2.Http, "close", lambda http: closed.append(http))
    req = scanner._drive_service("synthetic-token").files().list()
    with pytest.raises(ValueError, match="synthetic transport failure"):
        req.execute(num_retries=0)
    assert req.execute(num_retries=0) == {"files": []}
    assert seen[0] is not seen[1]
    assert all(http in closed for http in seen)


def test_real_folder_walk_keeps_parallelism_without_sharing_connections(monkeypatch):
    barrier = threading.Barrier(4, timeout=5)
    seen, closed = [], []
    lock = threading.Lock()
    monkeypatch.setattr(scanner, "_DISCOVERY_WORKERS", 4)
    def wire(http, uri, method="GET", body=None, headers=None, **kwargs):
        fid = parse_qs(urlparse(uri).query)["q"][0].split("'")[1]
        with lock:
            seen.append(http)
        if fid == "root":
            files = [{"id": str(i), "name": str(i),
                      "mimeType": "application/vnd.google-apps.folder"} for i in range(4)]
        else:
            barrier.wait()  # A serial 'fix' cannot pass this test.
            files = [{"id": "file" + fid, "name": fid + ".docx",
                      "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}]
        return httplib2.Response({"status": "200"}), json.dumps({"files": files}).encode()
    monkeypatch.setattr(httplib2.Http, "request", wire)
    monkeypatch.setattr(httplib2.Http, "close", lambda http: closed.append(http))
    result = scanner._search_folder(scanner._drive_service("synthetic-token"), "root")
    assert {item["id"] for item in result} == {"file" + str(i) for i in range(4)}
    assert len({id(http) for http in seen}) == 5
    assert {id(http) for http in seen} <= {id(http) for http in closed}


def test_sdk_retry_uses_its_private_transport_then_closes_it(monkeypatch):
    seen, closed = [], []
    def wire(http, *args, **kwargs):
        seen.append(http)
        if len(seen) == 1:
            return httplib2.Response({"status": "503"}), b'{}'
        return httplib2.Response({"status": "200"}), b'{"files": []}'
    monkeypatch.setattr(httplib2.Http, "request", wire)
    monkeypatch.setattr(httplib2.Http, "close", lambda http: closed.append(http))
    req = scanner._drive_service("synthetic-token").files().list()
    req._sleep = lambda seconds: None
    assert req.execute(num_retries=1) == {"files": []}
    assert len(seen) == 2 and seen[0] is seen[1]
    assert closed == [seen[0]]


def test_explicit_transport_remains_caller_owned(monkeypatch):
    closed = []
    monkeypatch.setattr(httplib2.Http, "request", lambda *a, **k:
                        (httplib2.Response({"status": "200"}), b'{"files": []}'))
    monkeypatch.setattr(httplib2.Http, "close", lambda http: closed.append(http))
    own = httplib2.Http(timeout=10)
    req = scanner._drive_service("synthetic-token").files().list()
    assert req.execute(http=own) == {"files": []}
    assert not closed
