"""1.4.5 / 1.4.9 Images of Text — OCR-based detection (ADR 0002 §agentic tier).

WCAG 1.4.5 (AA, Required): real text must be used rather than images of text,
except for a "Customizable" exception (the image can be visually re-styled to
the reader's needs) or an "Essential" exception (logotypes, brand names, a
screenshot where the exact presentation matters). WCAG 1.4.9 (AAA, Optional)
drops the Customizable exception — and since a static raster image embedded in
a document is never customizable to begin with, 1.4.9's real bite for documents
is that it tolerates none of the slack 1.4.5 gives small/incidental text blocks.
We model that honestly as a STRICTER threshold on the same OCR signal, not a
copy of 1.4.5 — 1.4.9 findings are a superset (every 1.4.5 hit reappears here,
plus smaller/shorter text blocks 1.4.5's higher floor lets through).

We can't tell from markup whether an image *contains* text, so this runs OCR
(tesseract) over the images actually embedded in a document and flags any that
carry a meaningful amount of text.

Scope: OOXML (docx/pptx/xlsx) and PDF, whose images are embedded and extractable
locally. HTML <img> references external files we don't fetch, so HTML isn't
covered here. The fix (re-authoring as real text) is human/AI-assisted, so a
finding is detected automatically and routed to review — never auto-passed.

Self-gating and bounded: returns [] when tesseract/pytesseract are unavailable
or ACP_DETECT_IMAGES_OF_TEXT=0, and never raises (OCR must not fail a scan).
Caps keep it cheap — small images (icons/bullets) and vector art are skipped, a
per-file image cap bounds runtime, and only images with >= a word threshold count
(so logos and one-word badges don't false-positive at the 1.4.5/AA bar).
"""
from __future__ import annotations

import io
import hashlib
import os
import re
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

# Tunables (env-overridable) — conservative defaults to avoid flagging logos.
_MIN_WORDS = int(os.environ.get("ACP_OCR_MIN_WORDS", "10"))     # >= this many real words = image of text (1.4.5/AA)
_MIN_PIXELS = int(os.environ.get("ACP_OCR_MIN_PIXELS", "20000"))  # skip icons/bullets (~140x140) (1.4.5/AA)
# 1.4.9/AAA has no Customizable exception to lean on — much lower floors, but
# still skip single-glyph/watermark noise (~35x35px, 3 words) rather than flag
# on literal pixel dust.
_MIN_WORDS_STRICT = int(os.environ.get("ACP_OCR_MIN_WORDS_STRICT", "3"))
_MIN_PIXELS_STRICT = int(os.environ.get("ACP_OCR_MIN_PIXELS_STRICT", "1200"))
_MAX_IMAGES = int(os.environ.get("ACP_OCR_MAX_IMAGES", "30"))    # per-file cap (bounds scan time)
_MAX_DIM = 3000  # downscale giant scans before OCR to keep memory/time bounded
_OCR_TIMEOUT_S = float(os.environ.get("ACP_OCR_TIMEOUT_S", "30"))
_OCR_CACHE_SIZE = int(os.environ.get("ACP_OCR_CACHE_SIZE", "128"))

_RASTER = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
_MEDIA_RE = re.compile(r"^(word|ppt|xl)/media/", re.I)
_WORD_RE = re.compile(r"[A-Za-z]{2,}")


_WARNED = False
_OCR_CACHE: OrderedDict[str, str] = OrderedDict()
_OCR_CACHE_LOCK = threading.Lock()


def _cached_text(key: str) -> str | None:
    with _OCR_CACHE_LOCK:
        text = _OCR_CACHE.get(key)
        if text is not None:
            _OCR_CACHE.move_to_end(key)
        return text


def _remember_text(key: str, text: str) -> None:
    if _OCR_CACHE_SIZE <= 0:
        return
    with _OCR_CACHE_LOCK:
        _OCR_CACHE[key] = text
        _OCR_CACHE.move_to_end(key)
        while len(_OCR_CACHE) > _OCR_CACHE_SIZE:
            _OCR_CACHE.popitem(last=False)


