"""Local-model AI layer for ACP.

Calls a locally-running Ollama instance (its native /api HTTP endpoint) to
generate human-readable explanations and fix examples for WCAG findings. No
commercial-LLM SDK or API key is used anywhere — the only backend is the local
Ollama model; the layer degrades to deterministic prose when it is unreachable.

Config (env vars):
  OLLAMA_BASE_URL      — default http://localhost:11434
  OLLAMA_MODEL         — default llama3.2 (text: explain / suggest / digest)
  OLLAMA_VISION_MODEL  — default moondream (vision: genuine alt text from image bytes)
  OLLAMA_VISION_TIMEOUT— default 120s (CPU vision inference is heavier than text)

Fails gracefully: every public function returns None (deterministic prose for the
digest) when Ollama is unreachable — callers never break and never need a key. The
vision path (describe_image) is the same: unavailable → None, and callers fall back
to a faithful source or human review.
"""
from __future__ import annotations
import os
import re

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "llama3.2")
# A separate vision model — the text model cannot see images, so genuine alt text needs this.
# Same local-Ollama backend, so the "no third-party AI" claim holds. Default is moondream (a
# compact ~1.7GB captioner) rather than llava:7b (~4.5GB): with llama3.1:8b it fits the 8Gi
# Consumption box with both models resident (no swap, no OOM), and infers faster on CPU. Set
# OLLAMA_VISION_MODEL to override — the deploy wires it, and nothing here assumes a model name.
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "moondream")
# Vision inference on CPU is heavier than text: a cold single-image describe can take
# 30-90s. Bound it so a wedged model can't stall a remediation job.
def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


OLLAMA_VISION_TIMEOUT = _envf("OLLAMA_VISION_TIMEOUT", 120.0)
# Availability probe. The warm path answers in milliseconds; the long budget only ever
# applies after the fast probe TIMES OUT, which is how a Container App scaling up from
# minReplicas=0 behaves (ACA holds the request while the replica activates).
OLLAMA_PROBE_TIMEOUT = _envf("OLLAMA_PROBE_TIMEOUT", 3.0)
OLLAMA_COLD_START_TIMEOUT = _envf("OLLAMA_COLD_START_TIMEOUT", 90.0)
# Memoise the probe: it is called once per remediated file, and a cold/absent Ollama must
# not cost the cold-start budget on every one of them.
OLLAMA_PROBE_TTL = _envf("OLLAMA_PROBE_TTL", 300.0)
_TAGS_CACHE: dict = {"at": 0.0, "tags": None}


def reset_probe_cache() -> None:
    """Drop the memoised probe (tests, and after an operator changes the Ollama config)."""
    _TAGS_CACHE.update(at=0.0, tags=None)


def provenance() -> dict:
    """AI provenance for governance/transparency (ADR 0019 Phase 0): which model runs, and WHERE
    the document bytes are processed — the enterprise "what model? / did my document leave my
    network?" answer, surfaced instead of a bare "AI generated".

    `zone` is derived from OLLAMA_BASE_URL so it stays truthful if an operator repoints it:
      - 'local'  → the endpoint is on your own infrastructure (localhost, an internal cluster
                   address, or a private IP range). No document leaves your network.
      - 'cloud'  → a third-party host (e.g. a hosted GPU proxy). Bytes leave your network.
    This build has no API key and no third-party AI SDK; the only backend is the configured
    Ollama endpoint. `zone='local'` is the honest default for the self-hosted Ollama deployment.
    """
    from urllib.parse import urlparse
    host = (urlparse(OLLAMA_BASE_URL).hostname or "").lower()
    local = (
        host in ("localhost", "127.0.0.1", "::1", "")
        or host.endswith(".internal") or ".internal." in host
        or host.endswith(".local")
        or host.startswith("10.") or host.startswith("192.168.")
        or any(host.startswith(f"172.{n}.") for n in range(16, 32))
    )
    return {
        "provider": "ollama",
        "model": OLLAMA_MODEL,
        "vision_model": OLLAMA_VISION_MODEL,
        "zone": "local" if local else "cloud",
        "host": host,
    }


def build_envelope(result: dict, *, model: str | None = None, grounded: bool | None = None,
                   grounding_sources: list[str] | None = None, latency_ms: float | None = None,
                   cost_usd: float = 0.0, trace_id: str | None = None,
                   prompt_version: str | None = None) -> dict:
    """The normalized `{result, provenance, trust}` envelope (ADR 0019 §3b).

    A pure assembler, deliberately NOT wired into the hot-path `ai.*` signatures (rule 4/22 — callers
    keep reading `result` unchanged): it composes the provenance the module already produces
    (`provenance()` + the per-call model/latency) with the grounding signal `describe_image_structured`
    already returns, into the single shape the card + certification will read once Phase 1 threads it
    through the provider adapters. `processing_zone` is honest ('local' for the keyless Ollama build,
    else the provider's zone). No fabricated number lives here — every field is a measurement or an
    evidence flag (ADR 0016)."""
    prov = provenance()
    zone = prov.get("zone", "local")
    return {
        "result": result,
        "provenance": {
            "provider": prov.get("provider"),
            "model": model or prov.get("vision_model"),
            "processing_zone": "local" if zone == "local" else "customer_cloud",
            "latency_ms": latency_ms,
            "cost_usd": cost_usd,          # 0 for local Ollama; a real per-token cost when a cloud adapter runs
            "trace_id": trace_id,
            "prompt_version": prompt_version,
        },
        "trust": {
            "grounded": grounded,
            "grounding_sources": grounding_sources or [],
        },
    }

# Per-rule plain-English context injected into the prompt so the model
# produces grounded, file-type-aware explanations rather than generic advice.
_RULE_CONTEXT: dict[str, str] = {
    "1.1.1":  "Images and non-text elements must have a text alternative (alt attribute). "
              "Screen readers read the alt text aloud; without it the image is invisible to blind users.",
    "1.3.1":  "Information conveyed visually (headings, lists, tables, form labels) must be "
              "programmatically marked up so assistive technology can interpret the structure.",
    "1.4.1":  "Color must not be the only way to convey information — "
              "color-blind users will miss meaning that relies solely on hue.",
    "1.4.3":  "Text must have at least 4.5:1 contrast ratio against its background (3:1 for large text). "
              "Low contrast makes text unreadable for users with low vision.",
    "1.4.4":  "Text must remain readable when zoomed to 200% — "
              "fixed pixel sizes break reflow for users who enlarge their display.",
    "1.4.10": "Content must reflow to a single column at 320px width without horizontal scrolling. "
              "Side-scrolling is disorienting for users with low vision or cognitive disabilities.",
    "1.4.11": "UI components and graphical objects must have 3:1 contrast against adjacent colors. "
              "Invisible borders and icons exclude low-vision users.",
    "1.4.12": "Line height, letter spacing, and word spacing must be overridable by user stylesheets. "
              "Many users with dyslexia rely on custom spacing to read comfortably.",
    "2.1.1":  "All functionality must be operable via keyboard alone. "
              "Mouse-only interactions exclude users with motor disabilities who rely on keyboards or switch access.",
    "2.4.2":  "Every page or document must have a descriptive title. "
              "Screen reader users hear the title first and use it to orient themselves.",
    "2.4.3":  "Focus order must follow a logical reading sequence. "
              "Unpredictable tab order disorients keyboard and screen-reader users.",
    "2.4.4":  "Link text must describe the destination or purpose without surrounding context. "
              "'Click here' or 'Read more' is meaningless to screen-reader users navigating by links.",
    "2.4.6":  "Headings must be descriptive and form a logical hierarchy (h1→h2→h3, no skipped levels). "
              "Screen reader users navigate documents by jumping between headings.",
    "2.4.7":  "Keyboard focus indicator must be visible. "
              "Without it, keyboard-only users cannot tell where they are on the page.",
    "3.1.1":  "The page's primary language must be declared on the <html> element. "
              "Screen readers use this to select the correct voice and pronunciation engine.",
    "3.1.4":  "Abbreviations must have an expansion available. "
              "Users with cognitive disabilities or domain newcomers may not know what abbreviations mean.",
    "4.1.2":  "Form inputs, buttons, and custom widgets must have a programmatic name, role, and state. "
              "Without these, screen readers cannot announce what a control is or does.",
}


