"""AI provider adapter seam (ADR 0019 Phase 1, §1).

The gateway's provider abstraction for the VISION path — the one place a cloud model ever
earns its keep (complex charts a local captioner can't ground, ADR 0019 §3c). Text
explanations stay local-Ollama-only by design (they need no cloud), so this seam covers
`describe_image` / `describe_image_structured` / `validate_alt_text`, which all funnel through
`ai._vision_generate`.

A provider is a small object with a uniform `generate(prompt, image_bytes, *, model, timeout)`
that returns a normalized result dict — never raises, degrades to `ok=False`. `ai.py` keeps the
prompt building, the honesty/cleaning guard, and the Langfuse+ai_calls trace; the provider owns
only the transport + its own cost/zone metadata. Callers of `ai.*` are untouched (rule 4).

Slice 1 ships only the Ollama adapter (keyless, local, $0) wired behind the selector, so
behaviour is byte-for-byte what the inline call did. Cloud adapters (Azure OpenAI first) drop in
at `active_vision_provider()` behind the acceptance policy in a later slice — the assistant never
handles a key; an admin enters it in the product Settings UI and it is stored as a secret ref.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

# The cloud providers the gateway knows how to configure. Slice 2 stores config for all of them;
# slice 3 wires the Azure OpenAI *adapter* first (the enterprise-safe default). Ollama is the
# built-in local default and needs no key, so it is not in this table.
CLOUD_PROVIDERS = ("azure_openai", "openai", "anthropic", "gemini", "bedrock")


def zone_for_url(base_url: str) -> str:
    """'local' when the endpoint is on your own infrastructure (localhost / private ranges /
    internal DNS) — no document leaves your network — else 'cloud'. The SINGLE source of truth for
    the governance zone: `ai.provenance()` calls this rather than reimplementing the test, so
    `/config` and the per-call trace can never disagree about whether a document left the network."""
    host = (urlparse(base_url or "").hostname or "").lower()
    local = (
        host in ("localhost", "127.0.0.1", "::1", "")
        or host.endswith(".internal") or ".internal." in host
        or host.endswith(".local")
        or host.startswith("10.") or host.startswith("192.168.")
        or any(host.startswith(f"172.{n}.") for n in range(16, 32))
    )
    return "local" if local else "cloud"


# ── Why a vision call ended the way it did ─────────────────────────────────────
# A vision call has three distinct failure modes and they need three different fixes:
#
#   1. the transport threw          → connection refused / DNS / TLS / timeout — the endpoint
#                                     is wrong, down, or slower than the timeout
#   2. the endpoint answered non-2xx → the endpoint is up; the request or the deployment is
#                                     wrong (model not pulled, bad key, wrong route)
#   3. HTTP 200 with an EMPTY body   → transport and model are both healthy; the model simply
#                                     answered with nothing to THIS prompt
#
# Until 2026-07-31 all three collapsed into one silent `text=None, ok=False` with the exception
# swallowed by a bare `except Exception: pass`-shaped handler. Case 3 was live in production
# that day — moondream returned `{"response": "", "done_reason": "stop"}` for the full
# _vision_prompt, describe_image returned None, and the reviewer re-draft (#131) did nothing.
# Diagnosing it needed a hand-rolled httpx.post inside the container, because the app recorded
# nothing about which of the three had happened. (The prompt half of that bug is #128; this is
# the half that made it expensive to find.)
#
# So: every adapter logs the distinguishing detail and returns a `reason` on the result, which
# ai._trace_ai carries onto the ai_calls row — triage without shelling into a container.
REASON_OK = "ok"
REASON_TRANSPORT = "transport_error"       # case 1 — no HTTP response exists
REASON_EMPTY = "empty_response"            # case 3 — 200, and the model said nothing
# case 2 is `http_<status>` (e.g. 'http_502'), so `reason LIKE 'http_%'` groups them.

# Not a transport outcome at all, and set by ai.py rather than by an adapter: the model answered
# and the alt-text honesty guard rejected the answer as too thin for WCAG 1.1.1. It belongs in
# this vocabulary because it shares the ai_calls column with the three above — and because on
# that row, unnamed, it is indistinguishable from a dead endpoint.
REASON_UNUSABLE = "reply_unusable"


def _http_reason(status: int) -> str:
    return f"http_{status}"


# An error body can be an entire HTML page; a log line that long is unreadable and the useful
# part is always at the front. 400 chars covers an Ollama/Azure JSON error envelope whole.
_BODY_SLICE_CHARS = 400


def _body_slice(resp, limit: int = _BODY_SLICE_CHARS) -> str:
    """A bounded, single-line excerpt of an error response body for the log line.

    Single-line on purpose: Container Apps stores one log ROW per line, so a multi-line message
    is only findable by whichever line you happened to search for. Never raises — this runs on
    the failure path, where a second failure would hide the first."""
    try:
        raw = resp.text or ""
    except Exception:
        return "<unreadable>"
    raw = " ".join(raw.split())
    return raw[:limit] + ("…" if len(raw) > limit else "")


def _classify(exc: Exception) -> tuple[str, str]:
    """(reason, log detail) for an exception raised by a vision call — case 2 vs case 1.

    An HTTP error carries the response it came from, so we can name the status and quote a
    bounded slice of the body. A transport throw carries no response at all, so its own type
    and text ARE the diagnosis ('ConnectError: [Errno 61] Connection refused')."""
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if isinstance(status, int):
        return _http_reason(status), f"HTTP {status} · body={_body_slice(resp)!r}"
    return REASON_TRANSPORT, f"{type(exc).__name__}: {exc}"


def _log_failure(provider: str, model: str, endpoint: str, detail: str) -> None:
    """One single-line diagnostic per failed vision call, in this repo's print-to-stdout style
    (see scanner.py / ai.py). Names the provider, model and endpoint because the selector can
    pick any of three adapters and 'vision failed' does not say which one was asked.

    Collapsed to ONE line here rather than at each call site, because the newlines arrive from
    outside: an exception's own `str()` is routinely multi-line (httpx renders a URL hint on a
    second line) and so is an error body. Container Apps stores one row per line, so half of a
    split message is invisible to any search that matched the other half."""
    line = " ".join(f"[vision] {provider} · model={model} · endpoint={endpoint} — {detail}".split())
    print(line, flush=True)


@runtime_checkable
class VisionProvider(Protocol):
    """A vision-capable model behind one uniform call. Implementations MUST NOT raise from
    `generate` — a failure returns `ok=False` so the gateway can fall back or escalate. Not
    raising is not the same as not saying why: an implementation MUST also log the
    distinguishing detail and set `reason` to which of the three modes it hit."""
    name: str
    zone: str

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        ...


def _result(*, text: str | None, model: str, provider: str, zone: str,
            latency_ms: int, ok: bool, cost_usd: float = 0.0,
            reason: str = REASON_OK,
            prompt_tokens: int | None = None,
            completion_tokens: int | None = None) -> dict:
    """The normalized vision result every adapter returns. `cost_usd` is a real measured cost
    (0 for local Ollama; a cloud adapter fills its per-call token cost) — never a fabricated
    number (ADR 0016). `reason` says WHICH way a call ended, because `ok=False` on its own is
    not actionable — see the reason constants above.

    `prompt_tokens`/`completion_tokens` are the REAL token counts the API returned (Ollama's
    prompt_eval_count/eval_count; a cloud provider's usage) — the numbers ai._trace_ai forwards
    so the Langfuse generation carries real `usage` (ADR 0019 §1, Langfuse audit N1). They are
    counts only, never any prompt/completion text (docs/audit-langfuse-phi.md); None when the
    provider did not report them (a failed call, or a transport that omits usage)."""
    return {"text": text, "model": model, "provider": provider, "zone": zone,
            "latency_ms": latency_ms, "ok": ok, "cost_usd": cost_usd, "reason": reason,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


class OllamaVisionProvider:
    """The default, keyless, local provider — the existing Ollama /api/generate vision call,
    unchanged. `base_url` + `model` are passed in from `ai`'s live globals (which the runtime
    endpoint override may have repointed), so this stays a pure transport with no back-import."""

    def __init__(self, base_url: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.name = "ollama"
        self.zone = zone_for_url(self.base_url)

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64
        mdl = model or self.model
        t0 = time.monotonic()

        def _fail(reason: str) -> dict:
            return _result(text=None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False, reason=reason)

        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            import ai as _ai
            r = httpx.post(
                f"{self.base_url}/api/generate",
                json={"model": mdl, "prompt": prompt, "images": [b64],
                      "stream": False, "options": {"temperature": 0.2, "num_predict": 200}},
                headers=_ai._OLLAMA_HEADERS,
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json() or {}
            raw = (data.get("response", "") or "").strip()
        except Exception as e:                       # cases 1 and 2 — see the reason constants
            reason, detail = _classify(e)
            _log_failure(self.name, mdl, self.base_url, detail)
            return _fail(reason)
        if not raw:
            # Case 3. Nothing raised and nothing is wrong with the deployment: Ollama answered
            # 200 with `{"response": "", "done_reason": "stop"}`. done_reason/eval_count are the
            # two fields that tell it apart from a truncation, so they belong in the line.
            _log_failure(self.name, mdl, self.base_url,
                         "model returned empty — HTTP 200 with response='' "
                         f"(done_reason={data.get('done_reason')!r}, "
                         f"eval_count={data.get('eval_count')!r}). The model is healthy; it "
                         "declined to answer THIS prompt.")
            return _fail(REASON_EMPTY)
        return _result(text=raw, model=mdl, provider=self.name, zone=self.zone,
                       latency_ms=int((time.monotonic() - t0) * 1000), ok=True,
                       prompt_tokens=data.get("prompt_eval_count"),
                       completion_tokens=data.get("eval_count"))


# ── Provider configuration (ADR 0019 §6, secret-ref design) ────────────────────
# The DB stores non-secret config + the NAME of an environment/Key-Vault secret (key_secret_ref).
# The key VALUE is provisioned by ops as a container secret and read here at call time — it never
# enters the DB, a request body, a log, a trace, or the browser. credential_source is therefore
# 'environment_managed' when a ref is set (the enterprise "this is your key in your vault" answer).

def _resolve_key(cfg: dict) -> str | None:
    """The actual API key for a provider, read from the ops-provisioned environment secret named by
    `key_secret_ref`. Internal — only an adapter calls this, never a route or the UI. Returns None
    when unconfigured or the secret isn't present (→ provider stays inert, routes to local + human)."""
    ref = (cfg or {}).get("key_secret_ref")
    return os.environ.get(ref) if ref else None


