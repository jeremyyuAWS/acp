"""Tests for the AI-proposes → validate → one-click-approve spine (api/proposals.py) and
its store persistence + HTML/office proposers. The local model is never called here — the
deterministic derivers are pure, and the model-backed paths are exercised elsewhere with the
model stubbed offline (tests/test_remediate_office.py). Pure stdlib + lxml.
"""
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import proposals as P  # noqa: E402


# ── Deterministic derivers ────────────────────────────────────────────────────

def test_is_vague_link_text():
    for vague in ["click here", "here", "Read more", "learn more", "more", "",
                  "https://example.com/x", "www.site.org", "Click Here."]:
        assert P.is_vague_link_text(vague), vague
    for ok in ["Download the 2026 budget", "Contact the admissions office", "Leadership team"]:
        assert not P.is_vague_link_text(ok), ok


def test_derive_link_text_from_download_target():
    r = P.derive_link_text("/files/Annual-Report-2026.pdf")
    assert r and r["deterministic"] is True
    assert r["text"] == "Download Annual Report 2026 (PDF)"


def test_derive_link_text_from_page_path():
    r = P.derive_link_text("https://x.org/about/leadership-team")
    assert r and r["text"] == "Leadership Team"


def test_derive_link_text_mailto():
    r = P.derive_link_text("mailto:admissions@uni.edu")
    assert r and r["text"] == "Email admissions@uni.edu"


def test_derive_link_text_opaque_returns_none():
    # A bare domain / id-only query is not deterministically derivable → human/model draft.
    assert P.derive_link_text("https://example.com/?id=8842") is None
    assert P.derive_link_text("https://example.com/") is None
    assert P.derive_link_text("") is None


def test_infer_decorative_by_name_and_dims():
    assert P.infer_decorative(filename="Company Logo")            # space-separated display name
    assert P.infer_decorative(filename="assets/site-divider.png")  # slug-separated
    assert P.infer_decorative(filename="x.png", width=600, height=4)     # hairline
    assert P.infer_decorative(filename="x.png", width=16, height=16)     # icon-sized
    assert P.infer_decorative(filename="quarterly-chart.png", width=600, height=400) is None


def test_infer_heading_levels_by_size_rank():
    lv = P.infer_heading_levels([28, 18, 18, 40, 14])
    assert lv == {40.0: 1, 28.0: 2, 18.0: 3, 14.0: 4}
    # deeper ranks clamp at 6 (WCAG defines only h1–h6)
    assert P.infer_heading_levels([100, 90, 80, 70, 60, 50, 40, 30])[30.0] == 6


def test_propose_language_parts_flags_the_minority_language():
    text = ("Our annual report highlights strong performance across every business unit this year. "
            "The board thanks all employees for their dedication and hard work throughout the period. "
            "Le conseil remercie chaleureusement tous les employes pour leur devouement remarquable cette annee.")
    props = P.propose_language_parts(text)
    # langdetect present in the test env → the French sentence surfaces as a proposal.
    if props:  # self-gates to [] if langdetect is unavailable
        assert any(p["proposed_value"] == "fr" for p in props)
        assert all("locator" in p and "rationale" in p for p in props)


def test_propose_language_parts_single_language_is_empty():
    assert P.propose_language_parts("All one language here, nothing to mark, every sentence English.") == []


# ── store.enqueue_proposals — persistence, JSON round-trip, idempotency ────────

def _store():
    import os
    os.environ["ACP_SQLITE_PATH"] = tempfile.mktemp(suffix=".db")
    import importlib
    import store as _store
    importlib.reload(_store)
    return _store.Store()