def _prompt(rule_id: str, rule_name: str, level: str, filename: str,
            finding_count: int, severity: str, engine_rule_ids: list[str]) -> str:
    context = _RULE_CONTEXT.get(rule_id, "")
    ids_str = ", ".join(engine_rule_ids[:5]) if engine_rule_ids else "unknown"
    return (
        f"You are an accessibility compliance assistant. A WCAG 2.1 audit found a violation.\n\n"
        f"Rule: WCAG {rule_id} — {rule_name} (Level {level})\n"
        f"File: {filename}\n"
        f"Findings: {finding_count} instance(s) — checks: {ids_str}\n"
        f"Severity: {severity}\n"
        f"Context: {context}\n\n"
        f"Reply with exactly two labeled lines:\n"
        f"WHY: one sentence — which users are blocked and how\n"
        f"FIX: one concrete action or minimal code snippet to resolve it\n\n"
        f"Be specific to this file type. Under 55 words total."
    )


def _parse(text: str) -> dict[str, str]:
    why = fix = ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("WHY:"):
            why = line[4:].strip()
        elif line.upper().startswith("FIX:"):
            fix = line[4:].strip()
    if not why and not fix:
        parts = text.strip().split("\n", 1)
        why = parts[0].strip()
        fix = parts[1].strip() if len(parts) > 1 else ""
    return {"why": why, "fix": fix}


def _trace_ai(surface: str, prompt: str, completion: str | None, t0: float, *, ok: bool,
              model: str | None = None, scan_id: str | None = None, file: str | None = None,
              provider: str = "ollama", zone: str | None = None, cost_usd: float = 0.0,
              reason: str | None = None) -> None:
    """Emit a Langfuse span + persist an ai_calls provenance row for one model call — model,
    latency, prompt size, completion, ok, and (ADR 0019 §1) which provider/zone/cost it ran on.
    model defaults to the text model; vision calls pass the vision model. `provider`/`zone`/`cost_usd`
    default to the keyless local Ollama ($0, zone derived from the endpoint) so every existing text
    caller is unchanged; a cloud vision adapter passes its own provider, zone, and real cost.

    `reason` is WHY the call ended as it did (providers.REASON_*), because `ok=0` alone does not
    tell an operator whether the endpoint was unreachable, answered an error, or answered 200
    with nothing — three different fixes that were one indistinguishable row until 2026-07-31."""
    import time as _t
    latency_ms = int((_t.monotonic() - t0) * 1000)
    mdl = model or OLLAMA_MODEL
    zn = zone or provenance()["zone"]
    try:
        import lf as _lf
        _lf.trace_ai_call(surface, mdl, latency_ms, ok=ok, prompt_chars=len(prompt or ""),
                          completion=completion, scan_id=scan_id, file=file)
    except Exception:
        pass
    # ADR 0019 Phase 0b — persist an ai_calls provenance row (provider/model/local-or-cloud zone/
    # latency/cost), the queryable + certification-embeddable record behind the card's "Generated
    # by …" line and the governance rollup. Best-effort + lazy import so it never fails the AI call.
    try:
        import core
        core.store.record_ai_call(surface=surface, provider=provider, model=mdl,
                                  zone=zn, latency_ms=latency_ms, ok=ok, cost_usd=cost_usd,
                                  scan_id=scan_id, file=file, reason=reason)
    except Exception:
        pass


def explain_finding(
    rule_id: str,
    rule_name: str,
    level: str,
    filename: str,
    finding_count: int,
    severity: str,
    engine_rule_ids: list[str],
) -> dict | None:
    """Explain a WCAG finding via the local Ollama model. Returns None when Ollama
    is unavailable / on error (the UI then shows 'AI explanation unavailable')."""
    prompt = _prompt(rule_id, rule_name, level, filename, finding_count, severity, engine_rule_ids)
    import time as _t
    _t0 = _t.monotonic()
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.3, "num_predict": 120}},
            # CPU inference of a 3B model: first call loads the model (~15s) then
            # generates. 90s bounds the worst cold-start; the old 150s left the UI's
            # "thinking…" spinner hanging for 2.5 minutes when Ollama was wedged.
            timeout=90,
        )
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        _trace_ai("explain", prompt, raw, _t0, ok=True)
        return {**_parse(raw), "model": OLLAMA_MODEL, "raw": raw}
    except Exception:
        _trace_ai("explain", prompt, None, _t0, ok=False)
        return None


def _fetch_tags() -> list[dict] | None:
    """GET /api/tags, tolerating an Ollama that is scaling up from zero.

    The demo's Ollama runs as a Container App with minReplicas=0. A cold start of an 8 GiB
    llava image takes far longer than a snappy liveness ping, and ACA holds the request open
    while the replica activates — so a cold Ollama shows up as a TIMEOUT, not a refusal.
    The old 3s probe could never survive that, so vision_is_available() returned False and
    every image fell through to "needs human alt text" instead of getting an AI draft.

    Probe fast first (OLLAMA_PROBE_TIMEOUT, warm path), and on a timeout retry once with a
    cold-start budget (OLLAMA_COLD_START_TIMEOUT). A ConnectError means nothing is listening
    (local dev with no Ollama) — that is not a cold start, so fail immediately rather than
    make every caller wait out the long budget.

    Returns the model list, or None when Ollama is unreachable.
    """
    import httpx
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT)
        r.raise_for_status()
        return r.json().get("models", []) or []
    except httpx.ConnectError:
        return None                       # no listener — not a cold start; don't wait
    except httpx.TimeoutException:
        pass                              # possibly activating from zero — retry below
    except Exception:
        return None
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=OLLAMA_COLD_START_TIMEOUT)
        r.raise_for_status()
        return r.json().get("models", []) or []
    except Exception:
        return None


def _tags_cached() -> list[dict] | None:
    """Memoise the probe for OLLAMA_PROBE_TTL seconds.

    vision_is_available() is called once per remediated FILE. Without this, a scan of 50
    documents against a cold or absent Ollama would pay the cold-start budget 50 times.
    """
    import time
    now = time.monotonic()
    if _TAGS_CACHE["at"] and (now - _TAGS_CACHE["at"]) < OLLAMA_PROBE_TTL:
        return _TAGS_CACHE["tags"]
    tags = _fetch_tags()
    _TAGS_CACHE.update(at=now, tags=tags)
    return tags


# ── Runtime endpoint override (GPU burst pattern, no revision swap) ─────────────
# The endpoint used to live only in env vars, so pointing the app at a burst GPU (or back
# to CPU) required a container revision swap — which restarts the workers and was the root
# cause of the 2026-07-11 wedged-scan incident. The admin Settings override lives in the
# store instead: refreshed here on a short TTL, it reassigns the module globals every call
# site already reads, so a switch takes effect within seconds on EVERY replica, no restart.
# Empty/absent settings mean the env-var defaults — existing deployments are unchanged.
_ENV_DEFAULTS = {"base": OLLAMA_BASE_URL, "vision": OLLAMA_VISION_MODEL, "text": OLLAMA_MODEL}
_OVERRIDE_TTL_S = 30.0
_override_checked = {"at": 0.0}


