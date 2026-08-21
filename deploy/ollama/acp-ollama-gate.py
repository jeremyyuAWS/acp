#!/usr/bin/env python3
"""Auth-checking reverse proxy in front of Ollama (interim fix, 2026-08-21).

WHY THIS EXISTS. acp-ollama-gpu's ingress used to rely on an IP allowlist for a single address
that assumed acp-app's Consumption-plan Container Apps environment has a static outbound IP. It
does not -- Consumption environments draw from a large shared NAT pool (~300 addresses observed),
so the allowlisted address was never reliably the one traffic actually came from. Confirmed via
this app's own request log: zero incoming API calls for 3+ days while the container itself ran
healthy the whole time -- every real request was silently 403ing at the network layer, and vision
remediation degraded to "unavailable" with no visible error anywhere in ACP.

WHAT THIS IS, AND ISN'T. A stdlib-only (no pip deps, smaller image, nothing new to patch) shared-
secret gate: every request must carry X-ACP-Ollama-Secret matching ACP_OLLAMA_SHARED_SECRET or it
gets 403 before reaching Ollama. This is the FAST interim fix, not the destination -- the
architecturally correct answer is VNet-integrating acp-app's environment with a NAT Gateway so the
IP allowlist this replaces can do its job as originally intended. That needs Azure network-admin
RBAC this fix does not; a static secret is what's buildable and deployable without waiting on that.

FAILS CLOSED: refuses to start at all without a configured secret, rather than silently serving
Ollama unauthenticated. Ollama itself binds to 127.0.0.1 only (see Dockerfile.gpu) -- this gate is
the only thing listening on the externally-exposed port.

Known limitation, acceptable for an interim fix: `ollama serve` is started as a background job in
the container's startup script, not as this process's direct child, so a SIGTERM to this process
does not cleanly propagate to it. A container restart (image/revision replacement) is unaffected;
a graceful in-place drain is not — not a concern for a min-replicas=1 GPU box that's rarely scaled.
"""
import http.server
import os
import sys
import urllib.error
import urllib.request

SECRET = os.environ.get("ACP_OLLAMA_SHARED_SECRET", "")
UPSTREAM = os.environ.get("ACP_OLLAMA_UPSTREAM", "http://127.0.0.1:11500")
LISTEN_PORT = int(os.environ.get("ACP_OLLAMA_GATE_PORT", "11434"))
# Vision inference on a cold model load can run to ~280s per api/ai.py's own OLLAMA_VISION_TIMEOUT
# default (120s) plus RunPod-era headroom -- generous rather than tight, since a proxy timeout that
# fires before Ollama's own would misreport a slow-but-healthy call as a gate failure.
UPSTREAM_TIMEOUT = float(os.environ.get("ACP_OLLAMA_GATE_TIMEOUT", "280"))

_HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding", "keep-alive"}


class GateHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _deny(self, code: int, message: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(message)))
        self.end_headers()
        self.wfile.write(message)

    def _proxy(self) -> None:
        if self.headers.get("X-ACP-Ollama-Secret") != SECRET:
            self._deny(403, b'{"error":"forbidden"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(UPSTREAM + self.path, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in _HOP_BY_HOP:
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as resp:
                payload = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in _HOP_BY_HOP:
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as e:
            payload = e.read()
            self._deny(e.code, payload)
        except Exception as e:                        # upstream down/timeout — fail as a clean 502
            self._deny(502, f'{{"error":"upstream unreachable: {e}"}}'.encode())

    def do_GET(self) -> None: self._proxy()
    def do_POST(self) -> None: self._proxy()
    def do_HEAD(self) -> None: self._proxy()

    def log_message(self, fmt: str, *args) -> None:    # ship to container stdout, not devnull
        sys.stderr.write("[ollama-gate] " + (fmt % args) + "\n")


if __name__ == "__main__":
    if not SECRET:
        sys.stderr.write(
            "[ollama-gate] FATAL: ACP_OLLAMA_SHARED_SECRET is not set — refusing to start an "
            "unauthenticated gate in front of Ollama.\n")
        sys.exit(1)
    sys.stderr.write(f"[ollama-gate] listening on 0.0.0.0:{LISTEN_PORT}, forwarding to {UPSTREAM}\n")
    http.server.ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), GateHandler).serve_forever()