def provider_view(cfg: dict) -> dict:
    """A browser/route-SAFE view of one provider's config: never the key, only whether the
    referenced secret is present. `credential_source` tells an enterprise admin who owns the
    secret. This is the ONLY shape that leaves the backend for a provider config."""
    ref = (cfg or {}).get("key_secret_ref") or ""
    return {
        "provider": cfg.get("provider"),
        "enabled": bool(cfg.get("enabled")),
        "endpoint": cfg.get("endpoint") or "",
        "deployment": cfg.get("deployment") or "",
        "model": cfg.get("model") or "",
        "key_secret_ref": ref,                       # the NAME only, never the value
        "key_present": bool(os.environ.get(ref)) if ref else False,
        "credential_source": "environment_managed" if ref else "not_configured",
        "zone": zone_for_url(cfg.get("endpoint") or "") if cfg.get("endpoint") else "cloud",
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
    }


def list_provider_views() -> list[dict]:
    """Every configurable cloud provider as a SAFE view — configured ones from the DB, the rest as
    empty/not_configured placeholders so the Settings page can render the full catalogue. Ollama
    (the built-in local default) is reported separately by ai.provenance()/ai.vision_is_available."""
    configured = {}
    try:
        import core
        configured = {c["provider"]: c for c in core.store.list_ai_provider_configs()}
    except Exception:
        configured = {}
    out = []
    for name in CLOUD_PROVIDERS:
        out.append(provider_view(configured.get(name, {"provider": name})))
    return out