def _maybe_refresh_endpoint() -> None:
    """Re-read the runtime endpoint override (TTL-bounded) and reassign the module globals.
    Best-effort: any store hiccup leaves the current endpoint in place."""
    import time as _t
    global OLLAMA_BASE_URL, OLLAMA_VISION_MODEL, OLLAMA_MODEL
    now = _t.monotonic()
    if now - _override_checked["at"] < _OVERRIDE_TTL_S:
        return
    _override_checked["at"] = now
    try:
        import core as _core
        new_base = (_core.store.get_setting("ai_base_url") or "").strip().rstrip("/") or _ENV_DEFAULTS["base"]
        new_vision = (_core.store.get_setting("ai_vision_model") or "").strip() or _ENV_DEFAULTS["vision"]
        new_text = (_core.store.get_setting("ai_text_model") or "").strip() or _ENV_DEFAULTS["text"]
        if (new_base, new_vision, new_text) != (OLLAMA_BASE_URL, OLLAMA_VISION_MODEL, OLLAMA_MODEL):
            OLLAMA_BASE_URL, OLLAMA_VISION_MODEL, OLLAMA_MODEL = new_base, new_vision, new_text
            reset_probe_cache()   # the availability probe must re-check the NEW endpoint
            print(f"[ai] endpoint switched to {OLLAMA_BASE_URL} "
                  f"(vision={OLLAMA_VISION_MODEL}, text={OLLAMA_MODEL})", flush=True)
    except Exception:
        pass


def is_available() -> bool:
    """Quick ping to check if Ollama is reachable (tolerates a scale-from-zero cold start)."""
    _maybe_refresh_endpoint()
    return _tags_cached() is not None


def _tags_have(tags: list[dict] | None, model: str) -> bool:
    """Whether `model` is among the pulled tags, matching 'moondream' to 'moondream:latest'
    the way Ollama itself resolves a bare name."""
    if not tags or not model:
        return False
    base = model.split(":", 1)[0]
    for m in tags:
        name = m.get("name", "")
        if name == model or name.split(":", 1)[0] == base:
            return True
    return False


_MISSING_TEXT_MODEL_WARNED: set[tuple[str, str]] = set()


def model_is_available() -> bool:
    """True only when Ollama is reachable AND the configured TEXT model is pulled.

    is_available() answers a different question — 'is Ollama up' — and on 2026-07-29 that
    difference cost a day: acp-app reported available=true against an Ollama that did not
    have OLLAMA_MODEL at all, so every text generate returned 404 'model not found' while
    the status endpoint looked green. Reachability is not capability.

    Says so in the log the first time it sees a reachable Ollama missing the model, keyed on
    (endpoint, model) so a burst-GPU switch re-reports. Every text caller degrades to [] or a
    503, which is indistinguishable from a document that needed no fix — the operator needs one
    line naming the real cause, and `ollama pull` is the whole remedy.
    """
    _maybe_refresh_endpoint()
    tags = _tags_cached()
    ok = _tags_have(tags, OLLAMA_MODEL)
    if not ok and tags is not None:
        key = (OLLAMA_BASE_URL, OLLAMA_MODEL)
        if key not in _MISSING_TEXT_MODEL_WARNED:
            _MISSING_TEXT_MODEL_WARNED.add(key)
            print(f"[ai] text model {OLLAMA_MODEL!r} is NOT pulled on {OLLAMA_BASE_URL} "
                  f"(reachable, {len(tags)} model(s) present) — every text draft will be "
                  f"skipped until `ollama pull {OLLAMA_MODEL}`", flush=True)
    return ok


def vision_is_available() -> bool:
    """True only when Ollama is reachable AND the configured vision model is pulled.
    Distinct from is_available(): a text-only Ollama is 'available' but cannot describe
    images, so the alt-text remediator must gate genuine captioning on this, not is_available."""
    _maybe_refresh_endpoint()
    return _tags_have(_tags_cached(), OLLAMA_VISION_MODEL)


def vision_unavailable_reason() -> str | None:
    """One line saying WHY genuine alt text is off — or None when vision is available.

    The failure this exists for: detaching a burst GPU means clearing TWO fields (base URL and
    vision model, see deploy/gpu/README.md), and clearing only the first leaves a GPU-only model
    name pinned in the admin override. The override beats the env default indefinitely, so the
    endpoint goes back to the CPU box while the platform keeps asking it for a model it has never
    had. vision_available:false was the only symptom, which reads as "the endpoint is broken" and
    sends you to check the container — when the wrong thing is the NAME, and it is one field away.
    On 2026-07-29 that cost an afternoon of diagnosis, and every env-var fix was invisible
    underneath the override.

    config_sources() answers the neighbouring question — WHERE each value came from — and this
    defers to it rather than inferring the source by comparing against _ENV_DEFAULTS: an override
    deliberately set to the same string as the deploy default is still an override, and only the
    store knows that.
    """
    _maybe_refresh_endpoint()
    tags = _tags_cached()
    if tags is None:
        return f"Ollama at {OLLAMA_BASE_URL} is not reachable"
    if _tags_have(tags, OLLAMA_VISION_MODEL):
        return None
    names = sorted(n for n in (m.get("name", "") for m in tags) if n)
    have = ", ".join(names) if names else "no models at all"
    why = (f"the configured vision model '{OLLAMA_VISION_MODEL}' is not present at "
           f"{OLLAMA_BASE_URL} (available: {have})")
    # Name the source, because the fix differs: an override is cleared in Settings, a deploy
    # default needs the model pulled or baked into the image.
    if config_sources().get("vision_model") == "override":
        why += (f" — this name comes from the admin Settings override, not the deploy default "
                f"('{_ENV_DEFAULTS['vision']}'); clear the Vision model field to fall back to it")
    return why


def config_sources() -> dict:
    """Where each effective endpoint value came from: 'override' (admin Settings, stored in
    the DB) or 'env' (the deploy's env var).

    A stored override outranks the env var indefinitely, and nothing used to say so. On
    2026-07-29 `ai_vision_model` still held `qwen2.5vl:7b` from a GPU pod that had since been
    torn down; changing OLLAMA_VISION_MODEL on the container app therefore did nothing, and
    /ai/status reported only the effective value — which read as "the env var did not apply"
    rather than "a saved override is winning". Reporting the source makes that visible.
    """
    _maybe_refresh_endpoint()
    try:
        import core as _core
        stored = {k: (_core.store.get_setting(f"ai_{k}") or "").strip()
                  for k in ("base_url", "vision_model", "text_model")}
    except Exception:
        stored = {}
    return {"base_url": "override" if stored.get("base_url") else "env",
            "vision_model": "override" if stored.get("vision_model") else "env",
            "model": "override" if stored.get("text_model") else "env"}


# ── Vision alt text (llava-class model) ───────────────────────────────────────
# Genuine, image-derived alt text — the gap the text model cannot fill. Extract an
# image's bytes, send them to the vision model, write the returned one-liner as alt.
# Everything degrades to None (→ faithful source / human review) when unavailable.
_ALT_LABEL = re.compile(r"^\s*(?:alt(?:\s*text)?|description|caption|answer)\s*[:\-]\s*", re.I)
_ALT_LEAD = re.compile(
    r"^\s*(?:the|a|an|this)?\s*(?:image|picture|photo|photograph|graphic|illustration|screenshot|figure)\s+"
    r"(?:shows|depicts|of|is\s+of|is\s+a|contains|displays|features|portrays|represents|"
    # "presents" was the gap that showed up in real output, not in review: moondream answered
    # "The image presents a bar graph with six vertical bars…" and this pattern passed it through
    # untouched, so the redundant lead shipped into the alt attribute. A screen reader has already
    # announced that it is an image; "The image presents" is exactly the wording this regex exists
    # to remove, and it was one verb away from doing so.
    #
    # illustrates/captures are added alongside it. They are the same register and the same failure
    # — a caption-shaped opening — and a list that has now been caught missing one member is worth
    # widening past the single instance that caught it, since each miss is silent by construction:
    # the output is fluent, the tests pass, and only the redundancy reaches the user.
    r"presents|illustrates|captures|"
    r"is\s+a\s+representation\s+of)\s*[:,-]?\s*", re.I)


