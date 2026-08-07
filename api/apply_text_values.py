"""Write reviewer-approved TEXT-SPAN values into a Word document (WCAG 1.3.3 / 3.1.2).

The gap this closes
-------------------
`proposals.propose_sensory_rewrite` (1.3.3) and `proposals.propose_language_parts` (3.1.2)
both ship, both reach the review queue, and both were dead ends: approving a card stored the
value and stopped there, because `handlers._apply_approved_values` only ever routed alt text
(`apply_alt`) and link text (`apply_link_text`). The document never carried the answer, so
`store.mark_file_compliant_if_reviewed` correctly refused to certify the file and the matrix
capped both criteria at "Guided" rather than "AI Generated Fix". This module is the missing
write for both.

Why one module for two criteria
-------------------------------
They are the same problem underneath. Each proposer keys its value by a TEXT PREFIX —

    locator = sentence[:60]      (1.3.3, propose_sensory_rewrite)
    locator = segment[:60]       (3.1.2, propose_language_parts)

— not by a part#rId pair (apply_alt) or a resolved href (apply_link_text). So both writers
need the same primitive: find that prefix in the document's own text, and act on the RUNS
that carry it. `_locate` is that primitive; the two public writers are thin on top of it.

What differs is only the edit. 1.3.3 REPLACES the span's text with the approved rewrite;
3.1.2 keeps the text and marks the runs `w:lang`. Both preserve run formatting by splitting
a partially-covered run rather than swallowing it whole.

Deliberate limitations, each an honest-partial (ADR 0016) rather than a guess
----------------------------------------------------------------------------
* **A locator that no longer matches is REPORTED, never approximated.** It comes back in
  `unresolved` and the caller logs it; the reviewer approved a value for content the document
  no longer has, and writing it somewhere else would be fabrication.
* **The prefix must be unique enough to place.** When a locator matches more than one
  paragraph the FIRST is taken -- the same granularity `apply_link_text` already inherits
  from its href-keyed store (see its module docstring). A 60-character prose prefix collides
  far less often than a bare href does.
* **1.3.3 replaces to the end of the sentence**, mirroring how the proposer widened the match
  to a sentence in the first place: from the locator's start to the next "." inclusive, or the
  paragraph end. It never spills into the following sentence.
* **Whitespace is matched flexibly** (any run of spaces matches any other), because the
  proposer collapsed whitespace before truncating and the document did not. Everything else
  is matched literally.
* **Word and PowerPoint; xlsx cannot be done at all for 3.1.2.** The two Office dialects
  differ only in tag names, in where the language lives (Word a CHILD ELEMENT of `w:rPr`,
  PowerPoint an ATTRIBUTE on `a:rPr`), and in how many parts must be searched — so `_Dialect`
  parameterises those three and everything else is shared. SpreadsheetML has no per-run
  language element whatsoever, so no write can ever satisfy 3.1.2 there; that is a schema
  fact, not a backlog item.
"""
from __future__ import annotations
import io
import re
import zipfile

_W_PARA = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)
_W_RUN = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.S)
_W_TEXT = re.compile(r"(<w:t\b[^>]*>)([^<]*)(</w:t>)", re.S)
_W_RPR = re.compile(r"<w:rPr\b[^>]*/>|<w:rPr\b[^>]*>.*?</w:rPr>", re.S)
_W_LANG = re.compile(r"<w:lang\b[^>]*/>|<w:lang\b[^>]*>.*?</w:lang>", re.S)

_A_PARA = re.compile(r"<a:p\b[^>]*>.*?</a:p>", re.S)
_A_RUN = re.compile(r"<a:r\b[^>]*>.*?</a:r>", re.S)
_A_TEXT = re.compile(r"(<a:t\b[^>]*>)([^<]*)(</a:t>)", re.S)
_A_RPR = re.compile(r"<a:rPr\b[^>]*/>|<a:rPr\b[^>]*>.*?</a:rPr>", re.S)
_A_LANG_ATTR = re.compile(r'\blang="[^"]*"')

