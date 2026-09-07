"""ADR 0055's locator translation for docx and xlsx — the one capability those formats lacked.

`apply_pptx_image_of_text.resolve_media_locators` did this for pptx (#1742). The ADR left docx
and xlsx explicitly undecided, and the reason it was right to is that the translation is the ONE
pptx-specific part of describe-instead-of-replace: everything else — the `described_not_replaced`
resolution, `store.queue_described_image_alt`, the `1.1.1/described` row, the alt lane's
`credit_rule_ids` — is already format-agnostic and already works.

So this module exists because the pptx translation DOES NOT TRANSFER, and each way it fails was
measured on a real package built by python-docx / openpyxl and run through the real detectors,
not reasoned about from the pptx code:

1. **A docx media part is placed many times behind ONE relationship id.** pptx gets away with
   `part#rId` because every slide is its OWN part with its own `.rels`, so each placement is a
   distinct (part, rId) pair. Word puts every body picture in `word/document.xml` and reuses one
   `rId` for one image, so a picture placed twice is one part, one rId, and TWO `wp:docPr`
   elements. `apply_alt.resolve_target` is first-match-wins by contract, so a `part#rId` locator
   reaches only the FIRST placement. Measured: describing both placements clears 1.1.1 on a real
   re-scan; describing via `word/document.xml#rId9` leaves 1.1.1 still failing. That is the exact
   silent-withheld-credit hole the ADR's "As built" section records finding in the pptx draft,
   arriving in docx through a door `part#rId` cannot close.

2. **xlsx relationship targets are ABSOLUTE.** openpyxl writes
   `Target="/xl/media/image1.png"`, and `posixpath.normpath(posixpath.join("xl/drawings", t))`
   returns `/xl/media/image1.png` — with a leading slash, which matches no zip namelist entry.
   The pptx canonicaliser would therefore resolve NOTHING in a workbook and silently return an
   empty map: every locator left untranslated, every described row never applied.

3. **xlsx relationship attributes are in a different ORDER.** `apply_pptx_image_of_text._REL_RE`
   requires `Id="…"` to precede `Target="…"`; openpyxl emits `Type`, `Target`, `Id`. The pattern
   simply does not match, which is failure 2 again by a second independent route. Two bugs whose
   symptom is identical silence is exactly why this was measured rather than ported.

WHAT THIS EMITS, AND WHY IT IS DERIVED FROM THE WRITER RATHER THAN MIRRORED

A locator is only useful if `apply_alt` resolves it back to the picture we meant. Rather than
re-implement that resolution and hope the two agree — the drift CLAUDE.md records this repo
losing days to — every candidate locator is CHECKED against `apply_alt.resolve_target` itself
and kept only when it resolves to the element it was minted for. A placement no fragment can
uniquely address (two pictures sharing both a name and a relationship id) is OMITTED, on the
pptx resolver's own policy: silence leaves the row unapplied and the file uncertifiable, which
is the safe direction. Guessing would write a reviewer's description onto a picture they never
saw.

ALL THREE FORMATS NOW USE THE WALK BELOW, pptx included. It began as a docx/xlsx module that
delegated pptx to the proven slides-only resolver, and that delegation is gone because the
slides-only walk had two holes the generic one does not:

  * an image referenced only by a `slideLayout` or `slideMaster` was unreachable, so a described
    decision on it wedged the file permanently and silently — ADR 0055's own first-listed
    motivating case;
  * a single slide showing the SAME picture twice shares one relationship id, so the per-rId
    locator reached only the first placement — the docx failure above, in pptx clothing.

Both dissolve by deriving the part list from `ALT_TARGETS` and each locator from
`apply_alt.resolve_target`, which is what this module already did for docx and xlsx.
`apply_pptx_image_of_text.resolve_media_locators` now delegates HERE, so there is one
implementation and its callers and tests are unchanged.

WHAT THIS LANE REACHES, AND WHAT IT DOES NOT — measured, because the boundary is invisible

REACHED: every part in `formats.office.images.ALT_TARGETS` — for Word the body plus page headers
and footers, for PowerPoint slides plus slideLayouts and slideMasters, for Excel the drawing
parts. Derived, never restated: widening that table widens the detector, this resolver and the
writer together, which is the only reason the credit gate stays meaningful.

NOT REACHED: a media part no alt-bearing part references — a footnote image, a VML sheet
header graphic, a picture inside a chart part. `ocr._ooxml_images` walks the ZIP NAMELIST and
never opens a part, so such an image still raises 1.4.5 and still gets an `image N` card.

That leaves a DEAD END, and it is stated rather than fixed here. The 1.1.1 detector reads the
same ALT_TARGETS, so an unreachable image raises no 1.1.1 finding — which means a document that
also contains a reachable image still clears 1.1.1 and is credited normally. But a document whose
ONLY carded image is unreachable wedges: the described row is approved, nothing can ever be
written for it, `count_unapplied_approved_values` counts it forever and the file can never
certify. Safe (no false certification) but with no way out for the reviewer.

THE RESIDUAL WEDGE IS NOW VISIBLE RATHER THAN SILENT. It still exists — nothing here can reach a
media part no alt-bearing part references — but `handlers._apply_one_value_kind` now logs
`apply.unverified` when a lane writes NOTHING because every locator was unresolved, so
`apply_outcome` renders a card telling the reviewer the description reached no image instead of
leaving them with a file that never publishes and no explanation. Pinned by
tests/test_remediation_described_image_office_round_trip.py::
test_an_unreachable_image_wedges_the_file_rather_than_certifying_it_falsely.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile

# The pattern that recognises the 1.4.5 proposer's locator shape, and the pptx translation.
# IMPORTED, never recompiled or reimplemented: one owner for the shape, one implementation per
# format. This import is also what keeps `apply_pptx_image_of_text`'s resolver half provably
# live — tests/test_apply_pptx_image_of_text_retired.py asserts some api/ module uses it.
from apply_pptx_image_of_text import is_media_index_locator  # noqa: F401 (re-exported)

# The alt-bearing element per part, and the writer's own resolution of a locator fragment to an
# element. Private names, imported deliberately: this module's whole job is to mint locators
# apply_alt will resolve, so deriving "which elements are there" and "what does this fragment
# resolve to" from apply_alt is the only way the two cannot disagree. A local copy of either is
# how the minter and the writer start describing different pictures.
from apply_alt import _ATTR, _R_EMBED, _alt_elements, resolve_target, tag_for_part

# The parts that can carry alt text at all, in the one shared table both the detector and the
# writer read. A media part referenced only from somewhere else (word/numbering.xml, a chart
# part) has no alt-bearing element and is correctly emitted for nothing.
from formats.office.images import ALT_TARGETS as _ALT_TARGETS

_IMAGE_LOC = re.compile(r"^image\s+(\d+)$", re.IGNORECASE)

# One Relationship element, whole. Attributes are then read by name, because ORDER IS NOT
# GUARANTEED and assuming it is is measured failure 3 above.
_REL_EL = re.compile(r"<Relationship\b[^>]*/?>", re.IGNORECASE)

# The formats this module translates for — all of them, through one walk.
SUPPORTED_EXTS = ("docx", "xlsx", "pptx")


def _media_index(zin: zipfile.ZipFile) -> list[str]:
    """The media parts in the order `ocr._ooxml_images` yields them — so 'image N' means here
    exactly what it meant to the proposer that minted it.

    Derived from ocr's OWN regex and raster tuple rather than mirrored with a comment promising
    they match. `ocr` imports nothing but the standard library at module scope (pytesseract is
    lazy), so this costs nothing, and a change to the detector's traversal becomes a change
    here instead of a silent off-by-one that describes the wrong picture.
    """
    from ocr import _MEDIA_RE, _RASTER
    return [n for n in zin.namelist()
            if _MEDIA_RE.match(n) and n.lower().endswith(_RASTER)]


def _canonical(part_dir: str, target: str) -> str | None:
    """A relationship Target resolved to the zip path it names, or None if it names none.

    Both spellings, because both are real: Word writes `media/image1.png` relative to the part's
    own directory, openpyxl writes `/xl/media/image1.png` absolute from the package root. The
    leading slash is not a path component — joining it as one produces `/xl/media/image1.png`,
    which matches nothing in a namelist and is measured failure 2 above.
    """
    t = (target or "").strip()
    if not t:
        return None
    if t.startswith("/"):
        return t.lstrip("/")
    return posixpath.normpath(posixpath.join(part_dir, t))


def _rid_map(zin: zipfile.ZipFile, part: str) -> dict[str, str]:
    """rId -> canonical zip path, for the relationships of `part`.

    External relationships are skipped: their Target is a URL, not a part, and a linked image is
    not in the package for anyone to describe.
    """
    if "/" not in part:
        return {}
    part_dir, name = part.rsplit("/", 1)
    try:
        xml = zin.read(f"{part_dir}/_rels/{name}.rels").decode("utf-8", "replace")
    except (KeyError, OSError):
        return {}
    out: dict[str, str] = {}
    for m in _REL_EL.finditer(xml):
        el = m.group(0)
        if _ATTR(el, "TargetMode").strip().lower() == "external":
            continue
        rid, target = _ATTR(el, "Id").strip(), _ATTR(el, "Target")
        canonical = _canonical(part_dir, target)
        if rid and canonical:
            out[rid] = canonical
    return out


def _alt_parts(names: list[str]) -> list[str]:
    """Every part in the package that can carry alt text, in zip-namelist order."""
    return [n for n in names if any(pat.match(n) for pat, _tag, _w, _c in _ALT_TARGETS)]


def _placements(zin: zipfile.ZipFile, wanted: set[str]) -> dict[str, list[str]]:
    """canonical media path -> every locator that addresses one placement of it.

    The walk is the writer's own: within a picture block the alt-bearing element precedes its
    `<a:blip r:embed>`, so an element owns the first blip between it and the NEXT such element —
    the same adjacency `apply_alt.resolve_target` uses to match an rId fragment, and the same one
    `remediate_office._image_bytes_for` uses to find an image's bytes.

    Each placement is then addressed by the FIRST candidate fragment that `resolve_target`
    actually resolves back to it — its `name` (which is how the 1.1.1 detector already addresses
    these pictures, and what distinguishes two placements sharing one rId), else the rId itself.
    A placement neither addresses uniquely is omitted rather than guessed at.
    """
    found: dict[str, list[str]] = {}
    for part in _alt_parts(zin.namelist()):
        tag = tag_for_part(part)
        if not tag:
            continue
        rid_map = _rid_map(zin, part)
        if not rid_map:
            continue
        try:
            xml = zin.read(part).decode("utf-8")
        except (KeyError, OSError, UnicodeDecodeError):
            continue
        els = _alt_elements(xml, tag)
        for i, m in enumerate(els):
            stop = els[i + 1].start() if i + 1 < len(els) else len(xml)
            blip = _R_EMBED.search(xml, m.end(), stop)
            if not blip:
                continue                       # a group or a shape: no image of its own
            canonical = rid_map.get(blip.group(1))
            if canonical not in wanted:
                continue
            for fragment in (_ATTR(m.group(2), "name").strip(), blip.group(1)):
                if fragment and resolve_target(xml, tag, fragment) == m.start():
                    found.setdefault(canonical, []).append(f"{part}#{fragment}")
                    break
    return found


def resolve_media_locators(data: bytes, locators, ext: str = "") -> dict[str, list[str]]:
    """{'image N': ['<part>#<fragment>', …]} — ADR 0055's translation, for every Office format.

        'image N'  ->  the Nth media part in ocr._ooxml_images order
                   ->  EVERY placement of it that an alt-bearing element addresses

    `ext` is accepted for the caller's convenience and no longer selects an implementation: the
    parts to walk come from ALT_TARGETS, which already knows which of them belong to which
    format, so a per-format branch here could only ever disagree with it.

    ONE LOCATOR, MANY PLACEMENTS, for the reason the pptx module measured and for a second one
    it could not have seen: 'image N' names the MEDIA PART, and in Word — and on a pptx slide
    showing one picture twice — every placement of that part shares a single relationship id.
    Describing one and not the others leaves
    the rest carrying their source filename, which the 1.1.1 detector reads as junk, so the
    re-scan still reports 1.1.1, the lane withholds the credit, and the reviewer's approved
    description is never marked applied. Measured on a two-placement .docx, both ways.

    A locator is OMITTED rather than mapped to anything when it cannot be resolved — malformed,
    an index past the end of the media list, a media part no alt-bearing part references, or a
    placement no fragment uniquely addresses. The caller keeps the original, apply_alt reports it
    unresolved, and the credit is withheld: an undescribed image is a finding, a wrongly
    described one is a reviewer's signature on prose about a picture they never saw.
    """
    wanted = [str(l).strip() for l in (locators or ()) if str(l or "").strip()]
    if not wanted:
        return {}

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        media_idx = _media_index(zin)
        by_media: dict[str, None] = {}
        for locator in wanted:
            m = _IMAGE_LOC.match(locator)
            if not m:
                continue
            n = int(m.group(1)) - 1
            if 0 <= n < len(media_idx):
                by_media[media_idx[n]] = None
        if not by_media:
            return {}
        placements = _placements(zin, set(by_media))

    out: dict[str, list[str]] = {}
    for locator in wanted:
        m = _IMAGE_LOC.match(locator)
        if not m:
            continue
        n = int(m.group(1)) - 1
        if not (0 <= n < len(media_idx)):
            continue
        targets = placements.get(media_idx[n])
        if targets:
            out[locator] = list(targets)
    return out


def expand_media_locator_values(data: bytes, values: dict[str, str],
                                ext: str = "") -> dict[str, str]:
    """`values` with every resolvable 'image N' key replaced by its placements' locators.

    The flat {locator: text} map the alt lane hands straight to apply_alt_text. Each placement of
    a media part gets the SAME text, because the reviewer described the image and every placement
    IS that image.

    Keys that are not media-index locators pass through untouched — an ordinary 1.1.1 row's
    'part#name' must not be disturbed — and so does a media-index locator that did not resolve,
    so it reaches apply_alt, is reported unresolved, and appears in the apply.unresolved log
    under the name the reviewer's card used rather than one they never saw.
    """
    if not values:
        return {}
    if not any(_IMAGE_LOC.match(str(k).strip()) for k in values):
        return dict(values)
    resolved = resolve_media_locators(data, list(values), ext)
    out: dict[str, str] = {}
    for locator, text in values.items():
        for target in resolved.get(str(locator).strip(), [locator]):
            out[target] = text
    return out