def _clean_alt(text: str) -> str:
    """Normalise a model reply into a single-line, descr-safe alt string. Strips echoed
    labels ('Alt text:'), redundant 'this image shows' leads (a screen reader already
    announces it's an image, and the .NET AltTextRule rejects a bare 'image'), collapses
    whitespace, and bounds the length."""
    t = (text or "").strip().strip('"').strip("'").strip()
    t = _ALT_LABEL.sub("", t).strip().strip('"').strip("'").strip()
    t = re.sub(r"\s+", " ", t)
    t = _ALT_LEAD.sub("", t).strip()
    # Capitalise the first letter (leads were stripped in lower-case-friendly form).
    if t:
        t = t[0].upper() + t[1:]
    if len(t) > 250:
        t = t[:250].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t.strip()


def _vision_prompt(filename: str, context: str, style: str = "", guidance: str = "") -> str:
    where = f" It appears in the document '{filename}'." if filename else ""
    near = f" Nearby text for context: {context.strip()[:200]}" if context and context.strip() else ""
    # Reviewer-directed refinement (#131) — a length steer only; the description stays grounded in
    # what the model actually sees. Unknown/absent style → the default concise sentence.
    length = {
        "shorter": "Reply with ONE very short phrase (under 10 words) — just the essential subject. ",
        "detailed": "Reply with ONE fuller sentence (up to 40 words) that also describes the key visual "
                    "elements. State a number, label, or value ONLY if you can clearly read it in the "
                    "image — never estimate or invent figures; if the values are not legible, describe "
                    "what the image shows without them. ",
    }.get(style,
          "Reply with ONE concise sentence (under 30 words) that includes the key text verbatim where "
          "it carries meaning. ")
    return (
        "You are writing alternative text so a person using a screen reader understands what this "
        "image conveys. First READ any text inside the image — a headline, labels, axis names, "
        "legend, or data values are often the whole point and must not be lost. If it is a chart, "
        "graph, or diagram, name the type and state what it compares and the single most important "
        "figure or takeaway. If it is a photo or illustration, describe the content and its meaning. "
        f"{length}"
        "Do not begin with 'image of', 'picture of', or 'this image shows'."
        # ADR 0021 — org house style, injected only when review memory is active for this org.
        f"{(chr(10) + guidance) if guidance else ''}"
        f"{where}{near}\nAlt text:"
    )


# A compact vision model can answer the full _vision_prompt with a COMPLETELY EMPTY reply —
# HTTP 200, {"response": "", "done_reason": "stop"}, no error anywhere. Measured 2026-07-31
# against the real endpoint (moondream, the CPU deploy default), one image, one variable at a time:
#
#   "Describe this image in one concise sentence under 30 words."  → a real description
#   …the same, plus a trailing "\nAlt text:" label                 → EMPTY
#   …the same, plus "Do not begin with image of."                  → EMPTY
#   a longer multi-clause instruction, no label and no negation    → EMPTY
#
# Three independent triggers, each sufficient on its own. That is why simply shortening the prompt
# does NOT fix this, and why the trailing label alone was ruled out earlier and the case wrongly
# closed. A capable model (qwen2.5vl, a cloud adapter) handles all three happily and writes better
# alt text for the fuller instruction, so the real prompt is left exactly as it is and this bare
# form is only ever a RETRY. The two things it drops — the negation and the "Alt text:" label —
# cost nothing: _clean_alt already strips an "Alt text:" prefix (_ALT_LABEL) and an "image of" /
# "this image shows" lead (_ALT_LEAD) from whatever comes back.
_MINIMAL_VISION_STEER = {
    "shorter": "in under 10 words",
    "detailed": "in one sentence of up to 40 words",
}


def _minimal_vision_prompt(style: str = "") -> str:
    """The bare retry prompt for a model that returned nothing to the full one. Keep it a single
    short imperative with no negation and no trailing label — each of those alone is enough to
    make a compact model reply with nothing. Re-check `test_minimal_vision_prompt_stays_bare`."""
    steer = _MINIMAL_VISION_STEER.get(style, "in one concise sentence under 30 words")
    return f"Describe this image {steer}."


def _vision_generate(prompt: str, image_bytes: bytes, *, scan_id: str | None = None,
                     file: str | None = None, model: str | None = None, clean: bool = True) -> str | None:
    """One bounded, Langfuse-traced vision call → a cleaned single-line alt string, or None.
    Shared by describe_image and describe_image_structured so there is exactly one HTTP
    path, timeout, and honesty guard (a one-word reply won't clear WCAG 1.1.1 → treated as
    a miss so the caller falls back rather than writing junk that fails re-scan).

    `model` overrides the vision model for this one call (the validator uses a SECOND model for a
    genuine cross-check). `clean=False` returns the raw reply (the validator parses its own format
    rather than an alt string)."""
    import time as _t
    _t0 = _t.monotonic()
    # The transport goes through the provider seam (ADR 0019 §1): today that is always the local
    # Ollama adapter (keyless, $0), so this is byte-for-byte the previous inline call — but the
    # provider/zone/cost it reports is what flows into the trace, so a cloud adapter records its
    # real cost and zone here without touching this function again. generate() never raises.
    import providers as _providers
    prov = _providers.active_vision_provider()
    res = prov.generate(prompt, image_bytes, model=model, timeout=OLLAMA_VISION_TIMEOUT)
    # Fallback floor (ADR 0022): if the default GPU provider missed — a serverless cold-start over the
    # timeout, or the endpoint down — retry on the always-available local CPU Ollama so the finding
    # still gets *a* draft (degraded, not broken). Recorded honestly: the trace/ai_calls row reports
    # whichever provider ACTUALLY served the call, so provenance never claims GPU when CPU ran.
    if not res.get("ok") and getattr(prov, "name", "") != "ollama":
        fb = _providers.local_vision_provider()
        if getattr(fb, "name", "") == "ollama":
            res = fb.generate(prompt, image_bytes, model=None, timeout=OLLAMA_VISION_TIMEOUT)
    mdl = res.get("model") or model or OLLAMA_VISION_MODEL
    _tr = dict(model=mdl, scan_id=scan_id, file=file, provider=res.get("provider", "ollama"),
               zone=res.get("zone"), cost_usd=res.get("cost_usd", 0.0))
    raw = (res.get("text") or "").strip() if res.get("ok") else ""
    if not res.get("ok") or not raw:
        # The adapter already logged the distinguishing detail and named the mode; carry its
        # reason through so the ai_calls row says which one rather than only that it failed.
        _trace_ai("vision", prompt, None, _t0, ok=False,
                  reason=res.get("reason") or _providers.REASON_TRANSPORT, **_tr)
        return None
    if not clean:
        _trace_ai("vision", prompt, raw, _t0, ok=True, reason=_providers.REASON_OK, **_tr)
        return raw or None
    alt = _clean_alt(raw)
    ok = bool(alt) and len(alt) >= 8 and " " in alt
    # A fourth way to end at None, and the transport had nothing to do with it: the model DID
    # answer, and the honesty guard rejected the answer as too thin to clear WCAG 1.1.1. Left
    # unnamed it reads on the row exactly like a dead endpoint, which sends the next operator
    # to look at Ollama for a problem that is in the reply.
    if not ok:
        print(f"[vision] {_tr['provider']} · model={mdl} — reply rejected by the alt-text guard: "
              f"{alt!r} (needs ≥8 chars and more than one word)", flush=True)
    _trace_ai("vision", prompt, alt, _t0, ok=ok,
              reason=_providers.REASON_OK if ok else _providers.REASON_UNUSABLE, **_tr)
    return alt if ok else None