def is_available() -> bool:
    """True only when the OCR stack is actually usable — env-enabled, pytesseract
    importable, and the tesseract binary present.

    Says so ONCE when the binary is what is missing, because the degradation is otherwise
    invisible and does not look like a missing dependency. api/requirements.txt installs
    pytesseract, which is only a WRAPPER; the tesseract binary comes from the Dockerfile, so a
    developer who pip-installs the requirements locally has the import and not the engine.
    Nothing then errors — 1.1.1 alt text simply stops being auto-applied, because an alt is
    only written inline when it is GROUNDED in text read from the image, and with no OCR
    nothing can be. The drafts route to `proposals` for human approval instead, which is the
    correct behaviour for an ungrounded guess and indistinguishable from the model being poor.

    That cost most of a day on 2026-08-08: remediation was read as broken, then as a wiring
    bug, then as model quality, on a machine that was simply missing the binary. Installing it
    took one command and the fix count went from 8 to 9 with 1.1.1 among them.

    The env-disabled case stays silent — that one is a decision, not a misconfiguration, and
    warning about it would train people to ignore the line that matters.
    """
    if os.environ.get("ACP_DETECT_IMAGES_OF_TEXT", "1").lower() in ("0", "false", "no"):
        return False
    try:
        import pytesseract  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        global _WARNED
        if not _WARNED:
            _WARNED = True
            print("[acp] OCR unavailable — the tesseract binary was not found. Images-of-text "
                  "(1.4.5/1.4.9) will not be detected, and 1.1.1 alt text will be PROPOSED "
                  "rather than applied, because an alt is only written inline when grounded in "
                  "the image's own text. Install it: `brew install tesseract` (macOS) or "
                  "`apt-get install -y tesseract-ocr` (Debian). Set "
                  "ACP_DETECT_IMAGES_OF_TEXT=0 to disable this lane deliberately and silence "
                  "this.", flush=True)
        return False


def _ocr_words(img_bytes: bytes, min_pixels: int = _MIN_PIXELS) -> int:
    """Word count of text OCR'd from one image; 0 on any failure or if too small."""
    return len(_WORD_RE.findall(ocr_text(img_bytes, min_pixels=min_pixels)))


def ocr_text(img_bytes: bytes, *, min_pixels: int = _MIN_PIXELS_STRICT) -> str:
    """Raw text OCR'd from one image, or "" on any failure / if too small. Same bounded,
    self-gating image handling as _ocr_words (resize cap, mode coerce). Used to GROUND a
    vision alt-text proposal: a chart/screenshot with real embedded text ("2026 Sales
    Report", axis labels) yields OCR words the description can be anchored in — a High-
    confidence, auto-applyable derivation — whereas a textless photo yields "" and its
    description stays a pure vision guess surfaced for human confirmation (WCAG 1.1.1
    intent). Defaults to the STRICT pixel floor so a small labelled chart still grounds.

    Collapses read_image_text()'s "nothing was read" to "" for the callers that want a string
    they can put in a prompt. A criterion deciding whether a document CONFORMS must use
    read_image_text and tell the two apart — see there."""
    return read_image_text(img_bytes, min_pixels=min_pixels) or ""


def read_image_text(img_bytes: bytes, *, min_pixels: int = _MIN_PIXELS_STRICT) -> str | None:
    """The OCR reading of one image — or **None when no reading happened**.

    The distinction is the whole point of this function, and it is the same fail-closed contract
    the transcription lane uses: "" means tesseract ran over this image and found no text; None
    means it did not complete (timed out, raised, OCR unavailable) and NOTHING is known about
    what the image contains. An image below `min_pixels` is "" — that is a deliberate exclusion
    from the criterion (icons, bullets), not a failed reading.

    Conflating the two certifies unassessed content. On 2026-09-02 a 30s `_OCR_TIMEOUT_S`
    elapsed on a contended CI runner, "" came back, `images_of_text` counted zero words, and
    1.4.5 reported nothing at all on a document holding a full paragraph baked into a picture —
    output identical to a clean document. The 1.4.9 pass then re-read the same image
    successfully, because a failure is deliberately not cached, and flagged it. Two
    contradictory conclusions about one image, and the silent one was the Level AA one.
    """
    if not is_available():
        return None
    try:
        from PIL import Image
        import pytesseract
        im = Image.open(io.BytesIO(img_bytes))
        if (im.width * im.height) < min_pixels:
            return ""
        # The AA and AAA image-of-text checks intentionally inspect the same embedded image.
        # Cache only the small OCR string (never the document bytes) so the second criterion
        # reuses the first reading instead of starting another Tesseract process.
        cache_key = hashlib.sha256(img_bytes).hexdigest()
        cached = _cached_text(cache_key)
        if cached is not None:
            return cached
        if max(im.width, im.height) > _MAX_DIM:
            scale = _MAX_DIM / max(im.width, im.height)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        kwargs = {"timeout": _OCR_TIMEOUT_S} if _OCR_TIMEOUT_S > 0 else {}
        text = (pytesseract.image_to_string(im, **kwargs) or "").strip()
        _remember_text(cache_key, text)
        return text
    except Exception:
        # Deliberately NOT cached. A cached failure would be served to every later pass over the
        # same image, so the two images-of-text criteria would agree — on the answer nobody read.
        return None


