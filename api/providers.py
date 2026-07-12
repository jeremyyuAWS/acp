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

import time
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse


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
