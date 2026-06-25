"""Local-model AI layer for ACP.

Calls a locally-running Ollama instance (or any OpenAI-compatible endpoint)
to generate human-readable explanations and fix examples for WCAG findings.

Config (env vars):
  OLLAMA_BASE_URL  — default http://localhost:11434
  OLLAMA_MODEL     — default llama3.2 (3B, runs on CPU; swap for llava for vision tasks)

Fails gracefully: every public function returns None when Ollama is unreachable
so callers can show "AI explanation unavailable" without breaking the UI.
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
    """Call Ollama to explain a WCAG finding. Returns None on any error."""
    import httpx
    prompt = _prompt(rule_id, rule_name, level, filename, finding_count, severity, engine_rule_ids)
    try:
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.3, "num_predict": 120}},
            timeout=30,
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
