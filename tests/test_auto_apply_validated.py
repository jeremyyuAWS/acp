"""Auto-apply-validated policy (opt-in, default OFF) — the PRD's Tier-1 band extended.

An UNGROUNDED vision draft normally queues for one-click approval. With the policy on, a
draft that an INDEPENDENT second reading confirms ('consistent' consistency cross-check — a
measurement, never the model grading itself, ADR 0016) is applied inline like a grounded
one, with provenance saying exactly that. Every other verdict — divergent, validator down,
policy off — falls through to the proposal path unchanged, and the re-scan verify gate
still decides whether the criterion actually cleared.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402
import core  # noqa: E402
import remediate_office as R  # noqa: E402

_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_RELS = ('<?xml version="1.0"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId9" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
         'Target="media/image1.png"/></Relationships>')


def _photo(w=300, h=200) -> bytes:
    import io
    from PIL import Image
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (int(255 * x / w), int(255 * y / h), 128)
    buf = io.BytesIO(); im.save(buf, format="PNG"); return buf.getvalue()


def _run(monkeypatch, *, policy: bool, verdict):
    """One ungrounded draft through _fix_image_alt with the policy + validator mocked."""
    xml = (f'<?xml version="1.0"?><w:document {_W}><w:body>'
           '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 3"/>'
           '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p></w:body></w:document>')
    entries = {"word/document.xml": xml.encode(),
               "word/_rels/document.xml.rels": _RELS.encode(),
               "word/media/image1.png": _photo()}
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_image_structured",
                        lambda b, **k: {"alt": "A person at a desk", "grounded": False,
                                        "evidence": "vision only", "model": "llava"})
    monkeypatch.setattr(core.store, "get_auto_apply_validated", lambda: policy)
    calls = {"validated": 0}
    def fake_validate(img, alt, **k):
        calls["validated"] += 1
        if isinstance(verdict, Exception):
            raise verdict
        return verdict
    monkeypatch.setattr(ai, "validate_alt_text", fake_validate)
    props, applied_fixes = [], []
    applied, deferred = R._fix_image_alt(entries, vision_enabled=True, context_file="d.docx",
                                         proposals=props, applied_fixes=applied_fixes)
    return applied, props, applied_fixes, calls


def test_policy_off_never_calls_the_validator_and_queues_the_draft(monkeypatch, isolated_store):
    applied, props, fixes, calls = _run(monkeypatch, policy=False, verdict={"verdict": "consistent"})
    assert applied == [] and len(props) == 1
    assert calls["validated"] == 0                      # no silent extra model spend when off


def test_policy_on_consistent_draft_is_applied_with_honest_provenance(monkeypatch, isolated_store):
    applied, props, fixes, calls = _run(monkeypatch, policy=True, verdict={"verdict": "consistent"})
    assert len(applied) == 1 and props == []
    assert "independent second reading" in applied[0]
    assert fixes and "confirmed by an independent second reading" in fixes[0]["source"]


@pytest.mark.parametrize("verdict", [{"verdict": "divergent"}, None])
def test_policy_on_unconfirmed_draft_still_queues(monkeypatch, isolated_store, verdict):
    applied, props, fixes, calls = _run(monkeypatch, policy=True, verdict=verdict)
    assert applied == [] and len(props) == 1            # human approval, exactly as before


def test_validator_crash_falls_back_to_the_proposal(monkeypatch, isolated_store):
    applied, props, fixes, calls = _run(monkeypatch, policy=True, verdict=RuntimeError("down"))
    assert applied == [] and len(props) == 1