_LANG_CODE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class _Dialect:
    """The per-format shape of "a paragraph of runs of text, one of which carries a language".

    The two formats differ in three ways and nothing else that matters here: the tag names,
    where the language lives (Word a CHILD ELEMENT `<w:lang w:val>` of w:rPr, PowerPoint an
    ATTRIBUTE `lang` ON a:rPr), and how many parts have to be searched (one document vs every
    slide). Everything above — locating a prose prefix, widening it to its sentence, splitting
    a partly-covered run — is identical, so it is written once and parameterised rather than
    forked per format.
    """

    def __init__(self, *, para, run, text, rpr, text_tag, parts, set_lang):
        self.para, self.run, self.text, self.rpr = para, run, text, rpr
        self.text_tag, self.parts, self.set_lang = text_tag, parts, set_lang


def _docx_set_lang(run_xml: str, tag_lang: str) -> str:
    """Word: `<w:lang w:val="fr"/>` as a child of w:rPr, which must be the run's first child."""
    tag = f'<w:lang w:val="{_xesc_attr(tag_lang)}"/>'
    rm = _W_RPR.search(run_xml)
    if not rm:
        return re.sub(r"(<w:r\b[^>]*>)", r"\1" + f"<w:rPr>{tag}</w:rPr>", run_xml, count=1)
    rpr = rm.group(0)
    if rpr.endswith("/>"):                       # <w:rPr/> -- empty, expand it
        new_rpr = f"<w:rPr>{tag}</w:rPr>"
    elif _W_LANG.search(rpr):                    # already marked -- retag, never duplicate
        new_rpr = _W_LANG.sub(tag, rpr, count=1)
    else:
        # w:lang sits near the end of the rPr child order (ECMA-376 17.3.2.28), so appending
        # is schema-correct for everything the proposers can produce.
        new_rpr = rpr[: -len("</w:rPr>")] + tag + "</w:rPr>"
    return run_xml[: rm.start()] + new_rpr + run_xml[rm.end():]


def _pptx_set_lang(run_xml: str, tag_lang: str) -> str:
    """PowerPoint: `lang` is an ATTRIBUTE on a:rPr, and a:rPr is usually already there.

    PowerPoint writes `<a:rPr lang="en-US" dirty="0"/>` on essentially every run, so the
    common path is REPLACING an existing default rather than adding a mark — which is exactly
    why office_structure.language_marked_spans keys marks by language instead of treating any
    mark as sufficient.
    """
    attr = f'lang="{_xesc_attr(tag_lang)}"'
    rm = _A_RPR.search(run_xml)
    if not rm:
        return re.sub(r"(<a:r\b[^>]*>)", r"\1" + f"<a:rPr {attr}/>", run_xml, count=1)
    rpr = rm.group(0)
    if _A_LANG_ATTR.search(rpr):
        new_rpr = _A_LANG_ATTR.sub(attr, rpr, count=1)
    else:                                        # insert straight after the tag name
        new_rpr = re.sub(r"^<a:rPr\b", f"<a:rPr {attr}", rpr, count=1)
    return run_xml[: rm.start()] + new_rpr + run_xml[rm.end():]


def _docx_parts(names: list[str]) -> list[str]:
    return [n for n in names if n == "word/document.xml"]


def _pptx_parts(names: list[str]) -> list[str]:
    return sorted(n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))


_DIALECTS = {
    "docx": _Dialect(para=_W_PARA, run=_W_RUN, text=_W_TEXT, rpr=_W_RPR,
                     text_tag='<w:t xml:space="preserve">{}</w:t>',
                     parts=_docx_parts, set_lang=_docx_set_lang),
    "pptx": _Dialect(para=_A_PARA, run=_A_RUN, text=_A_TEXT, rpr=_A_RPR,
                     text_tag="<a:t>{}</a:t>",
                     parts=_pptx_parts, set_lang=_pptx_set_lang),
}

SUPPORTED_EXTS = tuple(_DIALECTS)


