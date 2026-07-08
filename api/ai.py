"""Local-model AI layer for ACP.

Calls a locally-running Ollama instance (its native /api HTTP endpoint) to
generate human-readable explanations and fix examples for WCAG findings. No
commercial-LLM SDK or API key is used anywhere — the only backend is the local
Ollama model; the layer degrades to deterministic prose when it is unreachable.

Config (env vars):
  OLLAMA_BASE_URL  — default http://localhost:11434
  OLLAMA_MODEL     — default llama3.2 (3B, runs on CPU; swap for llava for vision tasks)

Fails gracefully: every public function returns None (deterministic prose for the
digest) when Ollama is unreachable — callers never break and never need a key.
"""
from __future__ import annotations
import os

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "llama3.2")

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
        return {**_parse(raw), "model": OLLAMA_MODEL, "raw": raw}
    except Exception:
        return None


def is_available() -> bool:
    """Quick ping to check if Ollama is reachable."""
    import httpx
    try:
        httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


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
}


def _suggest_prompt(rule_id: str, rule_name: str, filename: str, detail: str) -> str:
    kind, want = _SUGGEST_KIND.get(rule_id, ("fix", "a concrete corrected value"))
    ctx = f"\nFinding detail: {detail}" if detail else ""
    vision_note = ""
    if rule_id == "1.1.1":
        vision_note = ("\nYou cannot see the image. Produce a SHORT fill-in-the-blank template the author "
                       "completes, e.g. 'Describe: [what the image shows and why it matters here]'.")
    return (
        f"You are an accessibility remediation assistant. A WCAG {rule_id} ({rule_name}) issue was found "
        f"in the document '{filename}'.{ctx}\n"
        f"Draft {want}.{vision_note}\n"
        f"Reply with ONLY the suggested {kind} — no preamble, no quotes, under 20 words."
    )


def suggest_fix(rule_id: str, rule_name: str, level: str, filename: str,
                detail: str = "") -> dict | None:
    """Draft a concrete, human-approvable fix value (alt text / link text / title) for a
    semantic finding via the local text model. Returns None when Ollama is unavailable."""
    prompt = _suggest_prompt(rule_id, rule_name, filename, detail)
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.4, "num_predict": 60}},
            timeout=90,
        )
        r.raise_for_status()
        text = r.json().get("response", "").strip().strip('"').strip()
        if not text:
            return None
        kind = _SUGGEST_KIND.get(rule_id, ("fix", ""))[0]
        return {"suggestion": text, "kind": kind,
                "is_template": rule_id == "1.1.1", "model": OLLAMA_MODEL}
    except Exception:
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
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": _digest_prompt(facts), "stream": False,
                  "options": {"temperature": 0.4, "num_predict": 200}}, timeout=150)
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        return (raw, OLLAMA_MODEL) if raw and len(raw) > 40 else None
    except Exception:
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
