"""A vision call that fails must say WHICH way it failed.

Three genuinely different outcomes used to collapse into one indistinguishable `text=None,
ok=False`, with the exception swallowed by a bare `except Exception`:

  1. the transport threw           — connection refused / DNS / TLS / timeout
  2. the endpoint answered non-2xx — up, but the request or the deployment is wrong
  3. HTTP 200 with an EMPTY body   — transport and model are both healthy; the model answered
                                     nothing to this prompt

Case 3 was live in production on 2026-07-31 (moondream, `{"response": "", "done_reason":
"stop"}`), and identifying it needed a hand-rolled httpx.post inside the container because the
app recorded nothing about which case it was. These tests pin that each case is now separable
from the other two — in the log line and in the `reason` on the result — for every adapter,
since the same bare-except shape was in all three.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


class _Resp:
    """Enough of an httpx.Response for the adapters: a status, a JSON body, a text body."""

    def __init__(self, payload, *, status=200, text=None):
        self._payload = payload
        self.status_code = status
        self.text = text if text is not None else str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _StatusError(f"Server error '{self.status_code}'", response=self)

    def json(self):
        return self._payload


class _StatusError(Exception):
    """Shaped like httpx.HTTPStatusError: it carries the response it came from."""

    def __init__(self, msg, *, response):
        super().__init__(msg)
        self.response = response


def _post(monkeypatch, fn):
    import httpx
    monkeypatch.setattr(httpx, "post", fn)


# The three adapters, each built with whatever its constructor needs. Every one of them had the
# same bare-except, so every one of them is held to the same contract here.
def _ollama():
    return providers.OllamaVisionProvider("http://localhost:11434", "moondream")


def _azure():
    return providers.AzureOpenAIVisionProvider("https://acme.openai.azure.com", "gpt-4o", "KEY")


def _runpod():
    return providers.RunPodServerlessVisionProvider("endpoint123", "KEY", model="qwen2.5-vl")


ADAPTERS = [
    pytest.param(_ollama, {"response": "A bar chart of Q4 revenue"}, {"response": ""},
                 id="ollama"),
    pytest.param(_azure,
                 {"choices": [{"message": {"content": "A bar chart of Q4 revenue"}}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                 {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]},
                 id="azure_openai"),
    pytest.param(_runpod,
                 {"choices": [{"message": {"content": "A bar chart of Q4 revenue"}}]},
                 {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
                 id="runpod_serverless"),
]


@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_success_reports_reason_ok(monkeypatch, build, good, empty):
    _post(monkeypatch, lambda *a, **k: _Resp(good))
    res = build().generate("describe", b"IMG")
    assert res["ok"] is True
    assert res["reason"] == providers.REASON_OK
    assert res["text"] == "A bar chart of Q4 revenue"


# ── Case 1: the transport threw ────────────────────────────────────────────────

@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_transport_throw_is_named_and_logged(monkeypatch, capsys, build, good, empty):
    def boom(*a, **k):
        raise ConnectionRefusedError("[Errno 61] Connection refused")

    _post(monkeypatch, boom)
    res = build().generate("describe", b"IMG")

    assert res["ok"] is False and res["text"] is None          # still degrades, never raises
    assert res["reason"] == providers.REASON_TRANSPORT
    out = capsys.readouterr().out
    # The exception TEXT is the diagnosis here — there is no HTTP response to read a status
    # from, so swallowing it leaves literally nothing to go on.
    assert "Connection refused" in out
    assert "ConnectionRefusedError" in out


@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_transport_failure_log_is_one_line(monkeypatch, capsys, build, good, empty):
    """Container Apps stores one row per LINE, so a multi-line diagnostic is only findable by
    whichever line the operator happened to search for."""
    def boom(*a, **k):
        raise RuntimeError("first line\nsecond line\nthird line")

    _post(monkeypatch, boom)
    build().generate("describe", b"IMG")
    out = capsys.readouterr().out.rstrip("\n")
    assert out and "\n" not in out


# ── Case 2: the endpoint answered non-2xx ──────────────────────────────────────

@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_non_200_records_status_and_logs_body(monkeypatch, capsys, build, good, empty):
    body = '{"error":"model \'moondream\' not found, try pulling it first"}'
    _post(monkeypatch, lambda *a, **k: _Resp({}, status=404, text=body))
    res = build().generate("describe", b"IMG")

    assert res["ok"] is False and res["text"] is None
    # The status is ON the row, not only in the log — a 404 (wrong model/deployment) and a 401
    # (bad key) are different fixes and `reason LIKE 'http_%'` still groups them.
    assert res["reason"] == "http_404"
    out = capsys.readouterr().out
    assert "HTTP 404" in out
    assert "not found, try pulling it first" in out            # the body says what to do


@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_error_body_is_bounded_and_single_line(monkeypatch, capsys, build, good, empty):
    """An error body can be a whole HTML page; the useful part is always at the front."""
    huge = "<html>\n" + ("x" * 20_000) + "\n</html>"
    _post(monkeypatch, lambda *a, **k: _Resp({}, status=502, text=huge))
    res = build().generate("describe", b"IMG")

    assert res["reason"] == "http_502"
    out = capsys.readouterr().out.rstrip("\n")
    assert "\n" not in out
    assert len(out) < 1000                                     # bounded, not the whole page
    assert "…" in out                                          # and says it was truncated


@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_unreadable_error_body_does_not_mask_the_status(monkeypatch, capsys, build, good, empty):
    """A second failure on the failure path must not hide the first."""
    class _Hostile(_Resp):
        @property
        def text(self):
            raise RuntimeError("body stream already consumed")

        @text.setter
        def text(self, v):
            pass

    _post(monkeypatch, lambda *a, **k: _Hostile({}, status=500))
    res = build().generate("describe", b"IMG")
    assert res["reason"] == "http_500"
    assert "HTTP 500" in capsys.readouterr().out


# ── Case 3: HTTP 200 and the model said nothing ────────────────────────────────

@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_empty_200_is_its_own_reason_not_a_transport_error(monkeypatch, capsys, build, good, empty):
    """The production case. Nothing raised, nothing is misconfigured, and the old code reported
    it identically to a dead endpoint — which is what sent the investigation at Ollama."""
    _post(monkeypatch, lambda *a, **k: _Resp(empty))
    res = build().generate("describe", b"IMG")

    assert res["ok"] is False and res["text"] is None
    assert res["reason"] == providers.REASON_EMPTY
    assert res["reason"] != providers.REASON_TRANSPORT
    out = capsys.readouterr().out
    assert "empty" in out.lower()


def test_empty_200_logs_ollamas_done_reason(monkeypatch, capsys):
    """`done_reason` is what separates 'the model declined' from 'the model was truncated', and
    it is the exact field the container reproduction had to go and read by hand."""
    _post(monkeypatch, lambda *a, **k: _Resp({"response": "", "done_reason": "stop",
                                              "eval_count": 0}))
    _ollama().generate("describe", b"IMG")
    out = capsys.readouterr().out
    assert "done_reason='stop'" in out
    assert "eval_count=0" in out


def test_whitespace_only_reply_counts_as_empty(monkeypatch):
    _post(monkeypatch, lambda *a, **k: _Resp({"response": "   \n  "}))
    res = _ollama().generate("describe", b"IMG")
    assert res["ok"] is False and res["reason"] == providers.REASON_EMPTY


# ── The three are actually distinguishable from each other ─────────────────────

def test_the_three_cases_produce_three_different_reasons(monkeypatch):
    """The whole point: one `ok=False` for three causes is what made this expensive to find."""
    def _reason_for(fake_post):
        _post(monkeypatch, fake_post)
        return _ollama().generate("d", b"IMG")["reason"]

    def _throw(*a, **k):
        raise RuntimeError("connection refused")

    reasons = {
        _reason_for(_throw),
        _reason_for(lambda *a, **k: _Resp({}, status=503, text="upstream unavailable")),
        _reason_for(lambda *a, **k: _Resp({"response": ""})),
    }
    assert len(reasons) == 3


# ── The adapters still honour the seam's own contract ──────────────────────────

@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_adapters_still_never_raise(monkeypatch, build, good, empty):
    def boom(*a, **k):
        raise RuntimeError("anything at all")

    _post(monkeypatch, boom)
    res = build().generate("describe", b"IMG")                 # must not propagate
    assert res["ok"] is False


@pytest.mark.parametrize("build,good,empty", ADAPTERS)
def test_result_keys_are_unchanged_plus_reason(monkeypatch, build, good, empty):
    _post(monkeypatch, lambda *a, **k: _Resp(good))
    res = build().generate("describe", b"IMG")
    # prompt_tokens/completion_tokens joined the normalized result in the Langfuse audit N1 change,
    # so cloud generations carry real `usage` — counts only, never any prompt/completion text.
    assert set(res) == {"text", "model", "provider", "zone", "latency_ms", "ok", "cost_usd",
                        "reason", "prompt_tokens", "completion_tokens"}


def test_azure_cost_still_computed_from_real_usage(monkeypatch):
    """The refactor moved the cost maths out of the try block — it must still run."""
    _post(monkeypatch, lambda *a, **k: _Resp(
        {"choices": [{"message": {"content": "A bar chart of Q4 revenue"}}],
         "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}}))
    res = _azure().generate("describe", b"IMG")
    assert res["cost_usd"] == pytest.approx(12.50)             # gpt-4o: 2.50 in + 10.00 out


def test_runpod_cost_still_computed_from_execution_time(monkeypatch):
    _post(monkeypatch, lambda *a, **k: _Resp(
        {"choices": [{"message": {"content": "A bar chart of Q4 revenue"}}],
         "executionTime": 4000}))
    p = providers.RunPodServerlessVisionProvider("e", "K", cost_per_sec=0.001)
    assert p.generate("d", b"IMG")["cost_usd"] == pytest.approx(0.004)


def test_no_secret_reaches_the_log(monkeypatch, capsys):
    """The failure log names the endpoint, which for Azure is a URL — the key rides in a header
    and must not be anywhere near it."""
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    _post(monkeypatch, boom)
    providers.AzureOpenAIVisionProvider(
        "https://acme.openai.azure.com", "gpt-4o", "sk-SUPER-SECRET").generate("d", b"IMG")
    providers.RunPodServerlessVisionProvider("e", "rp-SUPER-SECRET").generate("d", b"IMG")
    out = capsys.readouterr().out
    assert "SUPER-SECRET" not in out
