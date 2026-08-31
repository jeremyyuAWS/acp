"""Write a reviewer-approved link text into an Office document (WCAG 2.4.4 / 2.4.9).

api/proposals.propose_link_texts drafts descriptive link text, keyed by

    locator = href      (the hyperlink's resolved destination URL)

not a part#name pair like apply_alt.py's image locator — the same vague or duplicate text
can legitimately appear on more than one run pointing at the same destination, and all of
them need the same fix. Approving those drafts used to store the text and stop there:
nothing wrote it into the document, so store.mark_file_compliant_if_reviewed correctly
refused to certify the file (proposals.py's own docstring at the time called this out as
the known gap). This module is the missing write.

Known, deliberate limitation: because the locator is the href alone, two DIFFERENT vague
texts that happen to point at the SAME destination collapse onto one {locator: value} entry
— the later approval wins. This mirrors the exact granularity proposals.propose_link_texts
already dedupes proposals at (one proposal per distinct (normalized text, href) pair sharing
a single href-keyed value store), so it is not a new risk introduced here, just an existing
one this module inherits. A rarer case in practice than the alt-text one-image-one-locator
case apply_alt.py handles.

Deliberately narrow otherwise: it rewrites the display text of every hyperlink run/cell whose
resolved href matches an approved locator, and touches nothing else — no destination change,
no reordering. A part it cannot resolve is REPORTED, never guessed at.
"""
from __future__ import annotations
import io
import re
import zipfile

import office_structure as _os