def describe_image(image_bytes: bytes, *, filename: str = "", context: str = "", style: str = "",
                   guidance: str = "", scan_id: str | None = None, file: str | None = None) -> dict | None:
    """Generate genuine alt text for one image via the local vision model.

    Sends the raw image bytes (base64) to Ollama /api/generate with OLLAMA_VISION_MODEL
    and an alt-text prompt. `style` ('shorter' | 'detailed' | '') lets a reviewer re-draft at a
    different length (#131) — a length steer only, the description stays grounded in the image.
    Returns {"alt", "model"} or None when the model is unavailable / errors / returns nothing
    usable. Traced through Langfuse (surface 'vision') — model, latency, prompt size, ok."""
    if not image_bytes:
        return None
    alt = _vision_generate(_vision_prompt(filename, context, style, guidance), image_bytes,
                           scan_id=scan_id, file=file)
    if not alt:
        # The model may have replied with nothing at all rather than failed — see
        # _minimal_vision_prompt. One bare retry, which is the difference between a working
        # reviewer re-draft (#131) and a button that silently does nothing on a compact model.
        alt = _vision_generate(_minimal_vision_prompt(style), image_bytes,
                               scan_id=scan_id, file=file)
    return {"alt": alt, "model": OLLAMA_VISION_MODEL} if alt else None


# An optional SECOND vision model for the validator — a different model catches a confident-but-wrong
# draft that the drafting model would rubber-stamp (genuine model agreement, ADR 0019 §3). Unset →
# self-check with the same model (still useful: flags obvious omissions/mismatches).
_ALT_VALIDATOR_MODEL = os.environ.get("ACP_ALT_VALIDATOR_MODEL", "")




_STOP = frozenset((
    "the", "a", "an", "of", "in", "on", "and", "or", "for", "to", "with", "is", "are", "it", "its",
    "this", "that", "these", "those", "image", "picture", "photo", "shows", "showing", "displays",
    "displaying", "depicts", "there", "which", "each", "at", "by", "as", "from", "into", "about",
    "key", "takeaway", "represents", "representing", "different", "various", "titled", "title",
))


def _content_terms(text: str) -> set:
    """Significant content words (lowercased, stopwords + short words dropped) — the nouns/verbs that
    carry meaning, so two descriptions of the same thing overlap and of different things don't."""
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP}


def validate_alt_text(image_bytes: bytes, alt: str, *, filename: str = "", model: str | None = None,
                      scan_id: str | None = None, file: str | None = None) -> dict | None:
    """Second-opinion validation of a drafted alt text by CONSISTENCY cross-check (ADR 0019 §3
    acceptance / #123) — the honest, robust design after finding that asking a weak VLM "is this ok?"
    is unreliable (it rubber-stamps, then nitpicks). Instead the model INDEPENDENTLY re-describes the
    image, and we compare content-word overlap with the proposed alt:

      - two independent descriptions that agree on the subject/type → 'consistent' (a real signal the
        draft is on the right track — feeds the auto-apply/auto-approve tier);
      - a strong divergence → 'divergent' (route to a human, and hand them the second description as
        concrete evidence: "the model independently saw: '…'").

    Using a DIFFERENT model (ACP_ALT_VALIDATOR_MODEL / `model`) makes it genuine model agreement. The
    verdict is an enum + the two descriptions — NOT a fabricated score (ADR 0016). It reliably catches
    a WRONG subject/type (the common gross error); it does NOT catch a wrong chart NUMBER (both
    generations mis-read equally — that limit is why charts still get human review). Returns
    {verdict, agrees, second_opinion, shared_terms, validator_model} or None when unavailable."""
    if not image_bytes or not (alt or "").strip():
        return None
    vmodel = model or _ALT_VALIDATOR_MODEL or None
    prompt = (
        "In one sentence, describe what this image is and what it shows, for someone who cannot see "
        "it. Name the kind of image (e.g. bar chart, flowchart, photo) and its subject."
    )
    second = _vision_generate(prompt, image_bytes, scan_id=scan_id, file=file, model=vmodel)
    if not second:
        return None
    a, b = _content_terms(alt), _content_terms(second)
    shared = sorted(a & b)
    # Measure how much of the ALT the independent description CONFIRMS (recall of the alt's own
    # content words), not raw overlap — so a short correct alt vs a long re-description isn't
    # falsely flagged. Back it with a Jaccard floor so a 1-word alt can't trivially "confirm".
    alt_recall = len(shared) / (len(a) or 1)
    jaccard = len(shared) / (len(a | b) or 1)
    # Consistent when the two independent descriptions agree on the subject/type; divergent on a
    # gross mismatch. Thresholds are internal heuristics; the reviewer sees the enum + both
    # descriptions, never a number (ADR 0016).
    consistent = (len(shared) >= 2 and alt_recall >= 0.4) or jaccard >= 0.22
    verdict = "consistent" if consistent else "divergent"
    return {"verdict": verdict, "agrees": verdict == "consistent",
            "second_opinion": second, "shared_terms": shared,
            "validator_model": vmodel or OLLAMA_VISION_MODEL}


def _structured_vision_prompt(filename: str, ocr_text: str, context: str) -> str:
    """A structured alt-text prompt for a data-bearing image (chart, diagram, screenshot).
    Feeds the OCR-read text so the description is ANCHORED in the image's real labels
    (headline, categories) instead of a free vision guess."""
    where = f" It appears in the document '{filename}'." if filename else ""
    seen = re.sub(r"\s+", " ", (ocr_text or "").strip())[:400]
    read = f"\nText read from the image (OCR): {seen}" if seen else ""
    near = f"\nNearby document text: {context.strip()[:200]}" if context and context.strip() else ""
    return (
        "You are writing alternative text for a chart, diagram, or screenshot so a screen-"
        "reader user understands what it conveys. Using the text read from the image, write "
        "ONE concise sentence (under 25 words) that states the image's headline/subject, its "
        "type (e.g. bar chart, line graph, table, screenshot), and the single key takeaway. "
        "State the takeaway as a COMPARISON or TREND in words. Do NOT state specific numeric values "
        "or pair numbers with categories (e.g. 'North at 150') — reading a chart's exact values is "
        "unreliable, a wrong figure is worse than none, and a human confirms the specifics. Do not "
        "begin with 'image of', 'picture of', or 'this image shows'."
        f"{where}{read}{near}\nAlt text:"
    )


# An IMAGE OF TEXT is the one 1.1.1 case where the correct alt text is not a description at
# all — it is the text itself (WCAG 1.1.1 / F30: "if the image is text, the alt is that text").
# Handing such an image to a compact captioner actively destroys information. Measured on
# 2026-07-29 against moondream and the real demo fixture — a white page reading "Quarterly
# Revenue Report 2026 / Total revenue increased fourteen percent / across every regional
# business unit" — the model rewrote the year 2026 as 2006 in 5/5 runs, invented "a chart or
# graph" that is not present, described the FILENAME as if it were visible content, and in one
# run leaked the prompt's own "OCR:" marker into the alt. OCR had read the text correctly every
# time. So when the OCR text already reads as prose, transcribe it and skip the paraphrase.
_TEXT_IMAGE_MIN_WORDS = 4