def _xesc(s: str) -> str:
    """Escape for XML element text -- an approved rewrite is free-form reviewer prose."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xesc_attr(s: str) -> str:
    return _xesc(s).replace('"', "&quot;")


def _runs_with_text(para: str, d: "_Dialect") -> list[dict]:
    """Every run in `para` that carries visible text, with its offset in the paragraph's
    concatenated text. [{xml, start, end, at, to, text}] where at/to index into `para`."""
    out: list[dict] = []
    cursor = 0
    for rm in d.run.finditer(para):
        tm = d.text.search(rm.group(0))
        if not tm:
            continue
        text = tm.group(2)
        if not text:
            continue
        out.append({"xml": rm.group(0), "at": rm.start(), "to": rm.end(),
                    "start": cursor, "end": cursor + len(text), "text": text})
        cursor += len(text)
    return out


def _flexible(needle: str) -> re.Pattern:
    """`needle` matched literally except that any whitespace run matches any other.

    The proposers collapse whitespace (`re.sub(r"\\s+", " ", ...)`) before truncating to 60
    chars; the document keeps whatever it had, including a run boundary mid-phrase. Matching
    rigidly would strand every locator whose sentence happened to span two runs.
    """
    return re.compile(r"\s+".join(re.escape(p) for p in needle.split()))


def _locate(xml: str, locator: str, d: "_Dialect") -> tuple[str, list[dict], int, int] | None:
    """Find `locator` in this part's paragraph text.

    Returns (paragraph_xml, runs, span_start, span_end) with the span expressed as offsets
    into the paragraph's CONCATENATED run text, or None when no paragraph contains it.
    """
    needle = " ".join((locator or "").split())
    if not needle:
        return None
    pat = _flexible(needle)
    for pm in d.para.finditer(xml):
        para = pm.group(0)
        runs = _runs_with_text(para, d)
        if not runs:
            continue
        joined = "".join(r["text"] for r in runs)
        m = pat.search(joined)
        if m:
            return para, runs, m.start(), m.end()
    return None


def _rebuild_run(run_xml: str, text: str, d: "_Dialect", *, lang: str | None = None) -> str:
    """`run_xml` with its text element replaced by `text`, optionally carrying a language.

    Formatting is preserved by keeping the run's own run-properties untouched apart from the
    language mark, so a split run's halves stay visually identical to the original.
    """
    tm = d.text.search(run_xml)
    if not tm:
        return run_xml
    out = run_xml[:tm.start()] + d.text_tag.format(_xesc(text)) + run_xml[tm.end():]
    return out if lang is None else d.set_lang(out, lang)


def _splice(para: str, runs: list[dict], start: int, end: int, d: "_Dialect",
            *, replacement: str | None, lang: str | None) -> str:
    """Rewrite the runs covering [start, end) of the paragraph's text.

    A run only partially covered is SPLIT so its uncovered half keeps its original text and
    formatting -- swallowing the whole run would silently rewrite text nobody approved.
    `replacement` (1.3.3) puts the new prose in the first covered run and empties the rest;
    `lang` (3.1.2) leaves the text alone and marks each covered run.
    """
    pieces: list[str] = []
    tail = 0
    placed = False
    for r in runs:
        if r["end"] <= start or r["start"] >= end:
            continue                             # untouched by the span
        lo = max(start, r["start"]) - r["start"]
        hi = min(end, r["end"]) - r["start"]
        text = r["text"]
        rebuilt: list[str] = []
        if lo > 0:                               # keep the part before the span, as it was
            rebuilt.append(_rebuild_run(r["xml"], text[:lo], d))
        covered = text[lo:hi]
        if replacement is not None:
            # All of the approved prose goes in the first covered run; the remaining covered
            # runs collapse to nothing, so the sentence is not duplicated across the split.
            body = replacement if not placed else ""
            placed = True
            if body:
                rebuilt.append(_rebuild_run(r["xml"], body, d))
        else:
            rebuilt.append(_rebuild_run(r["xml"], covered, d, lang=lang))
        if hi < len(text):                       # keep the part after the span, as it was
            rebuilt.append(_rebuild_run(r["xml"], text[hi:], d))
        pieces.append(para[tail:r["at"]])
        pieces.append("".join(rebuilt))
        tail = r["to"]
    pieces.append(para[tail:])
    return "".join(pieces)


def _sentence_end(joined: str, start: int, end: int) -> int:
    """End of the sentence/passage the located span opens.

    Both proposers work in sentence-sized units and then truncate to a 60-char locator:
    propose_sensory_rewrite widens its regex hit to the surrounding sentence, and
    propose_language_parts segments on sentence boundaries (textchecks._SEG_SPLIT). So the
    approved value applies to the SENTENCE the locator opens, never to the 60 characters that
    merely identify it. Stop at the first "." at or after the span, or the paragraph end.
    """
    dot = joined.find(".", max(end - 1, start))
    return len(joined) if dot == -1 else dot + 1


def _write(data: bytes, ext: str, values: dict[str, str], *, mode: str) -> tuple[bytes, list[dict], list[str]]:
    """Shared body for both writers. `mode` is "sensory" (replace) or "lang" (mark)."""
    ext = (ext or "").lower().lstrip(".")
    values = {k: v for k, v in (values or {}).items() if k and v and str(v).strip()}
    if not values or ext not in SUPPORTED_EXTS:
        return data, [], list(values.keys())

    d = _DIALECTS[ext]
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}

    parts: dict[str, str] = {}
    for n in d.parts(names):
        try:
            parts[n] = entries[n].decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            continue
    if not parts:
        return data, [], list(values.keys())

    applied: list[dict] = []
    for locator, value in values.items():
        value = str(value).strip()
        if mode == "lang" and not _LANG_CODE.match(value):
            # A language mark is an ISO code, not prose. Anything else is a bad row, and
            # writing it would put junk where assistive tech reads a language.
            continue
        # A pptx passage lives on ONE slide but we do not know which, so every part is
        # searched in order and the first match wins — the same "first match wins" rule the
        # single-part docx case already had, just across more parts.
        for name in parts:
            found = _locate(parts[name], locator, d)
            if not found:
                continue
            para, runs, start, end = found
            joined = "".join(r["text"] for r in runs)
            # BOTH modes act on the whole passage, not on the 60-char locator. The locator is
            # a truncated lookup key, not the unit of work: marking only its span left a
            # French sentence tagged for 60 characters and untagged (mid-word) for the rest,
            # which is wrong on its own terms and left 3.1.2 firing, so it never earned credit.
            end = _sentence_end(joined, start, end)
            before = joined[start:end]
            new_para = _splice(para, runs, start, end, d,
                               replacement=value if mode == "sensory" else None,
                               lang=value if mode == "lang" else None)
            if new_para == para:
                continue
            parts[name] = parts[name].replace(para, new_para, 1)
            applied.append({"locator": locator, "before": before,
                            "after": value if mode == "sensory" else f'{before} (lang="{value}")'})
            break

    unresolved = [k for k in values if k not in {a["locator"] for a in applied}]
    if not applied:
        return data, [], unresolved

    for name, xml in parts.items():
        entries[name] = xml.encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, entries[n])
    return buf.getvalue(), applied, unresolved


def apply_sensory_rewrite(data: bytes, ext: str, values: dict[str, str]) -> tuple[bytes, list[dict], list[str]]:
    """Write approved non-sensory rewrites into the document (WCAG 1.3.3).

    values: {sentence-prefix locator: approved rewrite}. Returns (new_bytes, applied,
    unresolved) on the same contract as apply_alt / apply_link_text -- ORIGINAL bytes back
    when nothing resolved, and every locator that matched no text reported rather than guessed.
    """
    return _write(data, ext, values, mode="sensory")


def apply_language_parts(data: bytes, ext: str, values: dict[str, str]) -> tuple[bytes, list[dict], list[str]]:
    """Mark approved foreign-language passages with the format's language mark (WCAG 3.1.2).

    values: {segment-prefix locator: ISO language code}. The passage's text is untouched --
    only the runs carrying it gain the mark (`w:lang` in Word, the `lang` attribute on a:rPr
    in PowerPoint). A value that is not a language code is skipped and reported unresolved
    rather than written where assistive tech reads a language.

    xlsx is unsupported by construction, not omission: SpreadsheetML's rich-text run
    properties have no language element at all, so there is nowhere to put the answer.
    """
    return _write(data, ext, values, mode="lang")
