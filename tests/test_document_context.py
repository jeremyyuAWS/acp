import hashlib
import pytest

from document_context import ContextValidationError, context_for_finding, context_prompt, normalize_context, source_digest


def package(**overrides):
    value = {
        "version": 1,
        "source_sha256": "a" * 64,
        "document_summary": "An employee benefits guide.",
        "sections": [{"id": "s1", "title": "Benefits", "purpose": "Plan overview"}],
        "entities": ["employees", "enrollment"],
        "style_rules": {"tone": "formal", "terminology": ["employee"]},
        "do_not_change": ["dates", "legal wording"],
        "accessibility_context": [{"finding_id": "f-1", "location": "image-2",
                                   "meaning": "Shows enrollment timeline", "safe_fix": "Describe the timeline",
                                   "risk": "medium"}],
    }
    value.update(overrides)
    return value


def test_normalize_context_canonicalizes_whitespace_and_preserves_binding():
    result = normalize_context(package(document_summary="  An   employee guide.  "))
    assert result["document_summary"] == "An employee guide."
    assert result["source_sha256"] == "a" * 64
    assert source_digest(b"document") == hashlib.sha256(b"document").hexdigest()


def test_context_for_finding_is_small_and_excludes_other_findings():
    value = package(accessibility_context=[
        package()["accessibility_context"][0],
        {"finding_id": "f-2", "meaning": "other", "safe_fix": "other", "risk": "low"},
    ])
    selected = context_for_finding(value, "f-1")
    assert selected["finding"]["finding_id"] == "f-1"
    assert "accessibility_context" not in selected
    assert "f-2" not in context_prompt(value, "f-1")


def test_context_prompt_is_stable_json_for_downstream_models():
    prompt = context_prompt(package(), "f-1")
    assert prompt.startswith("Document context (compiled from the full source;")
    assert '"finding":{"finding_id":"f-1"' in prompt


@pytest.mark.parametrize("field", ["source_sha256", "document_summary", "sections", "entities", "style_rules", "do_not_change", "accessibility_context"])
def test_malformed_context_is_rejected(field):
    value = package(**{field: None})
    with pytest.raises(ContextValidationError):
        normalize_context(value)


def test_source_binding_mismatch_is_rejected():
    with pytest.raises(ContextValidationError, match="does not match"):
        normalize_context(package(), source_sha256="b" * 64)


def test_context_is_bounded():
    with pytest.raises(ContextValidationError, match="exceeds"):
        normalize_context(package(document_summary="x" * 2001))
    with pytest.raises(ContextValidationError, match="at most"):
        normalize_context(package(entities=[str(i) for i in range(101)]))


def test_duplicate_ids_and_unknown_finding_are_rejected():
    with pytest.raises(ContextValidationError, match="unique"):
        normalize_context(package(sections=[{"id": "s", "title": ""}, {"id": "s", "title": ""}]))
    with pytest.raises(ContextValidationError, match="not present"):
        context_for_finding(package(), "missing")