def _looks_like_an_image_of_text(ocr_txt: str) -> bool:
    """True when OCR read connected prose (a title card, a pull quote, a text slide) rather than
    the scattered fragments a chart's axes and legend produce.

    Deliberately conservative: a chart still wants a DESCRIPTION ('bar chart comparing …'),
    and transcribing its axis labels would be worse than the model's paraphrase. Requires
    several real words and a low share of number-ish/one-character tokens.
    """
    toks = re.findall(r"\S+", re.sub(r"\s+", " ", ocr_txt or "").strip())
    if len(toks) < _TEXT_IMAGE_MIN_WORDS:
        return False
    words = [t for t in toks if re.fullmatch(r"[A-Za-z][A-Za-z'’\-]{1,}[.,;:!?]?", t)]
    return len(words) >= _TEXT_IMAGE_MIN_WORDS and (len(words) / len(toks)) >= 0.6


def _transcribed_alt(ocr_txt: str) -> str:
    """The image's own text as an alt string: whitespace collapsed, length-bounded, no model in
    the loop. Not run through _clean_alt — that strips 'image of'-style leads, which is right for
    a model's reply and wrong for a verbatim transcription."""
    t = re.sub(r"\s+", " ", (ocr_txt or "").strip())
    if len(t) > 250:
        t = t[:250].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def describe_image_structured(image_bytes: bytes, *, filename: str = "", context: str = "",
                              scan_id: str | None = None, file: str | None = None,
                              allow_transcription: bool = False) -> dict | None:
    """Structured, OCR-anchored alt text (WCAG 1.1.1). Returns
    {"alt", "grounded", "evidence", "model"} or None.

    `grounded` is True when OCR read real text from the image (a chart's headline/labels, a
    screenshot's words): the description is then anchored in extractable content, a High-
    confidence derivation a remediator may auto-apply. When OCR finds nothing (a textless
    photo) the description is a pure vision guess — `grounded` is False and the caller
    surfaces it as a Medium proposal for human confirmation rather than auto-applying, since
    a machine cannot judge whether a guessed description conveys the author's intent.

    `allow_transcription` opts into the image-of-text path: when the OCR text reads as prose,
    it is returned verbatim as the alt and no model runs. Only set it when `image_bytes` is the
    image ITSELF. The PDF remediator must not — it OCRs a render of the whole PAGE, so "this
    render contains prose" means "the page has paragraphs", not "this figure is an image of
    text", and transcribing would hand a figure the page's body copy as its alt."""
    if not image_bytes:
        return None
    ocr_txt = ""
    try:
        import ocr as _ocr
        ocr_txt = _ocr.ocr_text(image_bytes)
    except Exception:
        ocr_txt = ""
    grounded = len(re.findall(r"[A-Za-z]{2,}", ocr_txt)) >= 2
    # An image of text: the text IS the alt text, and no model needs to see it. Returning here
    # is both more accurate and cheaper than a paraphrase — see _looks_like_an_image_of_text.
    if allow_transcription and grounded and _looks_like_an_image_of_text(ocr_txt):
        transcribed = _transcribed_alt(ocr_txt)
        if transcribed:
            return {"alt": transcribed, "grounded": True,
                    "evidence": "transcribed verbatim from the text in the image — no model "
                                "paraphrase, so no figure or label can drift",
                    "model": None, "source": "ocr"}
    if grounded:
        prompt = _structured_vision_prompt(filename, ocr_txt, context)
    else:
        prompt = _vision_prompt(filename, context)
    alt = _vision_generate(prompt, image_bytes, scan_id=scan_id, file=file)
    model_used = OLLAMA_VISION_MODEL
    # Acceptance-gated cloud escalation (ADR 0019 §2/§3c): a local result that did not ground
    # (ungrounded, or the local model returned nothing usable) MAY escalate to the configured cloud
    # provider — only when an admin has enabled one and its secret is present, so the default keyless
    # build never leaves the box. The escalation is transparent: the numbered path is attached, not
    # hidden or dressed up as a score.
    escalation = None
    if not grounded:
        esc = _escalate_vision(prompt, image_bytes, scan_id=scan_id, file=file)
        if esc:
            alt = esc["alt"]
            model_used = esc["model"]
            escalation = esc
    if not alt:
        return None
    if grounded:
        snippet = re.sub(r"\s+", " ", ocr_txt).strip()[:80]
        evidence = f"anchored in text read from the image (OCR: “{snippet}”)"
    elif escalation:
        evidence = ("a stronger cloud vision model produced this after the local model could not "
                    "ground it — confirm it matches the intent")
    else:
        evidence = "vision description only — no text in the image to anchor it; confirm it matches the intent"
    out = {"alt": alt, "grounded": grounded, "evidence": evidence, "model": model_used}
    if escalation:
        out.update(provider=escalation["provider"], processing_zone=escalation["zone"],
                   cost_usd=escalation["cost_usd"], escalation=escalation["steps"])
    return out


def _escalate_vision(prompt: str, image_bytes: bytes, *, scan_id: str | None = None,
                     file: str | None = None) -> dict | None:
    """Escalate one ungrounded vision description to the configured cloud provider (ADR 0019 §3c). Returns
    a better draft + the transparent numbered path, or None when no cloud provider is configured /
    enabled / key-present, or the cloud call fails or returns nothing usable. The cloud call is
    traced + cost-recorded through the same ai_calls provenance path as every other AI call."""
    import providers as _providers
    cloud = _providers.cloud_vision_provider()
    if cloud is None:
        return None
    import time as _t
    _t0 = _t.monotonic()
    res = cloud.generate(prompt, image_bytes, timeout=OLLAMA_VISION_TIMEOUT)
    mdl = res.get("model")
    # Stay vendor-agnostic (rule 6): the provider names itself in its result; ai.py never hardcodes
    # a cloud vendor. 'cloud' is only a defensive fallback if an adapter omitted its own name.
    _trace_ai("vision", prompt, res.get("text"), _t0, ok=bool(res.get("ok")), model=mdl,
              provider=res.get("provider") or "cloud", zone=res.get("zone"),
              cost_usd=res.get("cost_usd", 0.0), scan_id=scan_id, file=file,
              reason=res.get("reason"))
    if not res.get("ok"):
        return None
    alt = _clean_alt(res.get("text") or "")
    if not (alt and len(alt) >= 8 and " " in alt):
        return None
    return {
        "alt": alt, "model": mdl, "provider": res.get("provider"), "zone": res.get("zone"),
        "cost_usd": res.get("cost_usd", 0.0),
        "steps": [
            {"provider": "ollama", "zone": provenance()["zone"],
             "outcome": "no grounded description"},
            {"provider": res.get("provider"), "zone": res.get("zone"),
             "outcome": "produced a description", "cost_usd": res.get("cost_usd", 0.0)},
        ],
    }


_ORDER_FIRST_ITEM = re.compile(r"(?:^|\s)(1\s*[.)]\s+\S)")


def _strip_order_preamble(order: str) -> str:
    """Drop a vision model's throat-clearing before an enumerated reading order.

    Observed verbatim from llava:7b on a real discharge-instructions page:

        "The image shows a document with text and graphics. To provide an accurate reading
         order for this page, I would describe the content in a linear fashion from top to
         bottom: 1. Logo at the top left corner 2. Title 3. ..."

    The reviewer's card renders this string as the proposed reading order, so those first two
    sentences sit in front of the answer. When an enumerated list is present the list IS the
    order — start there. When it is not, the prose is all we have; return it untouched rather
    than guess where the answer begins. Deterministic: no prompt change, nothing invented, and
    a model that never enumerates is unaffected."""
    if not order:
        return order
    m = _ORDER_FIRST_ITEM.search(order)
    if not m:
        return order
    trimmed = order[m.start(1):].strip()
    # Refuse to trim away the answer: a trailing "1." with no items behind it is not an order.
    return trimmed if len(trimmed) >= 12 else order