def _xesc_text(s: str) -> str:
    """Escape for XML element text content — a reviewer's link text is free-form prose."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xesc_attr(s: str) -> str:
    return _xesc_text(s).replace('"', "&quot;")


def _apply_docx(xml: str, rels: dict[str, str], values: dict[str, str]) -> tuple[str, list[dict]]:
    applied: list[dict] = []
    out, last = [], 0
    for m in re.finditer(r'(<w:hyperlink[^>]*r:id="(rId\w+)"[^>]*>)(.*?)(</w:hyperlink>)', xml, re.S):
        href = rels.get(m.group(2))
        if not href or href not in values:
            continue
        inner = m.group(3)
        before = "".join(_os._WT.findall(inner))
        after = values[href]
        rpr_m = re.search(r"<w:rPr\b[^>]*/>|<w:rPr\b[^>]*>.*?</w:rPr>", inner, re.S)
        rpr = rpr_m.group(0) if rpr_m else ""
        new_inner = f'<w:r>{rpr}<w:t xml:space="preserve">{_xesc_text(after)}</w:t></w:r>'
        out.append(xml[last:m.start()])
        out.append(m.group(1) + new_inner + m.group(4))
        last = m.end()
        applied.append({"locator": href, "before": before or "(empty link text)", "after": after})
    out.append(xml[last:])
    return "".join(out), applied


def _apply_pptx(xml: str, rels: dict[str, str], values: dict[str, str]) -> tuple[str, list[dict]]:
    applied: list[dict] = []
    out, last = [], 0
    for m in re.finditer(r"(<a:r>)(.*?)(</a:r>)", xml, re.S):
        inner = m.group(2)
        hm = _os._A_HLINK.search(inner)
        if not hm:
            continue
        href = rels.get(hm.group(1))
        if not href or href not in values:
            continue
        before = "".join(_os._AT.findall(inner))
        after = values[href]
        rpr_m = re.search(r"<a:rPr\b[^>]*/>|<a:rPr\b[^>]*>.*?</a:rPr>", inner, re.S)
        rpr = rpr_m.group(0) if rpr_m else ""
        new_inner = f'{rpr}<a:t>{_xesc_text(after)}</a:t>'
        out.append(xml[last:m.start()])
        out.append(m.group(1) + new_inner + m.group(3))
        last = m.end()
        applied.append({"locator": href, "before": before or "(empty link text)", "after": after})
    out.append(xml[last:])
    return "".join(out), applied


# A single <c> element, self-closing or not. Mirrors office_structure._xlsx_cell_text_values'
# parse so the writer edits exactly the cell the detector read.
_C_ELEM = re.compile(r'<c\b[^>]*?(?:/>|>.*?</c>)', re.S)
_C_ATTRS = re.compile(r'<c\b([^>]*?)/?>')
_C_REF = re.compile(r'\br="([^"]+)"')
_C_TYPE = re.compile(r'\bt="([^"]*)"')
_SI_COUNT = re.compile(r'\buniqueCount="(\d+)"')


def _rewrite_cell_value(xml: str, ref: str, after: str,
                        shared: "_SharedStrings") -> tuple[str, str | None, str | None]:
    """Rewrite the visible value of the cell at `ref` to `after`.

    Returns (new_xml, before_text, refusal).

    THREE OUTCOMES, and the caller needs all three kept apart:
      * rewritten           — before_text is the old label, refusal is None.
      * no cell at `ref`    — before_text and refusal are BOTH None. Not an error: a hyperlink
                              carrying an explicit display= needs no cell, and the hand-authored
                              packages in tests/test_apply_link_text.py are exactly that shape.
      * cell present but unwritable — refusal explains why, and new_xml is unchanged.

    Collapsing the middle case into the third is a regression this function already caused once:
    every display=-carrying link in a sheet with no <sheetData> stopped being written at all.

    WHY THE CELL AND NOT JUST display=. In a worksheet, `<hyperlink display="…">` is a cached
    label; what a person reads in the grid is the VALUE of the cell at `ref`. Rewriting only the
    attribute left the spreadsheet showing "click here" while ACP's re-scan — which resolves the
    cell value — was told the criterion had cleared. The write has to move the text a reader
    actually sees.

    THE SHARED-STRING TRAP, which is why this appends rather than edits. A t="s" cell holds an
    INDEX into xl/sharedStrings.xml, and any number of unrelated cells may hold the same index —
    that is the entire point of the table. Editing the <si> in place would silently rewrite every
    other cell sharing that string, anywhere in the workbook. So a new <si> is appended and only
    this cell is repointed at it; the original entry is left exactly as it was for whoever else
    is using it.
    """
    for m in _C_ELEM.finditer(xml):
        cell = m.group(0)
        attrs_m = _C_ATTRS.match(cell)
        if not attrs_m:
            continue
        attrs = attrs_m.group(1)
        ref_m = _C_REF.search(attrs)
        if not ref_m or ref_m.group(1).split(":")[0] != ref:
            continue

        # A formula cell's displayed text is COMPUTED. Overwriting the cached <v> would be undone
        # the moment Excel recalculates, and replacing <f> would destroy the formula — neither is
        # a fix, and guessing is worse than reporting. Refused, never written.
        if "<f" in cell:
            return xml, None, (f"cell {ref} holds a formula — its label is computed, so it "
                               f"cannot be rewritten as literal text")

        t_m = _C_TYPE.search(attrs)
        t = t_m.group(1) if t_m else ""

        if t == "s":
            v_m = re.search(r"<v>([^<]*)</v>", cell)
            if not v_m:
                return xml, None, f"cell {ref} is typed as a shared string but carries no index"
            try:
                before = shared.table[int(v_m.group(1))]
            except (ValueError, IndexError):
                return xml, None, f"cell {ref} points at a shared string that is not in the table"
            new_cell = cell[:v_m.start()] + f"<v>{shared.append_text(after)}</v>" + cell[v_m.end():]

        elif t == "inlineStr":
            # No aliasing here — the text belongs to this cell alone, so it is edited in place.
            is_m = re.search(r"(<is>\s*<t[^>]*>)([^<]*)(</t>)", cell)
            if not is_m:
                return xml, None, f"cell {ref} is an inline string with no text run"
            before = is_m.group(2)
            new_cell = (cell[:is_m.start(2)] + _xesc_text(after) + cell[is_m.end(2):])

        elif t == "":
            # A number. The detector never reads one as a link label (it skips numeric cells), so
            # arriving here means the approval does not match the document — and turning a number
            # into text would change the sheet's DATA, not its labelling.
            return xml, None, (f"cell {ref} holds a number, not text — rewriting it would change "
                               f"the data rather than the label")
        else:
            return xml, None, f"cell {ref} has an unsupported cell type t={t!r}"

        return xml[:m.start()] + new_cell + xml[m.end():], before, None

    return xml, None, None          # no cell at `ref` — see the docstring's middle outcome


class _SharedStrings:
    """The workbook's shared-string table plus whatever this apply appends to it.

    Kept as one object because the index a new entry gets depends on every addition made so far
    across all worksheets in the same apply — computing it per-sheet would hand two cells the
    same index and make the second overwrite the first's label.
    """

    def __init__(self, table: list[str]):
        self.table = table
        self.additions: list[str] = []

    def append_text(self, text: str) -> int:
        """Append `text` as a new <si> and return the index cells should point at."""
        self.additions.append(text)
        return len(self.table) + len(self.additions) - 1

    def serialise(self, original_xml: str) -> str:
        """The new sharedStrings.xml. `uniqueCount` grows by the number of entries added; `count`
        (total string-cell references in the workbook) is deliberately untouched, because
        repointing a cell moves a reference rather than creating one."""
        if not self.additions:
            return original_xml
        added = "".join(f"<si><t>{_xesc_text(t)}</t></si>" for t in self.additions)
        out = original_xml
        m = _SI_COUNT.search(out)
        if m:
            new_unique = int(m.group(1)) + len(self.additions)
            out = out[:m.start()] + f'uniqueCount="{new_unique}"' + out[m.end():]
        close = out.rfind("</sst>")
        return out[:close] + added + out[close:] if close != -1 else out


def _apply_xlsx(xml: str, rels: dict[str, str], values: dict[str, str],
                shared: _SharedStrings) -> tuple[str, list[dict], list[tuple[str, str]]]:
    """Rewrite the label of every cell hyperlink whose href was approved.

    Returns (new_xml, applied, refusals). A refusal is a cell this must not rewrite (a formula,
    a number, a missing cell); it is surfaced so the reviewer learns their approval did not
    land, rather than the row being credited on a write that never happened.
    """
    applied: list[dict] = []
    refusals: list[tuple[str, str]] = []

    # PASS 1 — read every hyperlink off the ORIGINAL xml and decide what each one needs. Nothing
    # is edited yet, so no offset here can be invalidated by a later edit.
    plan: list[dict] = []
    for m in re.finditer(r"<hyperlink\b[^>]*/?>", xml):
        tag = m.group(0)
        rid_m = re.search(r'r:id="(rId\w+)"', tag)
        if not rid_m:
            continue
        href = rels.get(rid_m.group(1))
        if not href or href not in values:
            continue
        ref_m = _os._HL_REF.search(tag)
        plan.append({"href": href, "after": values[href],
                     "ref": ref_m.group(1).split(":")[0] if ref_m else None,
                     "has_display": bool(_os._HL_DISPLAY.search(tag))})

    # PASS 2 — rewrite the cells. Each call re-finds its cell by `ref`, so edits made by earlier
    # iterations cannot shift a later one onto the wrong bytes.
    cell_before: dict[str, str] = {}
    blocked: set[str] = set()
    for p in plan:
        if not p["ref"]:
            continue
        xml, before, refusal = _rewrite_cell_value(xml, p["ref"], p["after"], shared)
        if refusal:
            # The cell is there and cannot carry the label. Writing `display` alone here would
            # recreate the exact divergence this change exists to end — ACP reading the cached
            # attribute as fixed while the reader still sees the old computed text — so the link
            # is left entirely alone and the reviewer is told why.
            refusals.append((p["href"], refusal))
            blocked.add(p["href"])
        elif before is not None:
            cell_before[p["href"]] = before
        elif not p["has_display"]:
            # No cell AND no display attribute: there is nowhere a label could live, so there is
            # nothing this approval can change. Reported rather than silently counted as applied.
            refusals.append((p["href"], f"no cell at {p['ref']} and no display attribute — "
                                        f"the link has no label to rewrite"))
            blocked.add(p["href"])

    # PASS 3 — the hyperlink tags themselves, over the now-current xml.
    out, last = [], 0
    for m in re.finditer(r"<hyperlink\b[^>]*/?>", xml):
        tag = m.group(0)
        rid_m = re.search(r'r:id="(rId\w+)"', tag)
        if not rid_m:
            continue
        href = rels.get(rid_m.group(1))
        if not href or href not in values or href in blocked:
            continue
        after = values[href]
        disp_m = _os._HL_DISPLAY.search(tag)
        before = cell_before.get(href, disp_m.group(1) if disp_m else "")
        if disp_m:
            # Keep the cached attribute in step with the cell, so the two cannot disagree.
            new_tag = tag[:disp_m.start()] + f'display="{_xesc_attr(after)}"' + tag[disp_m.end():]
        elif href in cell_before:
            # Authored without the attribute — the cell IS the label, and it has just been
            # rewritten. Adding a display attribute now would create a second copy of the text
            # that can drift from the cell, so the tag stays as its author wrote it.
            new_tag = tag
        else:
            new_tag = (tag[:-2] + f' display="{_xesc_attr(after)}"/>' if tag.endswith("/>")
                       else tag[:-1] + f' display="{_xesc_attr(after)}">')
        out.append(xml[last:m.start()])
        out.append(new_tag)
        last = m.end()
        applied.append({"locator": href, "before": before or "(empty link text)", "after": after})
    out.append(xml[last:])
    return "".join(out), applied, refusals


def apply_link_text(data: bytes, ext: str, values: dict[str, str]) -> tuple[bytes, list[dict], list[str]]:
    """Write each locator's (href's) approved link text into the Office package `data`.

    values: {href: link text}. Returns (new_bytes, applied, unresolved):
      applied    — [{locator, before, after}], one per hyperlink run/cell actually rewritten,
                   ready for store.record_remediation_diffs.
      unresolved — hrefs that matched no hyperlink anywhere in the document. The caller must
                   surface these rather than treating the approval as honoured.

    When nothing resolves, the ORIGINAL bytes are returned unchanged.
    """
    ext = (ext or "").lower().lstrip(".")
    values = {k: v for k, v in (values or {}).items() if k and v and v.strip()}
    if not values or ext not in ("docx", "pptx", "xlsx"):
        return data, [], list(values.keys()) if ext not in ("docx", "pptx", "xlsx") else []

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}

    applied: list[dict] = []
    touched: dict[str, bytes] = {}
    remaining = dict(values)
    # Approvals a writer deliberately DECLINED to honour, with the reason — a formula cell, a
    # numeric cell, a missing cell. Distinct from "no hyperlink matched this href": the link is
    # right there and the label cannot be moved, which is something a reviewer needs told.
    refused: list[str] = []

    if ext == "docx":
        part = "word/document.xml"
        if part in entries:
            try:
                xml = entries[part].decode("utf-8")
                rels = _os._relationships(zipfile.ZipFile(io.BytesIO(data)), "word/_rels/document.xml.rels")
                new_xml, part_applied = _apply_docx(xml, rels, remaining)
                if part_applied:
                    touched[part] = new_xml.encode("utf-8")
                    applied.extend(part_applied)
            except UnicodeDecodeError:
                pass
    elif ext == "pptx":
        for slide_name in sorted(n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
            num = re.search(r"slide(\d+)\.xml", slide_name).group(1)
            try:
                xml = entries[slide_name].decode("utf-8")
            except UnicodeDecodeError:
                continue
            rels = _os._relationships(zipfile.ZipFile(io.BytesIO(data)), f"ppt/slides/_rels/slide{num}.xml.rels")
            new_xml, part_applied = _apply_pptx(xml, rels, remaining)
            if part_applied:
                touched[slide_name] = new_xml.encode("utf-8")
                applied.extend(part_applied)
    elif ext == "xlsx":
        # One shared-string table for the whole workbook, threaded through every sheet: the index
        # a new entry receives depends on the additions made for earlier sheets, so a per-sheet
        # table would hand two cells the same index and the second would overwrite the first.
        ss_part = "xl/sharedStrings.xml"
        ss_xml = ""
        if ss_part in entries:
            try:
                ss_xml = entries[ss_part].decode("utf-8")
            except UnicodeDecodeError:
                ss_xml = ""
        shared = _SharedStrings(_os._xlsx_shared_strings(ss_xml) if ss_xml else [])
        for ws_name in sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
            num = re.search(r"sheet(\d+)\.xml", ws_name).group(1)
            try:
                xml = entries[ws_name].decode("utf-8")
            except UnicodeDecodeError:
                continue
            rels = _os._relationships(zipfile.ZipFile(io.BytesIO(data)), f"xl/worksheets/_rels/sheet{num}.xml.rels")
            new_xml, part_applied, part_refused = _apply_xlsx(xml, rels, remaining, shared)
            refused.extend(part_refused)
            if part_applied:
                touched[ws_name] = new_xml.encode("utf-8")
                applied.extend(part_applied)
        if shared.additions and ss_xml:
            touched[ss_part] = shared.serialise(ss_xml).encode("utf-8")

    landed = {a["locator"] for a in applied}
    # (href, reason) pairs, never a pre-joined "href: reason" string — an href contains colons
    # of its own ("https:"), so splitting one back apart finds the wrong one.
    reasons = dict(refused)
    unresolved = [f"{href} — {reasons[href]}" if href in reasons else href
                  for href in values if href not in landed]

    if not applied:
        return data, [], unresolved

    entries.update(touched)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, entries[n])
    return buf.getvalue(), applied, unresolved
