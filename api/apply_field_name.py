"""Write a reviewer-approved accessible name onto a Word form field (WCAG 4.1.2).

The gap this closes
-------------------
`remediate_pdf.apply_pdf_field_name` has written approved field names into a PDF's `/TU`
since PR #24. Word had no twin: `propose_forms` drafted a label for every unlabeled content
control and the approval stopped in the review queue, so the criterion stayed failing however
many names a reviewer signed off. This is that twin.

What it writes, and why that is the right element
-------------------------------------------------
A content control's Title — `<w:alias w:val="…"/>` inside `w:sdtPr` — is what Word exposes to
assistive technology as the control's accessible NAME. It is also the visible label 3.3.2 asks
for, which is why one write clears both criteria and why `docx_checks` flags them together.

It is NOT `w:tag`. That is a developer-facing identifier used for data binding and is never
announced; a check that read it (062642f) could fail a perfectly announceable document and
pass an anonymous one. Reconciled to `w:alias` in the commit that added this module.

Locator
-------
    docx:sdt:{w:id}      the control's own Word identifier — stable across edits elsewhere
    docx:sdt:#{ordinal}  fallback, document order, for a control carrying no w:id

Minted by `propose_forms.proposals_from_document_xml`; the two must agree, and
`tests/test_apply_field_name.py` asserts a proposal's locator resolves here.

Deliberate limitations, each an honest-partial (ADR 0016) rather than a guess
----------------------------------------------------------------------------
* **A locator that no longer resolves is REPORTED, never approximated.** It comes back in
  `unresolved`; the reviewer approved a name for a field this document no longer has, and
  writing it onto a neighbouring field would put the wrong name on the wrong input — worse
  than leaving it unnamed, because it reads as authoritative.
* **An existing non-empty alias is never overwritten.** That field is not a finding, so no
  proposal should carry it; if one does, the document's own author wins.
* **The ordinal fallback counts the same population the proposer counted** — input-gallery
  content controls in document order — so the two cannot drift apart on the same file.
* **Word only.** PowerPoint and Excel have no content-control equivalent; their 4.1.2 signal
  stays the ActiveX/OLE advisory, which no static write can resolve.
"""
from __future__ import annotations
import io
import re
import zipfile

_SDT = re.compile(r"<w:sdt>(.*?)</w:sdt>", re.S)
_SDT_PR = re.compile(r"<w:sdtPr>(.*?)</w:sdtPr>", re.S)
_SDT_INPUT_TYPE = re.compile(r"<w:(checkbox|date|dropDownList|comboBox|picture)\b")
_SDT_ALIAS = re.compile(r'<w:alias\s+w:val="([^"]*)"\s*/?>')
_SDT_ID = re.compile(r'<w:id\s+w:val="([^"]+)"')

_PART = "word/document.xml"


def _xesc_attr(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _locators_for(pr_xml: str, ordinal: int) -> tuple[str, ...]:
    """Every locator this control answers to — its w:id form and its ordinal form.

    Both are accepted on the way IN even though the proposer mints only one, so a value
    approved before a control gained or lost its w:id still lands on the right field.
    """
    sid_m = _SDT_ID.search(pr_xml)
    out = [f"docx:sdt:#{ordinal}"]
    if sid_m:
        out.insert(0, f"docx:sdt:{sid_m.group(1)}")
    return tuple(out)


def apply_docx_field_name(data: bytes, values: dict[str, str]) -> tuple[bytes, list[dict], list[str]]:
    """Write each locator's approved accessible name into the Word package `data`.

    values: {locator: accessible name}. Returns (new_bytes, applied, unresolved) on the same
    contract as apply_alt / apply_link_text / apply_pdf_field_name:
      applied    — [{locator, before, after}], one per control actually named.
      unresolved — locators that matched no control, or matched one that already has a name.

    When nothing resolves, the ORIGINAL bytes are returned unchanged.
    """
    values = {k: v for k, v in (values or {}).items() if k and v and str(v).strip()}
    if not values:
        return data, [], []

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}
    if _PART not in entries:
        return data, [], list(values)
    try:
        xml = entries[_PART].decode("utf-8")
    except UnicodeDecodeError:
        return data, [], list(values)

    applied: list[dict] = []
    out: list[str] = []
    last = 0
    ordinal = 0

    for m in _SDT.finditer(xml):
        inner = m.group(1)
        pr_m = _SDT_PR.search(inner)
        if not pr_m or not _SDT_INPUT_TYPE.search(pr_m.group(1)):
            continue                       # not an input gallery type — the proposer skips these too
        ordinal += 1
        pr_xml = pr_m.group(1)
        alias_m = _SDT_ALIAS.search(pr_xml)
        if alias_m and alias_m.group(1).strip():
            continue                       # already named — the author's value wins
        value = next((values[k] for k in _locators_for(pr_xml, ordinal) if k in values), None)
        if value is None:
            continue
        value = str(value).strip()
        tag = f'<w:alias w:val="{_xesc_attr(value)}"/>'
        if alias_m:                        # an empty alias — replace it rather than add a second
            new_pr = pr_xml[:alias_m.start()] + tag + pr_xml[alias_m.end():]
        else:
            # w:alias belongs at the head of w:sdtPr, before the gallery-type element.
            new_pr = tag + pr_xml
        new_inner = inner[:pr_m.start(1)] + new_pr + inner[pr_m.end(1):]
        out.append(xml[last:m.start(1)])
        out.append(new_inner)
        last = m.end(1)
        matched = next(k for k in _locators_for(pr_xml, ordinal) if k in values)
        applied.append({"locator": matched, "before": "(no accessible name)", "after": value})

    out.append(xml[last:])
    unresolved = [k for k in values if k not in {a["locator"] for a in applied}]
    if not applied:
        return data, [], unresolved

    entries[_PART] = "".join(out).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, entries[n])
    return buf.getvalue(), applied, unresolved