def cloud_status() -> dict:
    """Non-admin, secret-free answer to 'is a governed cloud vision provider a configured, usable
    fallback?' — for the review card's empty-state honesty message, which must know WITHOUT admin
    rights whether escalation can happen (ADR 0019).

    Computed from the SAFE provider views only: `enabled` is True when some cloud provider is both
    admin-enabled AND its ops-provisioned secret is present (`key_present`), and `provider`/`zone`
    name that provider display-safely. It exposes NO secret — never the key value, the
    key_secret_ref value, or the endpoint — a boolean plus a provider name and a 'local'/'cloud'
    zone only. When nothing qualifies it reports the out-of-box state (disabled, no provider)."""
    for v in list_provider_views():
        if v.get("enabled") and v.get("key_present"):
            return {"enabled": True, "provider": v.get("provider"), "zone": v.get("zone")}
    return {"enabled": False, "provider": None, "zone": None}


# Per-1M-token list prices (USD) for cost accounting. These are REAL billing inputs multiplied by
# the token counts the API returns — a measured cost, never a fabricated score (ADR 0016). Unknown
# model → cost stays 0 (we don't invent one); tokens are still recorded.
_PRICE_PER_1M = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    # Anthropic (Claude) — first-party list prices per 1M tokens (input, output). Matched by
    # substring like the rest, so keep the full version ids; an unknown Claude model → cost 0.
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}


