"""3.1.1 Language of Page — HTML.

FULL coverage, and one of the few criteria that genuinely earns it. 3.1.1 asks that the page's
default human language be *programmatically determinable*; a valid `lang` on the root element is
exactly that, and its absence is exactly the failure. There is no subset left unexamined and no
proxy involved — contrast PDF 4.1.2 (PARTIAL: sound over AcroForm fields only) and PDF 2.4.3
(HEURISTIC: /Tabs = /S stands in for a property it cannot measure).

Whether the declared language is the CORRECT one is a different question, and not this
criterion's — 3.1.1 is about determinability. Mis-declared language is a content error a human
finds, not a conformance failure this check can or should assert.

SCAN PATH NOTE: scanner._analyse_html still runs its own inline lang check on the already-parsed
tree, and this detector re-parses. That duplication is deliberate and temporary — the registry
entry declares COVERAGE today without disturbing the HTML scan path, which parses once for
~30 criteria. When the HTML package grows enough detectors to own that parse, _analyse_html
delegates to them and the inline check goes.
"""
from __future__ import annotations

from pathlib import Path

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def detect(path: Path) -> list[dict]:
    """One 3.1.1 finding when the root element declares no language. Never raises."""
    try:
        from lxml import html as lx
        root = lx.fromstring(path.read_bytes(), base_url=str(path))
    except Exception:
        return []
    # lxml returns the root element, which is <html> for a document and the fragment root for a
    # snippet — mirrors _analyse_html's own resolution so the two can never disagree.
    el = root if root.tag == "html" else (root.find(".//html") if root.find(".//html") is not None
                                          else root)
    if not (el.get("lang") or el.get(_XML_LANG) or "").strip():
        return [{
            "ruleId": "HTML_MISSING_LANG",
            "wcag": "3.1.1 Language of Page",
            "severity": "SERIOUS",
            "detail": "the root element declares no lang attribute, so assistive technology "
                      "cannot determine the page's language and may read it with the wrong voice",
        }]
    return []