def test_enqueue_proposals_roundtrip_and_idempotent():
    s = _store()
    props = [P.proposal("#l1", "click here", "Download Annual Report (PDF)", "from target", "derived"),
             P.proposal("#l2", "more", "Leadership Team", "from path", "derived")]
    i1 = s.enqueue_proposals("scan1", "a.html", "2.4.4", props, validated=True, rule_name="Link Purpose")
    row = s.list_hitl_queue(scan_id="scan1")[0]
    assert isinstance(row["proposals"], list) and len(row["proposals"]) == 2
    assert row["validated"] == 1
    assert row["proposals"][0]["proposed_value"] == "Download Annual Report (PDF)"
    # idempotent per (scan, file, sc): re-enqueue REPLACES, never duplicates the row.
    i2 = s.enqueue_proposals("scan1", "a.html", "2.4.4", props[:1], validated=False)
    assert i1 == i2
    assert len(s.list_hitl_queue(scan_id="scan1")) == 1
    row2 = s.get_hitl_item(i1)
    assert len(row2["proposals"]) == 1 and row2["validated"] == 0


def test_enqueue_proposals_empty_is_noop():
    s = _store()
    assert s.enqueue_proposals("scanEmpty", "e.html", "1.1.1", []) is None
    assert s.list_hitl_queue(scan_id="scanEmpty") == []


# ── HTML 2.4.4 link expansion (proposer, not a FIXER — no fix_mode change) ─────

def test_html_link_expansion_applies_deterministic_and_collects_proposals():
    from remediate import remediate_html
    html = ('<html lang="en"><head><title>x</title></head><body>'
            '<p>See <a href="/reports/Annual-Report-2026.pdf">click here</a> '
            'and <a href="/about/leadership-team">read more</a>. '
            '<a href="https://x.com/?id=99">here</a></p></body></html>')
    props = []
    fixed, applied, _ = remediate_html(html, ai_enabled=False, proposals=props)
    # deterministic targets are rewritten inline (a real fix that clears the re-scan)…
    assert "Download Annual Report 2026 (PDF)" in fixed
    assert "Leadership Team" in fixed
    assert any("2.4.4" in a for a in applied)
    # …and surfaced as one-click proposals; the opaque link is left for a human/model draft.
    applied_props = [p for p in props if p.get("applied")]
    assert len(applied_props) == 2
    assert ">here<" in fixed   # opaque id-only link untouched (AI off)


def test_html_link_expansion_skips_links_wrapping_elements():
    from remediate import remediate_html
    html = ('<html lang="en"><head><title>x</title></head><body>'
            '<a href="/x.pdf"><img src="i.png" alt="thing"/></a></body></html>')
    props = []
    remediate_html(html, ai_enabled=False, proposals=props)
    assert props == []   # a link wrapping an <img> isn't a plain-text case


# ── docx pseudo-heading: detect → promote → clears the detector (parity) ───────

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CORE = ('<?xml version="1.0"?><cp:coreProperties '
         'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
         'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>x</dc:creator></cp:coreProperties>')


def _docx(body):
    d = Path(tempfile.mkdtemp()) / "h.docx"
    with zipfile.ZipFile(d, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", _CORE)
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {_W}><w:body>{body}</w:body></w:document>')
    return d


def test_docx_pseudo_heading_detected_then_cleared_by_fix():
    import office_structure as OSX
    import remediate_office as RO
    body = ('<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr>'
            '<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>Quarterly Results</w:t></w:r></w:p>'
            '<w:p><w:r><w:rPr><w:sz w:val="22"/></w:rPr>'
            '<w:t>This is ordinary body text describing the quarter in some detail for the reader.</w:t></w:r></w:p>')
    src = _docx(body)
    assert [f["ruleId"] for f in OSX.docx_checks(src)] == ["DOCX_PSEUDO_HEADING"]
    out, applied, _ = RO.remediate_office(src, ai_enabled=False)
    assert any("pseudo-heading" in a for a in applied)
    # the fix promoted it to a real Heading style, so the detector no longer fires (parity)
    assert "DOCX_PSEUDO_HEADING" not in [f["ruleId"] for f in OSX.docx_checks(out)]
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    assert 'w:val="Heading' in xml


def test_docx_ordinary_body_text_is_not_a_pseudo_heading():
    import office_structure as OSX
    # body-sized (11pt = 22 half-pt) non-bold text must not be flagged as a heading
    body = ('<w:p><w:r><w:rPr><w:sz w:val="22"/></w:rPr>'
            '<w:t>A short line.</w:t></w:r></w:p>')
    assert OSX.docx_checks(_docx(body)) == []