def _price_for(model: str) -> tuple[float, float] | None:
    m = (model or "").lower()
    for name, price in _PRICE_PER_1M.items():
        if name in m:
            return price
    return None


class AzureOpenAIVisionProvider:
    """Azure OpenAI vision via the chat-completions API — the enterprise-safe first cloud adapter
    (ADR 0019 §1). `privacy_zone='tenant'`: the model runs in the customer's OWN Azure resource, not
    a third-party host. The key is read from the ops-provisioned env secret (never stored/logged);
    cost is computed from the real token usage the API returns. Never raises."""

    def __init__(self, endpoint: str, deployment: str, api_key: str, *,
                 model: str | None = None, api_version: str = "2024-06-01"):
        self.endpoint = (endpoint or "").rstrip("/")
        self.deployment = deployment
        self._key = api_key
        self.model = model or deployment
        self.api_version = api_version
        self.name = "azure_openai"
        self.zone = "tenant"

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64
        t0 = time.monotonic()
        url = (f"{self.endpoint}/openai/deployments/{self.deployment}"
               f"/chat/completions?api-version={self.api_version}")

        def _fail(reason: str) -> dict:
            return _result(text=None, model=self.model, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False, reason=reason)

        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            body = {
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
                "max_tokens": 128, "temperature": 0.2,
            }
            # The key rides only in the request header to the customer's own Azure endpoint — it is
            # never persisted, logged, or returned; _resolve_key handed it in from the env secret.
            r = httpx.post(url, json=body, headers={"api-key": self._key}, timeout=timeout)
            r.raise_for_status()
            data = r.json() or {}
            choice = (data.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content", "") or "").strip()
        except Exception as e:                       # cases 1 and 2 — see the reason constants
            reason, detail = _classify(e)
            # The URL carries no secret (the key rides in the api-key header, which is never
            # logged), so naming the deployment endpoint is safe and is what identifies a 404
            # on a wrong deployment name from a 401 on a stale key.
            _log_failure(self.name, self.model, url, detail)
            return _fail(reason)
        if not text:
            # Case 3 — a 200 whose content is empty. On this API that is usually a content
            # filter or a length stop, and finish_reason is the field that says which.
            _log_failure(self.name, self.model, url,
                         "model returned empty — HTTP 200 with empty content "
                         f"(finish_reason={choice.get('finish_reason')!r}, "
                         f"usage={data.get('usage') or {}}).")
            return _fail(REASON_EMPTY)
        usage = data.get("usage") or {}
        price = _price_for(self.model)
        cost = 0.0
        if price:
            cost = round(usage.get("prompt_tokens", 0) / 1e6 * price[0]
                         + usage.get("completion_tokens", 0) / 1e6 * price[1], 6)
        return _result(text=text, model=self.model, provider=self.name,
                       zone=self.zone, latency_ms=int((time.monotonic() - t0) * 1000),
                       ok=True, cost_usd=cost,
                       prompt_tokens=usage.get("prompt_tokens"),
                       completion_tokens=usage.get("completion_tokens"))


class OpenAIVisionProvider:
    """OpenAI vision via the chat-completions API — api.openai.com, or an OpenAI-compatible
    endpoint the admin points at. `zone` is derived from the endpoint (public api.openai.com is
    'cloud': bytes leave the network, so the 🟡 badge stays honest — ADR 0016). The key rides only
    in the Authorization header (never stored/logged/returned); cost is computed from the real
    token usage the API returns. Never raises → ok=False on failure."""

    def __init__(self, api_key: str, *, model: str, endpoint: str | None = None):
        self.endpoint = (endpoint or "https://api.openai.com/v1").rstrip("/")
        self._key = api_key
        self.model = model
        self.name = "openai"
        self.zone = zone_for_url(self.endpoint)

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64
        mdl = model or self.model
        t0 = time.monotonic()
        url = f"{self.endpoint}/chat/completions"

        def _fail(reason: str) -> dict:
            return _result(text=None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False, reason=reason)

        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            body = {
                "model": mdl,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
                "max_tokens": 128, "temperature": 0.2,
            }
            # The key rides only in the Authorization header; the URL carries no secret, so naming
            # the endpoint on failure is safe and distinguishes a 404 (wrong path) from a 401 (key).
            r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {self._key}"},
                           timeout=timeout)
            r.raise_for_status()
            data = r.json() or {}
            choice = (data.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content", "") or "").strip()
        except Exception as e:                       # cases 1 and 2 — see the reason constants
            reason, detail = _classify(e)
            _log_failure(self.name, mdl, url, detail)
            return _fail(reason)
        if not text:
            _log_failure(self.name, mdl, url,
                         "model returned empty — HTTP 200 with empty content "
                         f"(finish_reason={choice.get('finish_reason')!r}, "
                         f"usage={data.get('usage') or {}}).")
            return _fail(REASON_EMPTY)
        usage = data.get("usage") or {}
        price = _price_for(mdl)
        cost = 0.0
        if price:
            cost = round(usage.get("prompt_tokens", 0) / 1e6 * price[0]
                         + usage.get("completion_tokens", 0) / 1e6 * price[1], 6)
        return _result(text=text, model=mdl, provider=self.name, zone=self.zone,
                       latency_ms=int((time.monotonic() - t0) * 1000), ok=True, cost_usd=cost,
                       prompt_tokens=usage.get("prompt_tokens"),
                       completion_tokens=usage.get("completion_tokens"))


class AnthropicVisionProvider:
    """Anthropic (Claude) vision via the Messages API (api.anthropic.com). `zone='cloud'`: a
    third-party host, so bytes leave the network and the 🟡 badge stays honest (ADR 0016). Thinking
    is disabled — alt text is a short, direct caption, so the token budget goes to the answer, not
    to reasoning. A safety refusal (HTTP 200, stop_reason='refusal') is treated as an empty answer.
    The key rides only in the x-api-key header (never stored/logged/returned); cost is computed from
    the real input/output token usage the API returns. Never raises → ok=False on failure."""

    _API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, *, model: str, endpoint: str | None = None):
        self.endpoint = (endpoint or "https://api.anthropic.com/v1").rstrip("/")
        self._key = api_key
        self.model = model
        self.name = "anthropic"
        self.zone = "cloud"

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64
        mdl = model or self.model
        t0 = time.monotonic()
        url = f"{self.endpoint}/messages"

        def _fail(reason: str) -> dict:
            return _result(text=None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False, reason=reason)

        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            body = {
                "model": mdl, "max_tokens": 128,
                # Disabling thinking is accepted at the default effort; it keeps the 128-token
                # budget for the caption rather than spending it on (billed) reasoning.
                "thinking": {"type": "disabled"},
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ]}],
            }
            r = httpx.post(url, json=body,
                           headers={"x-api-key": self._key, "anthropic-version": self._API_VERSION},
                           timeout=timeout)
            r.raise_for_status()
            data = r.json() or {}
        except Exception as e:                       # cases 1 and 2 — see the reason constants
            reason, detail = _classify(e)
            _log_failure(self.name, mdl, url, detail)
            return _fail(reason)
        if data.get("stop_reason") == "refusal":
            # Case 3 — a 200 the safety classifier declined. The model is healthy; it refused THIS
            # image. Nothing to certify from, so degrade to empty rather than emit a partial.
            _log_failure(self.name, mdl, url, "model refused — HTTP 200 with stop_reason='refusal'.")
            return _fail(REASON_EMPTY)
        text = "".join(b.get("text", "") for b in (data.get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "text").strip()
        if not text:
            _log_failure(self.name, mdl, url,
                         "model returned empty — HTTP 200 with no text block "
                         f"(stop_reason={data.get('stop_reason')!r}, usage={data.get('usage') or {}}).")
            return _fail(REASON_EMPTY)
        usage = data.get("usage") or {}
        price = _price_for(mdl)
        cost = 0.0
        if price:
            cost = round(usage.get("input_tokens", 0) / 1e6 * price[0]
                         + usage.get("output_tokens", 0) / 1e6 * price[1], 6)
        # Messages API names them input_tokens/output_tokens; the normalized result uses the
        # provider-neutral prompt/completion so ai._trace_ai forwards one shape to Langfuse.
        return _result(text=text, model=mdl, provider=self.name, zone=self.zone,
                       latency_ms=int((time.monotonic() - t0) * 1000), ok=True, cost_usd=cost,
                       prompt_tokens=usage.get("input_tokens"),
                       completion_tokens=usage.get("output_tokens"))


class RunPodServerlessVisionProvider:
    """GPU vision on a RunPod SERVERLESS endpoint via its OpenAI-compatible chat-completions API
    (ADR 0022). The endpoint URL is STABLE (set once), its workers auto-scale 0→N on demand and
    scale to zero when idle — so this can be the DEFAULT vision path with no standing pod and no
    idle bill, and it survives a redeploy. The key is read from an ops-provisioned env secret (never
    stored/logged/returned). `zone='cloud'`: RunPod is a third-party host, so bytes leave the network
    — the 🟡 badge stays honest (ADR 0016). Cost is GPU-seconds × the endpoint's rate (measured from
    the response, 0 when the rate is unknown — never invented). Never raises → ok=False on failure."""

    def __init__(self, endpoint_id: str, api_key: str, *, model: str = "qwen2.5-vl",
                 cost_per_sec: float = 0.0):
        self.endpoint_id = endpoint_id
        self._key = api_key
        self.model = model
        self.cost_per_sec = cost_per_sec
        self.name = "runpod_serverless"
        self.zone = "cloud"
        self.url = f"https://api.runpod.ai/v2/{endpoint_id}/openai/v1/chat/completions"

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64
        t0 = time.monotonic()
        mdl = model or self.model

        def _fail(reason: str) -> dict:
            return _result(text=None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False, reason=reason)

        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            body = {
                "model": mdl,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
                "max_tokens": 128, "temperature": 0.2,
            }
            # The RunPod key rides only in this request header — never persisted, logged, or returned.
            r = httpx.post(self.url, json=body,
                           headers={"Authorization": f"Bearer {self._key}", "content-type": "application/json"},
                           timeout=timeout)
            r.raise_for_status()
            data = r.json() or {}
            choice = (data.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content", "") or "").strip()
        except Exception as e:                       # cases 1 and 2 — see the reason constants
            reason, detail = _classify(e)
            # A serverless cold start over the timeout and a scaled-to-zero endpoint both end
            # here, and they read identically as ok=False — the exception text is what separates
            # a ReadTimeout from a ConnectError, and it decides whether to raise the timeout.
            _log_failure(self.name, mdl, self.url, detail)
            return _fail(reason)
        if not text:
            _log_failure(self.name, mdl, self.url,
                         "model returned empty — HTTP 200 with empty content "
                         f"(finish_reason={choice.get('finish_reason')!r}).")
            return _fail(REASON_EMPTY)
        # GPU-seconds → cost. RunPod surfaces execution time on the envelope; 0 if absent/no rate.
        exec_ms = data.get("executionTime") or (data.get("usage") or {}).get("execution_time_ms") or 0
        cost = round((exec_ms / 1000.0) * self.cost_per_sec, 6) if (exec_ms and self.cost_per_sec) else 0.0
        # The OpenAI-compatible envelope carries token usage; surface it for the Langfuse generation.
        usage = data.get("usage") or {}
        return _result(text=text, model=mdl, provider=self.name, zone=self.zone,
                       latency_ms=int((time.monotonic() - t0) * 1000), ok=True,
                       cost_usd=cost,
                       prompt_tokens=usage.get("prompt_tokens"),
                       completion_tokens=usage.get("completion_tokens"))


def serverless_vision_provider() -> VisionProvider | None:
    """The RunPod Serverless GPU provider from deploy env, or None when unconfigured (→ the vision
    default stays the local CPU floor, so a deploy without serverless config is exactly the keyless
    local build). `RUNPOD_ENDPOINT_ID` is non-secret config; `RUNPOD_API_KEY` is the ops secret."""
    eid = os.environ.get("RUNPOD_ENDPOINT_ID")
    key = os.environ.get("RUNPOD_API_KEY")
    if not (eid and key):
        return None
    model = os.environ.get("RUNPOD_VISION_MODEL", "qwen2.5-vl")
    try:
        rate = float(os.environ.get("RUNPOD_COST_PER_SEC", "0") or 0)
    except ValueError:
        rate = 0.0
    return RunPodServerlessVisionProvider(eid, key, model=model, cost_per_sec=rate)


def local_vision_provider() -> VisionProvider:
    """The always-available local CPU Ollama floor — the fallback when the default GPU provider
    misses (cold-start timeout / outage), built from `ai`'s current endpoint globals."""
    import ai as _ai
    _ai._maybe_refresh_endpoint()
    return OllamaVisionProvider(_ai.OLLAMA_BASE_URL, _ai.OLLAMA_VISION_MODEL)


def _adapter_for(provider: str, cfg: dict) -> VisionProvider | None:
    """Build the adapter for one configured cloud provider from its stored config, or None when it
    is under-configured (missing key or a required field). The single place that knows each cloud
    provider's required fields, so both the escalation path and the selector agree."""
    key = _resolve_key(cfg)
    if provider == "azure_openai":
        endpoint, deployment = cfg.get("endpoint"), cfg.get("deployment")
        if not (key and endpoint and deployment):
            return None
        return AzureOpenAIVisionProvider(endpoint, deployment, key, model=cfg.get("model"))
    if provider == "openai":
        if not (key and cfg.get("model")):
            return None
        return OpenAIVisionProvider(key, model=cfg.get("model"), endpoint=cfg.get("endpoint"))
    if provider == "anthropic":
        if not (key and cfg.get("model")):
            return None
        return AnthropicVisionProvider(key, model=cfg.get("model"), endpoint=cfg.get("endpoint"))
    return None


def cloud_vision_provider() -> VisionProvider | None:
    """The configured, ENABLED, key-present cloud vision provider for escalation, or None (ADR 0019
    §2/§3c). None is the out-of-box state: with no cloud configured, escalation never fires and the
    product stays exactly the keyless local build. When several are enabled, the admin's
    `ai_vision_provider` selection wins; otherwise the first configured one is used. A mis/under-
    configured provider is skipped rather than erroring."""
    try:
        import core
    except Exception:
        return None
    # The admin selection is a best-effort hint; a store that doesn't expose it (or errors) just
    # means "no preference" — it must not disable escalation on its own.
    try:
        setting = (core.store.get_setting("ai_vision_provider") or "").strip().lower()
    except Exception:
        setting = ""
    order = ([setting] if setting in CLOUD_PROVIDERS else []) + \
            [p for p in ("azure_openai", "openai", "anthropic") if p != setting]
    for name in order:
        try:
            cfg = core.store.get_ai_provider_config(name)
        except Exception:
            continue
        if cfg and cfg.get("enabled"):
            adapter = _adapter_for(name, cfg)
            if adapter is not None:
                return adapter
    return None


def active_vision_provider() -> VisionProvider:
    """Select the vision provider for this call (ADR 0019 §2 policy router — slice 1 stub).

    Reads the admin `ai_vision_provider` setting (default 'ollama') and constructs the adapter
    from `ai`'s current endpoint globals. Only 'ollama' is wired today; any other value falls
    back to Ollama so an un-provisioned cloud selection can never break the local path. The
    Azure OpenAI adapter + local-first acceptance policy slot in here next — this function stays
    the single selection point so no `if provider ==` branching leaks into `ai.py`."""
    import ai as _ai
    _ai._maybe_refresh_endpoint()              # honour a runtime endpoint switch before selecting
    base_url = _ai.OLLAMA_BASE_URL
    model = _ai.OLLAMA_VISION_MODEL
    env_choice = os.environ.get("ACP_VISION_PROVIDER", "").strip().lower()   # deploy default (ADR 0022)
    choice = env_choice
    try:
        import core
        setting = (core.store.get_setting("ai_vision_provider") or "").strip().lower()
        if setting:                                    # an explicit admin choice overrides the default
            if setting != env_choice and env_choice == "runpod_serverless":
                logging.warning(
                    "R2: ACP_VISION_PROVIDER=runpod_serverless (env) is overridden by the admin "
                    "store setting ai_vision_provider=%r — vision will use %r, not RunPod. "
                    "Clear the store setting to restore GPU vision.",
                    setting, setting,
                )
            choice = setting
    except Exception:
        pass
    choice = choice or "ollama"
    # RunPod Serverless GPU is the durable default when configured (ADR 0022); it falls back to the
    # local floor inside ai._vision_generate on a miss, and returns None here when unconfigured so
    # the local path is never broken by a stale selection.
    if choice == "runpod_serverless":
        sp = serverless_vision_provider()
        if sp is not None:
            return sp
        eid = os.environ.get("RUNPOD_ENDPOINT_ID", "")
        key = os.environ.get("RUNPOD_API_KEY", "")
        if eid and not key:
            logging.warning(
                "R2: ACP_VISION_PROVIDER=runpod_serverless and RUNPOD_ENDPOINT_ID=%r is set "
                "but RUNPOD_API_KEY is empty — the runpod-api-key Azure secret is missing or "
                "blank. Run set_integration_env.sh with a valid key; see "
                "docs/runbooks/runpod-key-rotation.md. Falling back to local Ollama.",
                eid,
            )
        else:
            logging.warning(
                "R2: ACP_VISION_PROVIDER=runpod_serverless but RUNPOD_ENDPOINT_ID is not set "
                "— endpoint unconfigured. Falling back to local Ollama.",
            )
    # A configured, enabled cloud provider (Azure OpenAI / OpenAI / Anthropic) is selected here; an
    # under-configured or unreachable-config selection falls through to the local floor so a stale
    # selection can never break the keyless local path.
    if choice in CLOUD_PROVIDERS:
        try:
            import core
            cfg = core.store.get_ai_provider_config(choice)
            if cfg and cfg.get("enabled"):
                adapter = _adapter_for(choice, cfg)
                if adapter is not None:
                    return adapter
        except Exception:
            pass
    return OllamaVisionProvider(base_url, model)
