"""Bounded, model-neutral document context for remediation suggestions.

A stronger model can read a document once and persist a small context package for
cheaper, task-specific generators.  This module only validates and projects that
package; it never calls a provider and never treats the package as approval or
conformance evidence.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

CONTEXT_VERSION = 1
MAX_SUMMARY = 2_000
MAX_SECTIONS = 100
MAX_ENTITIES = 100
MAX_TERMS = 40
MAX_PROTECTED = 40
MAX_FINDING_CONTEXT = 100
MAX_FIELD = 500
MAX_ID = 256
_RISK = frozenset({"low", "medium", "high", "unknown"})
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ContextValidationError(ValueError):
    """Raised when a model-produced context package is not bounded or usable."""


def _text(value: Any, *, field: str, limit: int = MAX_FIELD, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ContextValidationError(f"{field} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise ContextValidationError(f"{field} is required")
    if len(value) > limit:
        raise ContextValidationError(f"{field} exceeds {limit} characters")
    return value


def _list(value: Any, *, field: str, limit: int, item_limit: int = MAX_FIELD) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ContextValidationError(f"{field} must be a list of at most {limit} items")
    result = [_text(item, field=f"{field}[{i}]", limit=item_limit) for i, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise ContextValidationError(f"{field} must not contain duplicates")
    return result


def _finding(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ContextValidationError(f"accessibility_context[{index}] must be an object")
    finding_id = _text(item.get("finding_id"), field=f"accessibility_context[{index}].finding_id", limit=MAX_ID)
    location = _text(item.get("location", ""), field=f"accessibility_context[{index}].location", limit=MAX_FIELD, required=False)
    meaning = _text(item.get("meaning"), field=f"accessibility_context[{index}].meaning")
    safe_fix = _text(item.get("safe_fix"), field=f"accessibility_context[{index}].safe_fix")
    risk = item.get("risk", "unknown")
    if risk not in _RISK:
        raise ContextValidationError(f"accessibility_context[{index}].risk is invalid")
    return {"finding_id": finding_id, "location": location, "meaning": meaning,
            "safe_fix": safe_fix, "risk": risk}


def normalize_context(value: Any, *, source_sha256: str | None = None) -> dict[str, Any]:
    """Validate and canonicalize a context package produced by a context reader.

    ``source_sha256`` can be supplied by the server when the package is attached
    to an assessed source.  A caller supplied hash must match the package; this
    prevents context being silently reused for a different document.
    """
    if not isinstance(value, dict) or value.get("version") != CONTEXT_VERSION:
        raise ContextValidationError("document context version 1 is required")
    digest = value.get("source_sha256")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise ContextValidationError("document context requires a lowercase source_sha256")
    if source_sha256 is not None and digest != source_sha256:
        raise ContextValidationError("document context source does not match the assessed source")

    sections_value = value.get("sections", [])
    if not isinstance(sections_value, list) or len(sections_value) > MAX_SECTIONS:
        raise ContextValidationError(f"sections must be a list of at most {MAX_SECTIONS} items")
    sections: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(sections_value):
        if not isinstance(item, dict):
            raise ContextValidationError(f"sections[{i}] must be an object")
        section_id = _text(item.get("id"), field=f"sections[{i}].id", limit=MAX_ID)
        if section_id in seen_ids:
            raise ContextValidationError("section ids must be unique")
        seen_ids.add(section_id)
        sections.append({"id": section_id,
                         "title": _text(item.get("title", ""), field=f"sections[{i}].title", required=False),
                         "purpose": _text(item.get("purpose", ""), field=f"sections[{i}].purpose", required=False)})

    findings_value = value.get("accessibility_context", [])
    if not isinstance(findings_value, list) or len(findings_value) > MAX_FINDING_CONTEXT:
        raise ContextValidationError(
            f"accessibility_context must be a list of at most {MAX_FINDING_CONTEXT} items")
    findings = [_finding(item, i) for i, item in enumerate(findings_value)]
    finding_ids = [item["finding_id"] for item in findings]
    if len(set(finding_ids)) != len(finding_ids):
        raise ContextValidationError("accessibility_context finding ids must be unique")

    style_value = value.get("style_rules", {})
    if not isinstance(style_value, dict):
        raise ContextValidationError("style_rules must be an object")
    style: dict[str, Any] = {}
    if "tone" in style_value:
        style["tone"] = _text(style_value["tone"], field="style_rules.tone", limit=MAX_FIELD)
    if "terminology" in style_value:
        style["terminology"] = _list(style_value["terminology"], field="style_rules.terminology", limit=MAX_TERMS, item_limit=MAX_ID)

    return {
        "version": CONTEXT_VERSION,
        "source_sha256": digest,
        "document_summary": _text(value.get("document_summary", ""), field="document_summary", limit=MAX_SUMMARY, required=False),
        "sections": sections,
        "entities": _list(value.get("entities", []), field="entities", limit=MAX_ENTITIES, item_limit=MAX_ID),
        "style_rules": style,
        "do_not_change": _list(value.get("do_not_change", []), field="do_not_change", limit=MAX_PROTECTED),
        "accessibility_context": findings,
    }


def context_for_finding(context: dict[str, Any], finding_id: str) -> dict[str, Any]:
    """Return the bounded context a cheap generator needs for one finding."""
    normalized = normalize_context(context)
    finding = next((item for item in normalized["accessibility_context"]
                    if item["finding_id"] == finding_id), None)
    if finding is None:
        raise ContextValidationError("finding is not present in document context")
    return {"document_summary": normalized["document_summary"],
            "entities": normalized["entities"],
            "style_rules": normalized["style_rules"],
            "do_not_change": normalized["do_not_change"],
            "finding": finding}


def context_prompt(context: dict[str, Any], finding_id: str) -> str:
    """Render a stable, bounded instruction block for a task-specific model."""
    selected = context_for_finding(context, finding_id)
    # JSON is deliberate: it keeps metadata labels unambiguous and lets the
    # provider treat the package as constraints rather than copied prose.
    import json
    return "Document context (compiled from the full source; use as constraints only):\n" + json.dumps(
        selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_digest(data: bytes) -> str:
    """Hash the exact assessed bytes for context binding."""
    return hashlib.sha256(data).hexdigest()
