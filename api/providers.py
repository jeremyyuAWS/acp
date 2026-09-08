"""AI provider adapter seam (ADR 0019, §1).

The gateway's provider abstraction covers the vision path used by `describe_image`,
`describe_image_structured` and `validate_alt_text`, which funnel through
`ai._vision_generate`. It also owns the optional cloud TEXT transports used by governed
remediation pilots — Anthropic (Messages API) and OpenAI (chat-completions), selected by
`active_text_provider` and dispatched by `text_generate`; without a resolved cloud text secret,
text falls back to the established local path.

A provider is a small object with a uniform `generate(prompt, image_bytes, *, model, timeout)`
that returns a normalized result dict — never raises, degrades to `ok=False`. `ai.py` keeps the
prompt building, the honesty/cleaning guard, and the Langfuse+ai_calls trace; the provider owns
only the transport + its own cost/zone metadata. Callers of `ai.*` are untouched (rule 4).

The shipped selector supports the keyless Ollama floor; six owner-configured cloud vision
adapters (Azure OpenAI, OpenAI, Anthropic, Gemini, Bedrock and Hugging Face); two cloud text
transports (Anthropic, OpenAI); and the separately configured RunPod Serverless GPU route.
Cloud activation requires explicit governance plus a resolved secret reference. The assistant
never handles a key.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse
from swallowed import swallowed

# The six owner-governed cloud vision adapters. Ollama is the built-in local default; RunPod
# Serverless is a separate deployment-level GPU route, so neither appears in this table.
CLOUD_PROVIDERS = ("azure_openai", "openai", "anthropic", "gemini", "bedrock", "huggingface")

# ── Cloud TEXT transports (ADR 0019 §1) ───────────────────────────────────────
# The text lane mirrors the vision one: a vendor transport per provider, one selector
# (active_text_provider), one dispatcher (text_generate) and one provenance function
# (text_provider_provenance). Two vendors are implemented — Anthropic's Messages API and
# OpenAI's chat-completions — because a governed remediation pilot runs on whichever key the
# owner has provisioned, and a fix whose provenance cannot name the model that produced it is
# not auditable (ADR 0016).
#
# NEITHER TRANSPORT EVER HANDLES A PASTED KEY. Each resolves a REFERENCE that ops or the
# Settings page provisioned: the ops-provisioned environment secret, or — for OpenAI — the
# governed provider row's `key_secret_ref`, which is the same env-name-or-`keyvault:` reference
# the vision adapters resolve through `_resolve_key` (ADR 0019 §6, ADR 0050 write-through).
# The key rides only in the request header; it is never logged, stored, traced or returned.
#
# The text providers this module can transport for. Selection is active_text_provider().
TEXT_PROVIDERS = ("anthropic", "openai")

# Claude text provider — module-level config so both the text seam below and the
# vision auto-select in active_vision_provider() share the same source of truth.
# The key rides only in the x-api-key request header: never logged, stored, or returned.
CLAUDE_TEXT_MODEL = os.environ.get("CLAUDE_TEXT_MODEL", "claude-haiku-4-5")
_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2023-06-01"

# OpenAI text provider. `gpt-4o-mini` is the default because it is the cheap tier already
# priced in _PRICE_PER_1M below — so the cost on every call is a real per-token measurement
# rather than an invented one (ADR 0016) — and it is the OpenAI counterpart of the Anthropic
# default's cheap tier. _OPENAI_TEXT_BASE_URL points the lane at an OpenAI-compatible endpoint
# (self-hosted or gateway); the zone is DERIVED from it by zone_for_url, so pointing this at
# your own infrastructure reports 'local' honestly instead of claiming a third party ran it.
OPENAI_TEXT_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini")
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
_OPENAI_TEXT_BASE_URL = os.environ.get(
    "OPENAI_TEXT_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def claude_text_generate(prompt: str, *, temperature: float = 0.4,
                         max_tokens: int = 800, timeout: float = 30.0,
                         model: str | None = None) -> dict | None:
    """Single-turn text completion via the Anthropic Messages API.

    Returns {text, prompt_tokens, completion_tokens, cost_usd, model, provider, zone, host}
    or None when the key is absent or the call fails. Never raises."""
    if not _ANTHROPIC_KEY:
        return None
    import httpx
    requested_model = model or CLAUDE_TEXT_MODEL
    try:
        r = httpx.post(
            _ANTHROPIC_MESSAGES_URL,
            json={
                "model": requested_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={"x-api-key": _ANTHROPIC_KEY, "anthropic-version": _ANTHROPIC_API_VERSION},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in (data.get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "text").strip()
        if not text:
            return None
        usage = data.get("usage") or {}
        input_tok = usage.get("input_tokens", 0)
        output_tok = usage.get("output_tokens", 0)
        price = _price_for(requested_model)
        cost_usd = round(input_tok / 1e6 * price[0] + output_tok / 1e6 * price[1], 6) if price else 0.0
        return {
            "text": text,
            "prompt_tokens": input_tok,
            "completion_tokens": output_tok,
            "cost_usd": cost_usd,
            "model": requested_model,
            "provider": "anthropic",
            "zone": "cloud",
            "host": "api.anthropic.com",
        }
    except Exception:
        return None


def _openai_text_key() -> str:
    """The OpenAI key for the TEXT lane, resolved from a REFERENCE — never a pasted value.

    Two references, both of which already exist; this adds no new way to handle a key:

      1. the governed `openai` provider row's `key_secret_ref`, resolved by `_resolve_key`
         (an environment-variable name, or a `keyvault:` name this product wrote through to the
         deployment's Key Vault — ADR 0019 §6, ADR 0050). Read ONLY when that row is `enabled`,
         so a key an admin provisioned for vision cannot start serving text without the admin
         also enabling the provider;
      2. otherwise the ops-provisioned `OPENAI_API_KEY` environment secret — the exact mechanism
         the Anthropic text lane has always used for `ANTHROPIC_API_KEY`.

    Returns "" when neither resolves, which is what keeps the keyless local floor intact.
    """
    try:
        cfg = _config_for("openai")
        if cfg.get("enabled"):
            key = _resolve_key(cfg)
            if key:
                return key
    except Exception:
        swallowed("providers._openai_text_key: resolving the governed OpenAI key reference failed")
    return _OPENAI_KEY


def openai_text_generate(prompt: str, *, temperature: float = 0.4,
                         max_tokens: int = 800, timeout: float = 30.0,
                         model: str | None = None) -> dict | None:
    """Single-turn text completion via OpenAI's chat-completions API.

    The OpenAI half of the text seam: same signature, same normalized return shape and the same
    never-raises contract as `claude_text_generate`, so `text_generate` can dispatch to either
    without the caller learning which vendor ran.

    Returns {text, prompt_tokens, completion_tokens, cost_usd, model, provider, zone, host}
    or None when the key reference does not resolve or the call fails. Never raises."""
    key = _openai_text_key()
    if not key:
        return None
    import httpx
    requested_model = model or OPENAI_TEXT_MODEL
    url = f"{_OPENAI_TEXT_BASE_URL}/chat/completions"
    try:
        r = httpx.post(
            url,
            json={
                "model": requested_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            # The key rides only in the Authorization header — never in the URL, a log line or
            # the returned dict.
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json() or {}
        choice = (data.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content", "") or "").strip()
        if not text:
            return None
        usage = data.get("usage") or {}
        input_tok = usage.get("prompt_tokens", 0)
        output_tok = usage.get("completion_tokens", 0)
        price = _price_for(requested_model)
        cost_usd = round(input_tok / 1e6 * price[0] + output_tok / 1e6 * price[1], 6) if price else 0.0
        return {
            "text": text,
            "prompt_tokens": input_tok,
            "completion_tokens": output_tok,
            "cost_usd": cost_usd,
            "model": requested_model,
            "provider": "openai",
            "zone": zone_for_url(_OPENAI_TEXT_BASE_URL),
            "host": (urlparse(_OPENAI_TEXT_BASE_URL).hostname or "").lower(),
        }
    except Exception:
        return None


def _text_key_for(provider: str) -> str:
    """One text provider's resolved key, or "" — internal, and the value never leaves this
    module: `active_text_provider` uses it only to decide whether the provider is usable."""
    if provider == "anthropic":
        return _ANTHROPIC_KEY
    if provider == "openai":
        return _openai_text_key()
    return ""


def active_text_provider() -> str | None:
    """Which cloud text provider serves this deployment, or None for the keyless local floor.

    Order, and WHY it is this order:

      1. an explicit selection — the `ai_text_provider` admin setting, else the
         `ACP_TEXT_PROVIDER` deploy default — used only when that provider's key reference also
         resolves. This mirrors `active_vision_provider`'s setting-beats-env precedence;
      2. otherwise Anthropic when `ANTHROPIC_API_KEY` is present. This is the behaviour that
         shipped, preserved exactly: a deployment that has only the Anthropic secret keeps
         getting Anthropic text with nothing to reconfigure;
      3. otherwise None → `ai.suggest_fix` uses the established local path.

    OPENAI TEXT NEEDS THE EXPLICIT SELECTION, not just a key. `OPENAI_API_KEY` is present in
    environments that run the evals kit and `scripts/judge_drafts.py`, and an enabled `openai`
    row may exist for VISION only; auto-activating on either would start sending remediation
    text to a third party that nobody agreed to send it to. Cloud egress is opt-in (ADR 0019
    constraint 2), so the owner names the text provider and the key is the second half.

    A selection whose key does not resolve degrades to (2) then (3) rather than erroring — a
    stale selection can never break the local floor."""
    choice = ""
    try:
        import core
        choice = (core.store.get_setting("ai_text_provider") or "").strip().lower()
    except Exception:
        swallowed("providers.active_text_provider: reading the ai_text_provider setting failed")
    if not choice:
        choice = os.environ.get("ACP_TEXT_PROVIDER", "").strip().lower()
    # A name this module has no text transport for (a vision-only provider, a typo) is not an
    # error: it means "no preference", and the fallbacks below apply.
    if choice in TEXT_PROVIDERS and _text_key_for(choice):
        return choice
    if _ANTHROPIC_KEY:
        return "anthropic"
    return None


def text_generate(prompt: str, *, temperature: float = 0.4, max_tokens: int = 800,
                  timeout: float = 30.0, model: str | None = None,
                  provider: str | None = None) -> dict | None:
    """The single text seam `ai.py` calls: dispatch to the selected vendor's transport.

    `provider` PINS the call to one vendor and exists for the governed pilot lane, whose model
    id is vendor-specific (`remediation_pilot.PROVIDER`/`MODEL`): dispatching a Claude model id
    to OpenAI because OpenAI happens to be the deployment default would be a call that fails, or
    worse, one whose ai_calls row names a model that never ran. A pinned provider whose key does
    not resolve returns None, so the caller still degrades to the local path.

    Returns the vendor-neutral result dict, or None. Never raises."""
    name = (provider or active_text_provider() or "").strip().lower()
    if name == "openai":
        return openai_text_generate(prompt, temperature=temperature, max_tokens=max_tokens,
                                    timeout=timeout, model=model)
    if name == "anthropic":
        return claude_text_generate(prompt, temperature=temperature, max_tokens=max_tokens,
                                    timeout=timeout, model=model)
    return None


def text_provider_provenance() -> dict | None:
    """Return governance provenance for the configured cloud text provider, or None when
    keyless (Ollama). ai.provenance() calls this so the zone/host are a single source of truth.

    It reports whichever provider `active_text_provider` would actually use, so `/config` cannot
    name one vendor while the next remediation draft is produced by another."""
    name = active_text_provider()
    if name == "anthropic":
        return {
            "provider": "anthropic",
            "model": CLAUDE_TEXT_MODEL,
            "zone": "cloud",
            "host": "api.anthropic.com",
        }
    if name == "openai":
        return {
            "provider": "openai",
            "model": OPENAI_TEXT_MODEL,
            "zone": zone_for_url(_OPENAI_TEXT_BASE_URL),
            "host": (urlparse(_OPENAI_TEXT_BASE_URL).hostname or "").lower(),
        }
    return None


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
REASON_TIMEOUT = "timeout"                 # case 1a — bounded call exceeded its budget
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
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return REASON_TIMEOUT, f"{type(exc).__name__}: {exc}"
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
    """The actual API key for a provider, read from the secret named by `key_secret_ref`.

    Two kinds of name, one field (api/secret_store.py):
      * an environment variable — the original, ops-provisioned design; unchanged;
      * `keyvault:<name>` — a secret this product wrote to the deployment's Key Vault, resolved
        through a short-lived cache so the AI request path does not make a vault round-trip per
        call.

    Internal — only an adapter calls this, never a route or the UI. Returns None when unconfigured
    or the secret isn't present (→ provider stays inert, routes to local + human)."""
    ref = (cfg or {}).get("key_secret_ref")
    if not ref:
        return None
    import secret_store                    # noqa: PLC0415 - avoids an import cycle at module load
    if secret_store.is_vault_ref(ref):
        return secret_store.read_ref(ref)
    return os.environ.get(ref)


def credential_source_for(ref: str | None) -> str:
    """Who owns the secret behind a reference — for an admin reading the Settings page, and never
    a statement about its value."""
    if not ref:
        return "not_configured"
    import secret_store                    # noqa: PLC0415
    return "key_vault" if secret_store.is_vault_ref(ref) else "environment_managed"


def credential_for(provider: str) -> tuple[str | None, str]:
    """A provider's API key and the NAME it was read from — the supported way for code outside
    this module to reach an ops-provisioned credential.

    Returns `(key_or_None, source)` where source is the secret's reference name, or
    `"not_configured"` when the Settings page has no `key_secret_ref` for this provider, or
    `"secret_absent:<REF>"` when it names one that is not present in this environment. The
    SOURCE is always safe to print; the key never is.

    Exists because the evals kit (evals/candidates.py) needs the same credential the product
    uses, and the alternative was a second place to configure a key — one that fails silently
    when an ops team provisions it under a name of their own choosing, which is exactly what
    `key_secret_ref` exists to allow. Callers must not log or persist the first element.
    """
    cfg = _config_for(provider)
    ref = (cfg.get("key_secret_ref") or "").strip()
    if not ref:
        return None, "not_configured"
    val = _resolve_key(cfg)
    return (val, ref) if val else (None, f"secret_absent:{ref}")


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
        # Resolved through _resolve_key rather than os.environ directly, so a vault-backed
        # credential reports "present" on the page that an admin uses to check exactly that.
        # Before this, a key written to the vault read as absent and the provider looked broken.
        "key_present": bool(_resolve_key(cfg or {})) if ref else False,
        "credential_source": credential_source_for(ref),
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
    # (2.00, 10.00), not (3.00, 15.00). The latter is SONNET 4.6's price, carried onto Sonnet 5
    # when the id was added — a generation's price attached to its successor's name. It
    # over-quoted by 50%, so remediation_pilot's max_spend_usd guard stopped early rather than
    # late; the direction was lucky, not designed, and a spend cap fed by a wrong number is
    # exactly what ADR 0016 means by not inventing one.
    "claude-sonnet-5": (2.00, 10.00),
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


class GeminiVisionProvider:
    """Google Gemini vision via Gemini's OpenAI-compatible chat-completions endpoint.

    Gemini exposes the same request/response shape as OpenAI's `/v1/chat/completions`, so this
    class is structurally identical to OpenAIVisionProvider — the difference is the default
    endpoint and the provider name used in metrics. `zone='cloud'` because
    generativelanguage.googleapis.com is a public Google service (ADR 0016). The key rides only
    in the Authorization header; no secret is stored, logged, or returned.
    """

    def __init__(self, api_key: str, *, model: str, endpoint: str | None = None):
        self.endpoint = (endpoint or "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
        self._key = api_key
        self.model = model
        self.name = "gemini"
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
            r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {self._key}"},
                           timeout=timeout)
            r.raise_for_status()
            data = r.json() or {}
            choice = (data.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content", "") or "").strip()
        except Exception as e:
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


class BedrockVisionProvider:
    """AWS Bedrock vision via the Bedrock Runtime invoke_model API with SigV4 signing (boto3).

    Targets Claude models on Bedrock (payload: Anthropic Messages format, bedrock-2023-05-31
    version). `zone='cloud'` — Bedrock is AWS infrastructure, bytes leave the network (ADR 0016).
    The AWS secret access key rides only through boto3's SigV4 layer (never stored/logged/returned);
    `aws_access_key_id` is an identifier, not the secret. `key_secret_ref` resolves the secret key.
    Never raises → ok=False on failure.
    """

    def __init__(self, aws_access_key_id: str, aws_secret_access_key: str, *,
                 region: str, model: str):
        self._key_id = aws_access_key_id
        self._secret = aws_secret_access_key
        self.region = region
        self.model = model
        self.name = "bedrock"
        self.zone = "cloud"   # Bedrock is always a public AWS endpoint

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64, json
        mdl = model or self.model
        t0 = time.monotonic()
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{mdl}/invoke"

        def _fail(reason: str) -> dict:
            return _result(text=None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False, reason=reason)

        try:
            import boto3, botocore.exceptions
            client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                aws_access_key_id=self._key_id,
                aws_secret_access_key=self._secret,
            )
            b64 = base64.b64encode(image_bytes).decode("ascii")
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64,
                    }},
                ]}],
            }
            resp = client.invoke_model(
                modelId=mdl,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            data = json.loads(resp["body"].read()) or {}
            content = data.get("content") or []
            text = ""
            for block in content:
                if block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    break
        except Exception as e:
            reason, detail = _classify(e)
            _log_failure(self.name, mdl, url, detail)
            return _fail(reason)
        if not text:
            _log_failure(self.name, mdl, url,
                         "model returned empty — invoke_model 200 with no text block "
                         f"(stop_reason={data.get('stop_reason')!r}, "
                         f"usage={data.get('usage') or {}}).")
            return _fail(REASON_EMPTY)
        usage = data.get("usage") or {}
        price = _price_for(mdl)
        cost = 0.0
        if price:
            cost = round(usage.get("input_tokens", 0) / 1e6 * price[0]
                         + usage.get("output_tokens", 0) / 1e6 * price[1], 6)
        return _result(text=text, model=mdl, provider=self.name, zone=self.zone,
                       latency_ms=int((time.monotonic() - t0) * 1000), ok=True, cost_usd=cost,
                       prompt_tokens=usage.get("input_tokens"),
                       completion_tokens=usage.get("output_tokens"))


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


class HuggingFaceVisionProvider:
    """A private Hugging Face Inference Endpoint via its OpenAI-compatible chat-completions API
    (ADR 0019). The endpoint URL and model name come from the admin's stored config; the token
    rides only in the Authorization: Bearer header (never stored/logged/returned). `zone` is
    derived from the endpoint URL via `zone_for_url` — a public HF endpoint on HF's own cloud
    infrastructure is 'cloud'; an endpoint on private internal infrastructure is 'local'. Cost
    is 0.0: private HF endpoints are billed by the hour at the endpoint level, not per token, so
    there is no per-call token price to look up (ADR 0016 — never invent a cost). Never raises."""

    def __init__(self, endpoint: str, api_key: str, *, model: str):
        self._endpoint = (endpoint or "").rstrip("/")
        self._key = api_key
        self.model = model
        self.name = "huggingface"
        self.zone = zone_for_url(self._endpoint)

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        import base64
        mdl = model or self.model
        t0 = time.monotonic()
        url = f"{self.endpoint}/v1/chat/completions"

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
            # The token rides only in the Authorization header — the URL carries no secret, so
            # naming the endpoint on failure is safe and distinguishes a 404 (wrong path) from 401.
            r = httpx.post(url, json=body,
                           headers={"Authorization": f"Bearer {self._key}"},
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
        return _result(text=text, model=mdl, provider=self.name, zone=self.zone,
                       latency_ms=int((time.monotonic() - t0) * 1000), ok=True, cost_usd=0.0,
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


# The non-secret fields each cloud provider needs before it can be enabled, beyond the key. ONE
# table, consulted by both _adapter_for (which builds) and activation_readiness (which explains),
# so "what does this provider need" cannot be true in one place and stale in the other —
# test_provider_activation.py asserts the two agree for every provider in CLOUD_PROVIDERS.
_REQUIRED_FIELDS = {
    "azure_openai": ("endpoint", "deployment"),
    "openai": ("model",),
    "anthropic": ("model",),
    "gemini": ("model",),
    "bedrock": ("model", "region", "aws_access_key_id"),
    "huggingface": ("endpoint", "model"),
}


def activation_readiness(provider: str, cfg: dict | None = None) -> dict:
    """Whether one provider is complete enough to be ENABLED, and what is missing if not.

    WHY THIS EXISTS. Enabling was previously unconditional: `PUT /ai/providers` stored
    `enabled=true` whatever else was blank, and `_adapter_for` then returned None at call time, so
    the provider fell through to the local floor. Verified by running it, not by reading: a config
    with no model and no key_secret_ref stores as enabled=True, builds no adapter, and reports
    `credential_source='not_configured'` — the Settings page says the provider is on, and every
    document is silently still handled locally. An enable switch that does nothing is worse than
    one that refuses, because it looks like consent was honoured.

    `missing` names the fields an admin still has to fill, and `secret_resolves` is the separate,
    ops-owned half: the key VALUE is provisioned outside this app, so a complete config can still be
    unusable because the referenced environment secret is absent. Those two failures need two
    different people, so they are reported apart rather than as one "not ready".

    Reads no secret value and returns none — only whether the named reference resolves.
    """
    cfg = cfg or {}
    required = _REQUIRED_FIELDS.get(provider)
    if required is None:
        return {"provider": provider, "ready": False, "missing": [], "secret_resolves": False,
                "detail": f"no adapter is implemented for '{provider}'"}
    missing = [f for f in required if not (cfg.get(f) or "").strip()]
    ref = (cfg.get("key_secret_ref") or "").strip()
    if not ref:
        missing.append("key_secret_ref")
    resolves = bool(_resolve_key(cfg))
    ready = not missing and resolves
    if missing:
        detail = "missing " + ", ".join(missing)
    elif not resolves:
        detail = (f"the environment secret named {ref} is not present on this deployment — "
                  "ops provisions the key value; this app never stores it")
    else:
        detail = "configuration is complete and the referenced secret resolves"
    return {"provider": provider, "ready": ready, "missing": missing,
            "secret_resolves": resolves, "detail": detail}


# A tiny, fixed, SYNTHETIC image for the connection test — a black square on white, 64x64, built
# here from stdlib zlib/struct rather than read from disk or rendered from anything a customer
# uploaded. That is the whole point: "Test connection" must prove the credential and the route
# work WITHOUT sending one byte of customer content to a third party. Deterministic, so the same
# bytes go every time and nothing about a tenant can leak through the probe.
#
# Not a 1x1 pixel: a model asked to describe a single pixel legitimately answers with nothing, and
# an empty answer is the one outcome this test must be able to call a FAILURE. A square is enough
# content for any vision model to say something, so REASON_EMPTY here means the deployment is
# wrong, not that the prompt was unanswerable.
_PROBE_SIZE = 64


def probe_image_bytes() -> bytes:
    """The synthetic probe image. Contains no customer document, no scan, no tenant data."""
    import struct
    import zlib
    n = _PROBE_SIZE
    rows = bytearray()
    for y in range(n):
        rows.append(0)                                   # PNG per-row filter: none
        for x in range(n):
            inside = n // 4 <= x < 3 * n // 4 and n // 4 <= y < 3 * n // 4
            rows += b"\x00\x00\x00" if inside else b"\xff\xff\xff"

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + _chunk(b"IEND", b""))


PROBE_PROMPT = "Describe this image in one short sentence."


def test_connection(provider: str, *, timeout: float = 30.0) -> dict:
    """Send the synthetic probe image to one provider and report what came back. Admin action.

    NO CUSTOMER DOCUMENT IS SENT — the bytes are probe_image_bytes(), generated in-process. That
    is what makes this safe to press on a provider nobody has agreed to send documents to yet:
    pressing it is how an admin finds out whether the credential and route work BEFORE any real
    content could go anywhere.

    RETURNS NO SECRET. The result carries the provider, model, zone, latency, the outcome reason,
    the real token counts and the real cost — the same normalized shape every vision call
    produces. It never carries the key, and never the value behind key_secret_ref.

    The three outcomes are the adapter's own (see the reason constants): a transport throw, an
    HTTP status, or a 200 with nothing in it. They stay distinct here because they need different
    fixes — a 401 is the wrong key, a 404 is the wrong model or route, and an empty 200 on THIS
    image means the deployment answers but cannot caption a black square, which is a real finding
    about the deployment rather than about the prompt.
    """
    ready = activation_readiness(provider, _config_for(provider))
    if not ready["ready"]:
        return {"ok": False, "provider": provider, "reason": "not_configured",
                "detail": ready["detail"], "missing": ready["missing"],
                "secret_resolves": ready["secret_resolves"]}
    adapter = _adapter_for(provider, _config_for(provider))
    if adapter is None:                                  # belt and braces; readiness already agreed
        return {"ok": False, "provider": provider, "reason": "not_configured",
                "detail": "the adapter could not be built from this configuration",
                "missing": ready["missing"], "secret_resolves": ready["secret_resolves"]}
    res = adapter.generate(PROBE_PROMPT, probe_image_bytes(), timeout=timeout)
    return {
        "ok": bool(res.get("ok")),
        "provider": res.get("provider") or provider,
        "model": res.get("model"),
        "zone": res.get("zone"),
        "latency_ms": res.get("latency_ms"),
        "reason": res.get("reason"),
        "prompt_tokens": res.get("prompt_tokens"),
        "completion_tokens": res.get("completion_tokens"),
        "cost_usd": res.get("cost_usd", 0.0),
        # Whether the model produced a caption at all — NOT the caption. The probe image is
        # synthetic so its description would be harmless, but a test action has no reason to
        # return model output, and not returning it keeps the response shape free of anything
        # that could carry content if the probe ever changed.
        "described": bool((res.get("text") or "").strip()),
        "secret_resolves": True,
    }


def _config_for(provider: str) -> dict:
    """One provider's stored config, or an empty config when the store is unavailable."""
    try:
        import core
        return core.store.get_ai_provider_config(provider) or {"provider": provider}
    except Exception:
        return {"provider": provider}


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
    if provider == "gemini":
        if not (key and cfg.get("model")):
            return None
        return GeminiVisionProvider(key, model=cfg.get("model"), endpoint=cfg.get("endpoint"))
    if provider == "bedrock":
        region = cfg.get("region")
        key_id = cfg.get("aws_access_key_id")
        if not (key and region and key_id and cfg.get("model")):
            return None
        return BedrockVisionProvider(key_id, key, region=region, model=cfg.get("model"))
    if provider == "huggingface":
        endpoint = cfg.get("endpoint")
        if not (key and endpoint and cfg.get("model")):
            return None
        return HuggingFaceVisionProvider(endpoint, key, model=cfg.get("model"))
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
    # Fallback order: managed cloud providers first, then self-hosted HuggingFace Inference
    # Endpoints. Admin's explicit setting is tried first; gemini and bedrock are included so
    # they are reachable as auto-fallback, not only via explicit admin selection.
    order = ([setting] if setting in CLOUD_PROVIDERS else []) + \
            [p for p in ("azure_openai", "openai", "anthropic", "gemini", "bedrock", "huggingface")
             if p != setting]
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
    """Select the vision provider for this call through ADR 0019's policy boundary.

    An explicit stored administrator choice overrides the deployment environment. RunPod and
    each governed cloud adapter are used only when their configuration resolves; otherwise the
    selector returns the local Ollama floor. This remains the single selection point so vendor
    branching does not leak into `ai.py`."""
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
        swallowed("providers.active_vision_provider: reading the active vision provider setting failed")
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
    # A configured, enabled cloud provider is selected here; an
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
            swallowed("providers.active_vision_provider: resolving the vision provider's adapter "
                      "config failed")
    # NO KEY-PRESENCE AUTO-SELECT, and the absence is the policy rather than an omission.
    #
    # There was a branch here returning AnthropicVisionProvider when ANTHROPIC_API_KEY was set and
    # no provider had been chosen. It had been unreachable since `choice = choice or "ollama"` was
    # introduced above — `not choice` can no longer be true — so it never selected anything, and
    # removing it changes no behaviour. Measured, not read: with the key set and no selection, the
    # selector returned the Ollama floor.
    #
    # It is deleted rather than revived because reviving it would be the bug. Cloud egress is
    # OPT-IN (ADR 0019 constraint 2), and every other cloud adapter earns its place two ways —
    # an explicit selection AND an `enabled` governed row with a resolved secret, the gate
    # immediately above. Key presence is neither: ANTHROPIC_API_KEY is set wherever the evals kit
    # or the text lane runs, so auto-selecting on it would start sending CUSTOMER DOCUMENT IMAGES
    # to a third party nobody chose. #1756 settled the same question for the text lane and
    # settled it this way, for the same reason.
    #
    # No capability is lost: Anthropic vision is reachable today by the governed path, which also
    # honours the row's own model. The dead branch pinned `CLAUDE_TEXT_MODEL` — a TEXT model id —
    # onto a vision adapter, so it would have been wrong about the model as well as the consent.
    return OllamaVisionProvider(base_url, model)