def describe_reading_order(page_bytes: bytes, *, filename: str = "",
                           scan_id: str | None = None, file: str | None = None) -> dict | None:
    """Vision-proposed reading order for a scanned / multi-column page (WCAG 1.3.2).
    Returns {"order", "model"} — a short human-readable reading sequence — or None. Bounded
    and traced like describe_image. This is only ever a PROPOSAL a human confirms (a machine
    cannot be trusted to fix reading order on an untagged scan), never an auto-fix."""
    if not page_bytes:
        return None
    import base64
    import time as _t
    where = f" from the document '{filename}'" if filename else ""
    prompt = (
        f"This is one page{where}. A screen reader reads content in a single linear order. "
        "In one or two short sentences, state the correct reading order of this page's blocks "
        "(columns, headings, sidebars, captions, tables) — e.g. 'Read the left column top to "
        "bottom, then the right column, then the footer.' Be specific to the layout you see."
    )
    b64 = base64.b64encode(page_bytes).decode("ascii")
    _t0 = _t.monotonic()
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_VISION_MODEL, "prompt": prompt, "images": [b64],
                  "stream": False, "options": {"temperature": 0.2, "num_predict": 140}},
            timeout=OLLAMA_VISION_TIMEOUT,
        )
        r.raise_for_status()
        order = re.sub(r"\s+", " ", (r.json().get("response", "") or "").strip())
        order = _strip_order_preamble(order)[:400]
        ok = bool(order) and len(order) >= 12
        _trace_ai("vision", prompt, order, _t0, ok=ok,
                  model=OLLAMA_VISION_MODEL, scan_id=scan_id, file=file)
        return {"order": order, "model": OLLAMA_VISION_MODEL} if ok else None
    except Exception:
        _trace_ai("vision", prompt, None, _t0, ok=False,
                  model=OLLAMA_VISION_MODEL, scan_id=scan_id, file=file)
        return None


# ── AI-drafted fix suggestions (semantic HITL lane) ───────────────────────────
# For findings that can't be closed deterministically (alt text, link purpose, title),
# the text model drafts a concrete, human-approvable value the reviewer accepts or edits.
# Honest limit: the text model can't see images, so 1.1.1 alt drafts are fill-in templates
# (real vision alt-text would need a llava-class model). Everything degrades to None when
# Ollama is unreachable — the reviewer then writes the value manually.
_SUGGEST_KIND: dict[str, tuple[str, str]] = {
    "1.1.1": ("alt text", "concise descriptive alternative text (under 15 words) for an image"),
    "2.4.4": ("link text", "descriptive link text stating the destination or purpose without surrounding context"),
    "2.4.9": ("link text", "descriptive link text understandable from the link alone"),
    "2.4.2": ("title", "a concise, descriptive document title"),
    "2.4.10": ("heading", "a short, descriptive section heading (3-8 words) that names what the "
                          "passage in the finding detail is about — reply with the heading only"),
    "2.4.6": ("title", "a short, descriptive slide title (3-8 words) that names what the slide "
                       "content in the finding detail is about — reply with the title only"),
    "1.3.3": ("rewrite", "a rewrite of the instruction that does not rely on shape, colour, size, or "
                         "on-screen position — refer to controls by their visible label or name instead"),
}


def _suggest_prompt(rule_id: str, rule_name: str, filename: str, detail: str, guidance: str = "") -> str:
    kind, want = _SUGGEST_KIND.get(rule_id, ("fix", "a concrete corrected value"))
    ctx = f"\nFinding detail: {detail}" if detail else ""
    house = f"\n{guidance}" if guidance else ""    # ADR 0021 org house style (memory active)
    vision_note = ""
    if rule_id == "1.1.1":
        vision_note = ("\nYou cannot see the image. Produce a SHORT fill-in-the-blank template the author "
                       "completes, e.g. 'Describe: [what the image shows and why it matters here]'.")
    elif rule_id == "1.3.3":
        vision_note = ("\nThe instruction above relies on a sensory characteristic (shape / colour / size / "
                       "position such as 'the green button' or 'the box on the right'). Rewrite it to identify "
                       "the control by its visible text label or name instead, keeping the same meaning. If the "
                       "label is unknown, use a clearly-marked placeholder like '[button label]'.")
    return (
        f"You are an accessibility remediation assistant. A WCAG {rule_id} ({rule_name}) issue was found "
        f"in the document '{filename}'.{ctx}\n"
        f"Draft {want}.{vision_note}{house}\n"
        f"Reply with ONLY the suggested {kind} — no preamble, no quotes, under 30 words."
    )


def suggest_fix(rule_id: str, rule_name: str, level: str, filename: str,
                detail: str = "", image_bytes: bytes | None = None, style: str = "",
                guidance: str = "") -> dict | None:
    """Draft a concrete, human-approvable fix value (alt text / link text / title) for a
    semantic finding via the local model. Returns None when Ollama is unavailable.

    For 1.1.1 with the image's bytes in hand, uses the VISION model to produce real,
    image-derived alt text (is_template=False) instead of the text model's fill-in
    template — the reviewer then approves genuine alt text rather than a blank to fill.
    `style` re-drafts an image description shorter/longer at the reviewer's request (#131).
    `guidance` (ADR 0021) is the org house-style block, injected into the prompt when review
    memory is active — "" (the default) leaves the prompt byte-identical to pre-memory."""
    if rule_id == "1.1.1" and image_bytes:
        res = describe_image(image_bytes, filename=filename, context=detail, style=style,
                             guidance=guidance)
        if res:
            return {"suggestion": res["alt"], "kind": "alt text",
                    "is_template": False, "model": res["model"]}
        # vision unavailable / unusable → fall through to the text template below.
    prompt = _suggest_prompt(rule_id, rule_name, filename, detail, guidance)
    import time as _t
    _t0 = _t.monotonic()
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  # num_predict is a CEILING, not a target: a model that finishes stops at its own
                  # EOS, so raising this costs a non-reasoning model nothing. 60 was sized for the
                  # answer alone — "under 30 words" — and that silently excluded every REASONING
                  # model from this lane. qwen3 and its kind emit a thinking pass first and spend
                  # the whole budget on it, so the answer is never reached: the response comes back
                  # EMPTY, `if not text: return None` fires, and the card says "no draft".
                  #
                  # Measured on qwen3:14b with this exact prompt: num_predict=60 returns 0
                  # characters in 2.2s; num_predict=400 returns "Access the benchmark document for
                  # detailed information." in 14.0s. Nothing was wrong with the model — the budget
                  # ran out mid-thought, and the failure was indistinguishable from a model that
                  # cannot do the task. Every comparison of a reasoning model against this lane was
                  # measuring the cap.
                  "options": {"temperature": 0.4, "num_predict": 400}},
            timeout=90,
        )
        r.raise_for_status()
        text = r.json().get("response", "").strip().strip('"').strip()
        _trace_ai("suggest", prompt, text, _t0, ok=bool(text))
        if not text:
            return None
        kind = _SUGGEST_KIND.get(rule_id, ("fix", ""))[0]
        out = {"suggestion": text, "kind": kind,
               "is_template": rule_id == "1.1.1", "model": OLLAMA_MODEL}
        if out["is_template"]:
            # Be exact about WHY this is a blank to fill rather than a description. The card
            # used to say "no vision model described this image" in both cases, which reads as
            # "llava looked and failed" even when no image was ever handed to a vision model.
            out["reason"] = (
                "Template only — no vision model is available to look at this image. "
                "Rewrite it before approving."
                if image_bytes else
                "Template only — this text model cannot see the image, so it guessed from the "
                "filename. Pick the image above and draft again, or write the value yourself."
            )
        return out
    except Exception:
        return None


