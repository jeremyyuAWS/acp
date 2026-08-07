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
* **Word only.** The primitive is `w:r`/`w:t` shaped. pptx (`a:r`/`a:t`) is the same idea
  against different tag names and is the natural next port; `ext` is already threaded through
  so that lands without a signature change.
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

_LANG_CODE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

SUPPORTED_EXTS = ("docx",)


def _xesc(s: str) -> str:
    """Escape for XML element text -- an approved rewrite is free-form reviewer prose."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xesc_attr(s: str) -> str:
    return _xesc(s).replace('"', "&quot;")


def _runs_with_text(para: str) -> list[dict]:
    """Every run in `para` that carries visible text, with its offset in the paragraph's
    concatenated text. [{xml, start, end, at, to, text}] where at/to index into `para`."""
    out: list[dict] = []
    cursor = 0
    for rm in _W_RUN.finditer(para):
        tm = _W_TEXT.search(rm.group(0))
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


def _locate(xml: str, locator: str) -> tuple[str, list[dict], int, int] | None:
    """Find `locator` in the document's paragraph text.

    Returns (paragraph_xml, runs, span_start, span_end) with the span expressed as offsets
    into the paragraph's CONCATENATED run text, or None when no paragraph contains it.
    """
    needle = " ".join((locator or "").split())
    if not needle:
        return None
    pat = _flexible(needle)
    for pm in _W_PARA.finditer(xml):
        para = pm.group(0)
        runs = _runs_with_text(para)
        if not runs:
            continue
        joined = "".join(r["text"] for r in runs)
        m = pat.search(joined)
        if m:
            return para, runs, m.start(), m.end()
    return None


def _rebuild_run(run_xml: str, text: str, *, lang: str | None = None) -> str:
    """`run_xml` with its w:t replaced by `text`, optionally carrying a `w:lang`.

    Formatting is preserved by keeping the run's own w:rPr untouched apart from the language
    mark, so a split run's halves stay visually identical to the original.
    """
    tm = _W_TEXT.search(run_xml)
    if not tm:
        return run_xml
    out = run_xml[:tm.start()] + f'<w:t xml:space="preserve">{_xesc(text)}</w:t>' + run_xml[tm.end():]
    if lang is None:
        return out
    tag = f'<w:lang w:val="{_xesc_attr(lang)}"/>'
    rm = _W_RPR.search(out)
    if not rm:
        # No run properties at all -- w:rPr must be the run's FIRST child.
        return re.sub(r"(<w:r\b[^>]*>)", r"\1" + f"<w:rPr>{tag}</w:rPr>", out, count=1)
    rpr = rm.group(0)
    if rpr.endswith("/>"):                       # <w:rPr/> -- empty, expand it
        new_rpr = f"<w:rPr>{tag}</w:rPr>"
    elif _W_LANG.search(rpr):                    # already marked -- retag, never duplicate
        new_rpr = _W_LANG.sub(tag, rpr, count=1)
    else:
        # w:lang sits near the end of the rPr child order (ECMA-376 17.3.2.28), so appending
        # is schema-correct for everything the proposers can produce.
        new_rpr = rpr[: -len("</w:rPr>")] + tag + "</w:rPr>"
    return out[: rm.start()] + new_rpr + out[rm.end():]


def _splice(para: str, runs: list[dict], start: int, end: int,
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
            rebuilt.append(_rebuild_run(r["xml"], text[:lo]))
        covered = text[lo:hi]
        if replacement is not None:
            # All of the approved prose goes in the first covered run; the remaining covered
            # runs collapse to nothing, so the sentence is not duplicated across the split.
            body = replacement if not placed else ""
            placed = True
            if body:
                rebuilt.append(_rebuild_run(r["xml"], body))
        else:
            rebuilt.append(_rebuild_run(r["xml"], covered, lang=lang))
        if hi < len(text):                       # keep the part after the span, as it was
            rebuilt.append(_rebuild_run(r["xml"], text[hi:]))
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

    part = "word/document.xml"
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}
    if part not in entries:
        return data, [], list(values.keys())
    try:
        xml = entries[part].decode("utf-8")
    except UnicodeDecodeError:
        return data, [], list(values.keys())

    applied: list[dict] = []
    for locator, value in values.items():
        value = str(value).strip()
        if mode == "lang" and not _LANG_CODE.match(value):
            # A language mark is an ISO code, not prose. Anything else is a bad row, and
            # writing it would put junk in w:val where assistive tech reads a language.
            continue
        found = _locate(xml, locator)
        if not found:
            continue
        para, runs, start, end = found
        joined = "".join(r["text"] for r in runs)
        # BOTH modes act on the whole passage, not on the 60-char locator. The locator is a
        # truncated lookup key, not the unit of work: marking only its span left a French
        # sentence tagged for 60 characters and untagged (mid-word) for the rest, which is
        # wrong on its own terms and left 3.1.2 still firing, so the write never earned credit.
        end = _sentence_end(joined, start, end)
        before = joined[start:end]
        new_para = _splice(para, runs, start, end,
                           replacement=value if mode == "sensory" else None,
                           lang=value if mode == "lang" else None)
        if new_para == para:
            continue
        xml = xml.replace(para, new_para, 1)
        applied.append({"locator": locator, "before": before,
                        "after": value if mode == "sensory" else f'{before} (lang="{value}")'})

    unresolved = [k for k in values if k not in {a["locator"] for a in applied}]
    if not applied:
        return data, [], unresolved

    entries[part] = xml.encode("utf-8")
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
    """Mark approved foreign-language passages with `w:lang` (WCAG 3.1.2).

    values: {segment-prefix locator: ISO language code}. The passage's text is untouched --
    only the runs carrying it gain the language mark. A value that is not a language code is
    skipped and reported unresolved rather than written into w:val.
    """
    return _write(data, ext, values, mode="lang")