def _ooxml_images(path: Path):
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if _MEDIA_RE.match(n) and n.lower().endswith(_RASTER):
                    try:
                        yield z.read(n)
                    except Exception:
                        continue
    except Exception:
        return


def _pdf_images(path: Path):
    try:
        import pikepdf
        with pikepdf.open(str(path)) as pdf:
            for page in pdf.pages:
                images = getattr(page, "images", {}) or {}
                for obj in images.values():
                    try:
                        pil = pikepdf.PdfImage(obj).as_pil_image()
                        buf = io.BytesIO()
                        pil.save(buf, format="PNG")
                        yield buf.getvalue()
                    except Exception:
                        continue
    except Exception:
        return


def _embedded_images_and_total(path: Path, ext: str) -> tuple[list[bytes], int]:
    """(images examined, images present). The second number is why this exists.

    The cap is right — OCR costs ~0.1s per image on a synthetic fixture and more on a real
    scanned page, so an unbounded pass over a 500-image deck is a scan nobody waits for. What was
    wrong is that exceeding it was SILENT: a 35-image document produced exactly 30 image-of-text
    findings and no indication that five images were never looked at. The output is
    indistinguishable from a document whose last five images are clean, which is the shape of
    every defect this codebase keeps rediscovering — a number that is smaller for a reason nobody
    can see.

    Counting the whole source costs nothing extra: both generators are already walked lazily and
    the remainder is only counted, never decoded or OCR'd, so the cap still bounds the expensive
    work exactly as before.
    """
    ext = ext.lower()
    if ext in (".docx", ".pptx", ".xlsx"):
        source = _ooxml_images(path)
    elif ext == ".pdf":
        source = _pdf_images(path)
    else:
        return [], 0
    out: list[bytes] = []
    total = 0
    for img in source:
        total += 1
        if len(out) < _MAX_IMAGES:
            out.append(img)
    return out, total


def _embedded_images(path: Path, ext: str) -> list[bytes]:
    """Materialize this document's embedded raster images once (bounded by
    _MAX_IMAGES) so 1.4.5 and 1.4.9 can both scan them without re-parsing the
    zip/PDF twice."""
    return _embedded_images_and_total(path, ext)[0]


# Chart/graph recognition for 1.4.5's Essential exception, from the OCR text itself. A chart's
# OCR is dominated by data values and axis ticks (numbers, $, %); a screenshot of prose is
# dominated by words. Deterministic and evidence-based (ADR 0016) — no model call, no guess.
_NUMERIC_TOKEN = re.compile(r"^[\$€£(]?\d[\d,.–%()kKmMbB]*%?\)?$")


def _looks_like_chart(text: str) -> bool:
    """True when this OCR text reads like a data visualization (chart/graph/plot) rather than a
    picture of prose. Three independent signals, each measured on the real OCR tokens:
      - numeric density ≥30% (data values dominate),
      - several currency/percent values ($3.8M, 81%…),
      - an AXIS-TICK RUN: ≥4 consecutive numeric tokens ("100 80 60 40 20" down a y-axis) — long
        category labels dilute the density on labelled charts, but prose never produces a run of
        four bare numbers in a row.
    Used ONLY for the 1.4.5 Essential exception below."""
    toks = text.split()
    if len(toks) < 4:
        return False
    is_num = [bool(_NUMERIC_TOKEN.match(t)) for t in toks]
    num = sum(is_num)
    money_pct = sum(1 for t in toks if ("$" in t or "%" in t) and any(c.isdigit() for c in t))
    run = best = 0
    for b in is_num:
        run = run + 1 if b else 0
        best = max(best, run)
    return (num / len(toks)) >= 0.3 or money_pct >= 3 or best >= 4