def simplify_text(text: str, *, scan_id: str | None = None, file: str | None = None) -> str | None:
    """Plain-language rewrite of a dense passage for WCAG 3.1.5 (reading level), via the local text
    model. The prompt PRESERVES every fact, name, and number — it simplifies wording and breaks up
    long sentences, it does NOT summarise or drop content (that would change meaning, not readability,
    and could invent/omit facts — ADR 0016). Returns the simpler text or None. HITL by design: the
    reviewer approves the rewrite; nothing is auto-applied to the document."""
    src = (text or "").strip()
    # model_is_available(), not is_available(): the POST below names OLLAMA_MODEL, so a reachable
    # Ollama that never pulled it 404s on every call and this returns None either way — one probe
    # earlier is the difference between a logged cause and a silent empty proposal list.
    if not src or not model_is_available():
        return None
    prompt = (
        "Rewrite the text below in plain, clear language a general reader can follow (about an "
        "8th-grade reading level). Keep EVERY fact, name, and number exactly as given — do not add, "
        "remove, or change any information; only simplify the wording and split long sentences. "
        "Reply with the rewritten text only, no preamble.\n\n"
        f"Text: {src[:700]}\n\nPlain-language version:"
    )
    import time as _t
    _t0 = _t.monotonic()
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.3, "num_predict": 220}},
            timeout=OLLAMA_VISION_TIMEOUT,
        )
        r.raise_for_status()
        out = (r.json().get("response", "") or "").strip().strip('"').strip()
        out = re.sub(r"^(plain[- ]language version|rewritten text|here is[^:]*)\s*:\s*", "", out, flags=re.I).strip()
        _trace_ai("simplify", prompt, out, _t0, ok=bool(out), scan_id=scan_id, file=file)
        # Guard: a rewrite must actually be shorter/simpler and non-trivial, else treat as a miss.
        return out if (out and len(out) >= 20 and out.lower() != src.lower()) else None
    except Exception:
        _trace_ai("simplify", prompt, None, _t0, ok=False, scan_id=scan_id, file=file)
        return None


# ── Compliance digest (ADR 0009 follow-on) ────────────────────────────────────
# Deterministic facts (always reliable, grounded in real numbers) + an AI-written
# executive narrative on top, with a deterministic-prose fallback. The model only
# writes free prose from the supplied facts — it never invents numbers.
def _digest_facts(d: dict) -> dict:
    score, total, cert = d.get("avg_score"), d.get("total", 0), d.get("certifiable", 0)
    reg, improved, top = d.get("regressed", []), d.get("improved_count", 0), d.get("top_issues", [])
    pii_docs, delta = d.get("pii_docs", 0), d.get("score_delta")
    pl = lambda n: "" if n == 1 else "s"  # noqa: E731
    changed = []
    if delta is not None and delta != 0:
        changed.append(f"Estate score {'rose' if delta > 0 else 'fell'} {abs(delta)} point{pl(abs(delta))} to {score}/100 since the last scan.")
    if reg:
        w = reg[0]
        changed.append(f"{len(reg)} document{pl(len(reg))} regressed — worst: {w['file']} ({w['prev']}→{w['cur']}).")
    if improved:
        changed.append(f"{improved} document{pl(improved)} improved.")
    if pii_docs:
        changed.append(f"{pii_docs} document{pl(pii_docs)} contain sensitive data flagged for review.")
    top_issue = (f"{top[0]['name']} ({top[0]['sc']}) fails on {top[0]['fail']} document{pl(top[0]['fail'])} — the biggest systemic gap." if top else None)
    if top:
        next_action = f"Fix {top[0]['name']} across the estate — it clears the most documents toward AA."
    elif cert < total:
        next_action = f"Remediate the {total - cert} non-conformant document{pl(total - cert)} to reach full coverage."
    else:
        next_action = "Maintain coverage — schedule periodic re-scans to catch regressions."
    return {"headline": f"{cert} of {total} documents conformant ({score}/100 average).",
            "score": score, "changed": changed, "top_issue": top_issue, "next_action": next_action}


def _digest_prompt(facts: dict) -> str:
    bullets = "\n".join(f"- {c}" for c in facts["changed"]) or "- No notable changes since the last scan."
    return (
        "You are an accessibility compliance analyst. Write ONE short executive paragraph "
        "(2-3 sentences, plain English, no markdown, no preamble, no bullet points) "
        "summarising a document estate's WCAG 2.1 accessibility compliance for a compliance "
        "officer. Use ONLY these facts; never invent numbers.\n\n"
        f"Headline: {facts['headline']}\n"
        f"Changes since last scan:\n{bullets}\n"
        f"Biggest systemic issue: {facts['top_issue'] or 'none identified'}\n"
        f"Recommended next action: {facts['next_action'] or 'maintain current coverage'}\n\nParagraph:"
    )


def _digest_fallback_narrative(facts: dict) -> str:
    parts = [facts["headline"]]
    if facts["changed"]:
        parts.append(" ".join(facts["changed"]))
    if facts["top_issue"]:
        parts.append(facts["top_issue"][0].upper() + facts["top_issue"][1:])
    if facts["next_action"]:
        parts.append("Recommended: " + facts["next_action"])
    return " ".join(parts)


def _ollama_narrative(facts: dict) -> tuple[str, str] | None:
    """Local fallback narrative via the deployed Ollama backend. Returns (text, model)."""
    import time as _t
    _t0 = _t.monotonic()
    _p = _digest_prompt(facts)
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": _p, "stream": False,
                  "options": {"temperature": 0.4, "num_predict": 200}}, timeout=150)
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        _trace_ai("digest", _p, raw, _t0, ok=bool(raw and len(raw) > 40))
        return (raw, OLLAMA_MODEL) if raw and len(raw) > 40 else None
    except Exception:
        _trace_ai("digest", _p, None, _t0, ok=False)
        return None


def compliance_digest(d: dict, ai_enabled: bool = True) -> dict:
    """Executive digest from real scan data — deterministic facts + a narrative. Narrative
    preference: local Ollama → deterministic prose (no external LLM)."""
    facts = _digest_facts(d)
    narrative, ai, model = _digest_fallback_narrative(facts), False, "deterministic"
    if ai_enabled:
        res = _ollama_narrative(facts)
        if res:
            narrative, model, ai = res[0], res[1], True
    return {**facts, "narrative": narrative, "ai": ai, "model": model}


# ── HITL precision helpers (GPU-assisted hints — never decisions) ───────────────

def looks_like_logotype(image_bytes: bytes, *, scan_id: str | None = None,
                        file: str | None = None) -> bool | None:
    """Vision judgement for the images-of-text card: does this text-bearing image read as a
    LOGOTYPE / wordmark / brand badge — which WCAG 1.4.5 and 1.4.9 both treat as essential
    (exempt) — rather than content text baked into pixels? True / False, or None when vision
    is unavailable or the answer is unparseable. Strictly a HINT surfaced on the card:
    recording the logotype exception stays a human decision (ADR 0016 — the model informs,
    it never decides)."""
    if not image_bytes or not vision_is_available():
        return None
    prompt = ("Is this image a company logo, logotype, wordmark or brand badge — rather than a "
              "chart, a slide, a screenshot, a photo, or a block of document text? "
              "Answer with exactly one word: yes or no.")
    # clean=False: the default path's honesty guard rejects one-word replies as junk ALT
    # TEXT — correct there, fatal here, where one word is exactly the answer.
    out = _vision_generate(prompt, image_bytes, clean=False, scan_id=scan_id, file=file)
    if not out:
        return None
    w = out.strip().lower()
    if w.startswith("yes"):
        return True
    if w.startswith("no"):
        return False
    return None
