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
    internal DNS) — no document leaves your network — else 'cloud'. Kept identical to
    `ai.provenance()` so the governance zone stays truthful no matter which module reports it."""
    host = (urlparse(base_url or "").hostname or "").lower()
    local = (
        host in ("localhost", "127.0.0.1", "::1", "")
        or host.endswith(".internal") or ".internal." in host
        or host.endswith(".local")
        or host.startswith("10.") or host.startswith("192.168.")
        or any(host.startswith(f"172.{n}.") for n in range(16, 32))
    )
    return "local" if local else "cloud"


@runtime_checkable
class VisionProvider(Protocol):
    """A vision-capable model behind one uniform call. Implementations MUST NOT raise from
    `generate` — a transport failure returns `ok=False` so the gateway can fall back or escalate."""
    name: str
    zone: str

    def generate(self, prompt: str, image_bytes: bytes, *, model: str | None = None,
                 timeout: float = 120.0) -> dict:
        ...


def _result(*, text: str | None, model: str, provider: str, zone: str,
            latency_ms: int, ok: bool, cost_usd: float = 0.0) -> dict:
    """The normalized vision result every adapter returns. `cost_usd` is a real measured cost
    (0 for local Ollama; a cloud adapter fills its per-call token cost) — never a fabricated
    number (ADR 0016)."""
    return {"text": text, "model": model, "provider": provider, "zone": zone,
            "latency_ms": latency_ms, "ok": ok, "cost_usd": cost_usd}


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
        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            r = httpx.post(
                f"{self.base_url}/api/generate",
                json={"model": mdl, "prompt": prompt, "images": [b64],
                      "stream": False, "options": {"temperature": 0.2, "num_predict": 128}},
                timeout=timeout,
            )
            r.raise_for_status()
            raw = (r.json().get("response", "") or "").strip()
            return _result(text=raw or None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=bool(raw))
        except Exception:
            return _result(text=None, model=mdl, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False)


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


# Per-1M-token list prices (USD) for cost accounting. These are REAL billing inputs multiplied by
# the token counts the API returns — a measured cost, never a fabricated score (ADR 0016). Unknown
# model → cost stays 0 (we don't invent one); tokens are still recorded.
_PRICE_PER_1M = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
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
        try:
            import httpx
            b64 = base64.b64encode(image_bytes).decode("ascii")
            url = (f"{self.endpoint}/openai/deployments/{self.deployment}"
                   f"/chat/completions?api-version={self.api_version}")
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
            data = r.json()
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
            usage = data.get("usage") or {}
            price = _price_for(self.model)
            cost = 0.0
            if price:
                cost = round(usage.get("prompt_tokens", 0) / 1e6 * price[0]
                             + usage.get("completion_tokens", 0) / 1e6 * price[1], 6)
            return _result(text=text.strip() or None, model=self.model, provider=self.name,
                           zone=self.zone, latency_ms=int((time.monotonic() - t0) * 1000),
                           ok=bool(text.strip()), cost_usd=cost)
        except Exception:
            return _result(text=None, model=self.model, provider=self.name, zone=self.zone,
                           latency_ms=int((time.monotonic() - t0) * 1000), ok=False)


def cloud_vision_provider() -> VisionProvider | None:
    """The configured, ENABLED, key-present cloud vision provider for escalation, or None (ADR 0019
    §2/§3c). None is the out-of-box state: with no cloud configured, escalation never fires and the
    product stays exactly the keyless local build. Azure OpenAI is the only wired cloud adapter in
    Phase 1; a mis/under-configured provider returns None rather than erroring."""
    try:
        import core
        cfg = core.store.get_ai_provider_config("azure_openai")
    except Exception:
        return None
    if not cfg or not cfg.get("enabled"):
        return None
    key = _resolve_key(cfg)
    endpoint, deployment = cfg.get("endpoint"), cfg.get("deployment")
    if not (key and endpoint and deployment):
        return None
    return AzureOpenAIVisionProvider(endpoint, deployment, key, model=cfg.get("model"))


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
    choice = "ollama"
    try:
        import core
        choice = (core.store.get_setting("ai_vision_provider") or "ollama").strip().lower() or "ollama"
    except Exception:
        pass
    # Future: elif choice == "azure_openai" and configured → AzureOpenAIVisionProvider(...)
    return OllamaVisionProvider(base_url, model)
