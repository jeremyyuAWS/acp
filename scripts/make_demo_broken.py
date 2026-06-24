#!/usr/bin/env python3
"""
Patch a Word DOCX to introduce exactly the accessibility issues the mova.io
demo tool detects and auto-fixes:

  AUTO-FIXED (tracked changes appear in the remediated download):
    DOCX-TITLE-001  — document title blank in core.xml          (already blank)
    DOCX-TABLE-001  — 5 tables with no header row               (already broken)
    DOCX-LANG-001   — no dc:language in core.xml                (already blank)
    DOCX-ALT-001    — embedded image with no alt text           (this script adds)

  FLAGGED FOR HUMAN REVIEW (shows the tool's depth):
    DOCX-HEAD-001   — heading jump H1 → H3, H2 never used      (this script adds)
    DOCX-LINK-001   — hyperlink whose visible text is "click here" (this script adds)

Usage:
    python3 make_demo_broken.py
Outputs:
    ~/Downloads/demo-broken.docx
"""

import os, struct, zlib, zipfile, re, shutil

SRC = os.path.expanduser("~/Downloads/Movate_AI_Platform_Evaluation_Sample Word.docx")
DST = os.path.expanduser("~/Downloads/demo-broken.docx")

# ── tiny 80×50 two-tone blue PNG (no PIL required) ──────────────────────────
def _make_png(width=80, height=50):
    def chunk(tag, data):
        buf = tag + data
        return struct.pack(">I", len(data)) + buf + struct.pack(">I", zlib.crc32(buf) & 0xFFFFFFFF)

    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            raw += b"\x1b\x3a\x6b" if y < height // 2 else b"\x4a\x8f\xe0"  # dark/light navy

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )

IMG_PNG = _make_png()

# ── XML fragments ────────────────────────────────────────────────────────────

# Two heading paragraphs injected at body start: H1 then H3 (no H2 = DOCX-HEAD-001)
HEADING_PARAS = (
    '<w:p>'
    '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
    '<w:r><w:t>AI Platform Evaluation — Executive Summary</w:t></w:r>'
    '</w:p>'
    '<w:p>'
    '<w:pPr><w:pStyle w:val="Heading3"/></w:pPr>'
    '<w:r><w:t>Scoring Methodology</w:t></w:r>'
    '</w:p>'
)

# "click here" hyperlink paragraph (DOCX-LINK-001)
# rId7 = external URL relationship added below
LINK_PARA = (
    '<w:p>'
    '<w:r><w:t xml:space="preserve">For full methodology details, </w:t></w:r>'
    '<w:hyperlink r:id="rId7" w:history="1"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    '<w:t>click here</w:t></w:r>'
    '</w:hyperlink>'
    '<w:r><w:t>.</w:t></w:r>'
    '</w:p>'
)

# Inline image paragraph — wp:docPr and pic:cNvPr intentionally have NO descr= (DOCX-ALT-001)
# rId8 = image relationship added below
# cx/cy in EMUs: 80px × 9144 = 731520, 50px × 9144 = 457200
IMAGE_PARA = (
    '<w:p>'
    '<w:r>'
    '<w:drawing>'
    '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
    ' distT="0" distB="0" distL="0" distR="0">'
    '<wp:extent cx="731520" cy="457200"/>'
    '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
    '<wp:docPr id="100" name="Platform comparison chart"/>'
    '<wp:cNvGraphicFramePr>'
    '<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
    '</wp:cNvGraphicFramePr>'
    '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:nvPicPr>'
    '<pic:cNvPr id="101" name="Platform comparison chart"/>'
    '<pic:cNvPicPr><a:picLocks noChangeAspect="1" noChangeArrowheads="1"/></pic:cNvPicPr>'
    '</pic:nvPicPr>'
    '<pic:blipFill>'
    '<a:blip r:embed="rId8"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
    '<a:stretch><a:fillRect/></a:stretch>'
    '</pic:blipFill>'
    '<pic:spPr bwMode="auto">'
    '<a:xfrm><a:off x="0" y="0"/><a:ext cx="731520" cy="457200"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    '<a:noFill/>'
    '</pic:spPr>'
    '</pic:pic>'
    '</a:graphicData>'
    '</a:graphic>'
    '</wp:inline>'
    '</w:drawing>'
    '</w:r>'
    '</w:p>'
)

# New relationships to append before </Relationships>
NEW_RELS = (
    '<Relationship Id="rId7"'
    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"'
    ' Target="https://www.w3.org/WAI/WCAG21/Understanding/" TargetMode="External"/>'
    '<Relationship Id="rId8"'
    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
    ' Target="media/demo-chart.png"/>'
)

# Content-type override for PNG (append before </Types>)
PNG_CT = '<Default Extension="png" ContentType="image/png"/>'


def patch():
    # Read all files from source
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(SRC, "r") as z:
        for name in z.namelist():
            files[name] = z.read(name)

    # ── 1. document.xml — inject heading, link, image paragraphs ────────────
    doc = files["word/document.xml"].decode()
    injection = HEADING_PARAS + IMAGE_PARA + LINK_PARA
    doc = doc.replace("<w:body>", f"<w:body>{injection}", 1)
    files["word/document.xml"] = doc.encode()

    # ── 2. relationships — add hyperlink + image rels ───────────────────────
    rels = files["word/_rels/document.xml.rels"].decode()
    rels = rels.replace("</Relationships>", f"{NEW_RELS}</Relationships>")
    files["word/_rels/document.xml.rels"] = rels.encode()

    # ── 3. [Content_Types].xml — register PNG extension ─────────────────────
    ct = files["[Content_Types].xml"].decode()
    if 'Extension="png"' not in ct:
        ct = ct.replace("</Types>", f"{PNG_CT}</Types>")
    files["[Content_Types].xml"] = ct.encode()

    # ── 4. embed the PNG ─────────────────────────────────────────────────────
    files["word/media/demo-chart.png"] = IMG_PNG

    # ── 5. core.xml — ensure title + language are blank ─────────────────────
    core = files["docProps/core.xml"].decode()
    # Remove any existing dc:title / dc:language so they're truly absent
    core = re.sub(r'<dc:title>[^<]*</dc:title>', '<dc:title/>', core)
    core = re.sub(r'<dc:language>[^<]*</dc:language>', '', core)
    # If there's no dc:title at all, add an empty one
    if '<dc:title' not in core:
        core = core.replace('<cp:coreProperties', '<cp:coreProperties', 1)  # no-op
        core = re.sub(r'(<cp:coreProperties[^>]*>)', r'\1<dc:title/>', core)
    files["docProps/core.xml"] = core.encode()

    # ── write output ─────────────────────────────────────────────────────────
    with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)

    print(f"✓ Written: {DST}")
    print()
    print("Expected findings when uploaded to mova.io:")
    print("  AUTO-FIXED:")
    print("    DOCX-TITLE-001  missing document title")
    print("    DOCX-TABLE-001  5 tables missing header rows")
    print("    DOCX-LANG-001   document language not declared")
    print("    DOCX-ALT-001    1 image missing alt text  ← Claude Vision writes it live")
    print("  HUMAN REVIEW:")
    print("    DOCX-HEAD-001   heading jump H1 → H3 (H2 never used)")
    print("    DOCX-LINK-001   hyperlink text is 'click here'")


if __name__ == "__main__":
    patch()
