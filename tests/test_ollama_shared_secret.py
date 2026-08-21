"""Shared-secret auth for the GPU Ollama deployment (interim fix, 2026-08-21).

Root cause of the outage this fixes: acp-ollama-gpu's ingress relied on an IP allowlist for a
single address that assumed acp-app's Consumption-plan environment has a static outbound IP. It
does not (a large shared NAT pool instead), confirmed via Azure directly -- the allowlisted
address was not present among the environment's ~300 actual outbound IPs, and the GPU container's
own request log showed zero incoming calls for 3+ days despite the container running healthy the
whole time. Every real request was silently 403ing at the network layer.

Two halves:
  1. api/ai.py's _OLLAMA_HEADERS -- every client-side call (api/ai.py, api/app.py's pre-warm loop,
     api/providers.py's OllamaVisionProvider) sends X-ACP-Ollama-Secret when configured, and sends
     nothing extra when not (so local/CPU Ollama on localhost, which needs no auth, is unaffected).
  2. deploy/ollama/acp-ollama-gate.py -- the server-side gate, tested here directly as a real
     ThreadingHTTPServer against a real fake-upstream server, not mocked at the handler level. The
     whole point of this fix is the boundary between "has the secret" and "doesn't", and a mock of
     the handler's internals could pass while the actual HTTP behavior was wrong.
"""
from __future__ import annotations

import http.server
import importlib.util
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


# ── Client side: api/ai.py's _OLLAMA_HEADERS ──────────────────────────────────────────────────

def _reload_ai_with_secret(monkeypatch, secret):
    import importlib
    if secret is None:
        monkeypatch.delenv("ACP_OLLAMA_SHARED_SECRET", raising=False)
    else:
        monkeypatch.setenv("ACP_OLLAMA_SHARED_SECRET", secret)
    import ai
    importlib.reload(ai)
    return ai


def test_no_secret_configured_sends_no_extra_header(monkeypatch):
    """Local/CPU Ollama on localhost needs no auth -- the header must not appear at all, not
    appear empty, so a naive upstream check like `if header is not None` can't be fooled."""
    ai = _reload_ai_with_secret(monkeypatch, None)
    assert ai._OLLAMA_HEADERS == {}


def test_a_configured_secret_is_sent_as_the_exact_header(monkeypatch):
    ai = _reload_ai_with_secret(monkeypatch, "s3cr3t-value")
    assert ai._OLLAMA_HEADERS == {"X-ACP-Ollama-Secret": "s3cr3t-value"}


def test_every_real_call_site_passes_the_shared_headers(monkeypatch):
    """Guards the actual regression: a call site that forgets headers=_OLLAMA_HEADERS silently
    reverts to the exact bug this fix closes -- 403 forever, indistinguishable from 'down'."""
    src = (ACP / "api" / "ai.py").read_text()
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    calls = [l for l in body.splitlines() if "httpx.get(" in l or "httpx.post(" in l]
    assert len(calls) >= 6, "fewer Ollama call sites found than expected -- did one move?"
    # Every httpx.get/post call in this file must be followed by a headers= kwarg somewhere in
    # its own call (checked over the surrounding few lines, since calls span multiple lines).
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if "httpx.get(" in line or "httpx.post(" in line:
            window = "\n".join(lines[i:i + 8])
            assert "headers=" in window, f"no headers= kwarg near: {line.strip()}"

    for path in ("api/app.py", "api/providers.py"):
        src2 = (ACP / path).read_text()
        assert "_OLLAMA_HEADERS" in src2 or "_ai._OLLAMA_HEADERS" in src2, (
            f"{path} calls Ollama directly but never references the shared-secret headers"
        )


# ── Server side: deploy/ollama/acp-ollama-gate.py ─────────────────────────────────────────────

def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "acp_ollama_gate", ACP / "deploy" / "ollama" / "acp-ollama-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeUpstreamHandler(http.server.BaseHTTPRequestHandler):
    """Stands in for Ollama: echoes the path and whether a body was received."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        body = f'{{"path":"{self.path}"}}'.encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *a): pass


@pytest.fixture()
def gate(monkeypatch):
    """A real gate server in front of a real fake-upstream server, both on loopback."""
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    up_port = upstream.server_address[1]

    monkeypatch.setenv("ACP_OLLAMA_SHARED_SECRET", "the-real-secret")
    monkeypatch.setenv("ACP_OLLAMA_UPSTREAM", f"http://127.0.0.1:{up_port}")
    mod = _load_gate_module()

    gate_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), mod.GateHandler)
    gate_port = gate_srv.server_address[1]
    threading.Thread(target=gate_srv.serve_forever, daemon=True).start()

    yield gate_port
    gate_srv.shutdown()
    upstream.shutdown()


def _get(port, path="/api/tags", secret=None):
    headers = {"X-ACP-Ollama-Secret": secret} if secret is not None else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_a_request_with_no_secret_header_is_refused(gate):
    status, body = _get(gate, secret=None)
    assert status == 403
    assert b"forbidden" in body


def test_a_request_with_the_wrong_secret_is_refused(gate):
    status, _ = _get(gate, secret="wrong-guess")
    assert status == 403


def test_a_request_with_the_correct_secret_reaches_the_upstream(gate):
    status, body = _get(gate, path="/api/tags", secret="the-real-secret")
    assert status == 200
    assert b'"path":"/api/tags"' in body


def test_secret_reads_empty_when_unconfigured(monkeypatch):
    monkeypatch.delenv("ACP_OLLAMA_SHARED_SECRET", raising=False)
    mod = _load_gate_module()
    assert mod.SECRET == ""


def test_the_module_fails_closed_on_startup_without_a_secret():
    """Fail closed: a misconfigured deployment must not silently serve Ollama unauthenticated.
    Importing the module must NOT exit (the fixture above loads it that way for every other
    test) -- only actually running it as __main__ does, guarded by `if not SECRET: sys.exit(1)`
    before the server ever binds a port. Pinned by reading the guard out of the source rather
    than executing `python acp-ollama-gate.py` as a subprocess, which would need a free port and
    a real shutdown signal for a property that's really about the source's own control flow."""
    src = (ACP / "deploy" / "ollama" / "acp-ollama-gate.py").read_text()
    guard = src[src.index('if __name__ == "__main__":'):]
    assert "if not SECRET:" in guard
    assert "sys.exit(1)" in guard
    # The exit has to come before the server starts listening, not after.
    assert guard.index("sys.exit(1)") < guard.index("ThreadingHTTPServer")