def images_of_text(path: Path, ext: str) -> list[dict]:
    """Return one 1.4.5 issue per embedded image that carries substantial text. Each finding
    carries the OCR'd text itself as `detail` — the reviewer sees WHICH words are baked into
    WHICH image, not a bare rule id. Empty when OCR is unavailable/disabled — callers append
    these to the file's engine findings so they flow through the rubric and per-rule traces.

    Essential exception (WCAG 1.4.5): graphs and diagrams are the W3C's own example of a
    presentation of text that IS essential — a chart cannot be re-authored as selectable text;
    its information reaches AT users through the text alternative (1.1.1, checked separately).
    So an image whose OCR reads like chart data (axis ticks, values — see _looks_like_chart) is
    NOT a 1.4.5 failure and is skipped here. 1.4.9 (AAA, "No Exception") still flags it, which
    is exactly the AA-vs-AAA distinction the two criteria encode."""
    if not is_available():
        return []
    findings: list[dict] = []
    images, total = _embedded_images_and_total(path, ext)
    unread = 0
    retry_left = 1
    for i, img in enumerate(images):
        reading = read_image_text(img, min_pixels=_MIN_PIXELS)
        if reading is None and retry_left:
            # A timeout is a statement about the machine, not about the image, and the evidence
            # says so: on the run that exposed this the 1.4.9 pass re-read the very same image
            # moments later and succeeded. So try once more.
            #
            # ONCE PER DOCUMENT, not once per image. A document whose reads keep failing is on a
            # starved machine, and spending another `_OCR_TIMEOUT_S` on each of `_MAX_IMAGES`
            # images would turn one 30s stall into fifteen minutes of a scan someone is waiting
            # on — trading a reported gap for an unusable product.
            retry_left -= 1
            reading = read_image_text(img, min_pixels=_MIN_PIXELS)
        if reading is None:
            unread += 1
            continue
        text = " ".join(reading.split())
        if len(_WORD_RE.findall(text)) >= _MIN_WORDS:
            if _looks_like_chart(text):
                continue        # Essential exception — a chart/graph, not a picture of prose
            findings.append({
                "ruleId": "OCR_IMAGE_OF_TEXT",
                "wcag": "1.4.5 Images of Text",
                "severity": "SERIOUS",
                "detail": f"embedded image {i + 1} contains readable text (OCR): “{text[:160]}”",
            })
    # SAY WHAT WE COULD NOT READ. Same advisory shape, and the same argument, as the cap notice
    # below: an image whose reading did not complete has not been assessed, and reporting
    # nothing about it is a claim of conformance drawn from a measurement that never finished.
    #
    # Emitted from the 1.4.5 pass only, for the reason spelled out under the cap notice.
    if unread:
        findings.append({
            "ruleId": "OCR_IMAGE_UNREAD",
            "wcag": "1.4.5 Images of Text",
            "severity": "REVIEW",
            "detail": (f"{unread} of this document's {len(images)} images could not be read by "
                       f"OCR — the reading did not complete, so nothing is asserted about "
                       f"whether they contain text. This is usually a timeout on a loaded "
                       f"machine; raise ACP_OCR_TIMEOUT_S (currently {_OCR_TIMEOUT_S:g}s) and "
                       f"re-scan, or review those images by hand."),
        })

    # SAY WHAT WE DID NOT LOOK AT. Advisory (REVIEW), because the honest claim is not "these
    # images fail" — nobody read them — it is "this criterion was not fully checked on this
    # document". A blocking finding would assert a defect we have no evidence for; silence
    # asserts conformance we have no evidence for either.
    #
    # Emitted from the 1.4.5 pass ONLY, not from images_of_text_no_exception as well. Both walk
    # the same capped list, so reporting from each would show the reviewer the same truncation
    # twice under two criteria — and 1.4.9 is AAA, dropped at an AA target, so putting it there
    # alone would hide the notice on exactly the scans most people run.
    #
    # Names the knob. An operator who cannot act on a limit is only being made anxious by it.
    if total > len(images):
        findings.append({
            "ruleId": "OCR_IMAGE_CAP_REACHED",
            "wcag": "1.4.5 Images of Text",
            "severity": "REVIEW",
            "detail": (f"this document holds {total} images and only the first {len(images)} "
                       f"were checked for text — {total - len(images)} were not examined. "
                       "Raise ACP_OCR_MAX_IMAGES to cover them, or review them by hand; no "
                       "conclusion about those images is asserted either way."),
        })
    return findings


def images_of_text_no_exception(path: Path, ext: str) -> list[dict]:
    """Return one 1.4.9 issue per embedded image whose OCR'd text clears the
    stricter AAA floor — genuinely more images than 1.4.5 catches, since AAA
    tolerates none of the incidental-text slack AA does. Same self-gating,
    bounds, and OCR-text evidence as images_of_text()."""
    if not is_available():
        return []
    findings: list[dict] = []
    for i, img in enumerate(_embedded_images(path, ext)):
        text = " ".join(ocr_text(img, min_pixels=_MIN_PIXELS_STRICT).split())
        if len(_WORD_RE.findall(text)) >= _MIN_WORDS_STRICT:
            findings.append({
                "ruleId": "OCR_IMAGE_OF_TEXT_STRICT",
                "wcag": "1.4.9 Images of Text (No Exception)",
                "severity": "MODERATE",
                "detail": f"embedded image {i + 1} contains readable text (OCR): “{text[:160]}”",
            })
    return findings
