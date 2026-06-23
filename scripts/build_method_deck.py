"""
Rebuild method-deck.pptx with slide images instead of table XML.
Slides 2 and 3 get PIL-rendered PNGs (1920×1080, @2× quality → 3840×2160 then downscaled).
Slide 1 (the intro/design slide) is kept from the original PPTX unchanged.

Run from /Users/css173265/projects/acp:
  python3 scripts/build_method_deck.py
"""

import io, re, zipfile, struct, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SRC = Path('/Users/css173265/Downloads/MovaiO_AccessOps_Method_Slides V4.pptx')
DEST = Path('frontend/public/exports/method-deck.pptx')

# ---------------------------------------------------------------------------
# Status lookup (same values as exportDeliverables.js)
# ---------------------------------------------------------------------------
STATUS = {
    '1.1.1':'Live · AI vision','1.2.1':'Live · Whisper','1.2.2':'Live · Whisper',
    '1.2.3':'Live · transcript','1.3.1':'Live · auto','1.3.2':'Covered · HITL',
    '1.3.3':'Live · AI','1.2.4':'Covered · HITL','1.2.5':'Covered · HITL',
    '1.4.13':'Covered · HITL','2.1.4':'Covered · HITL','2.2.1':'Covered · HITL',
    '2.2.2':'Covered · HITL','2.5.1':'Covered · HITL','2.5.2':'Covered · HITL',
    '2.5.4':'Covered · HITL','3.2.1':'Covered · HITL','3.2.2':'Covered · HITL',
    '3.3.1':'Covered · HITL','3.3.3':'Covered · HITL','3.3.4':'Covered · HITL',
    '4.1.3':'Covered · HITL','1.4.6':'Live · auto','1.4.9':'Live · AI OCR',
    '2.4.9':'Live · AI','3.1.4':'Live · auto','1.3.6':'Covered · HITL',
    '1.4.8':'Covered · HITL','2.1.3':'Covered · HITL','2.2.3':'Covered · HITL',
    '2.2.4':'Covered · HITL','2.2.5':'Covered · HITL','2.2.6':'Covered · HITL',
    '2.3.2':'Covered · HITL','2.3.3':'Covered · HITL','2.4.8':'Covered · HITL',
    '2.4.10':'Covered · HITL','2.4.11':'Covered · HITL','2.4.12':'Covered · HITL',
    '2.4.13':'Covered · HITL','2.5.5':'Covered · HITL','2.5.6':'Covered · HITL',
    '2.5.7':'Covered · HITL','3.1.3':'Covered · HITL','3.1.5':'Covered · HITL',
    '3.1.6':'Covered · HITL','3.2.5':'Covered · HITL','3.3.5':'Covered · HITL',
    '3.3.6':'Covered · HITL','3.3.7':'Covered · HITL','3.3.8':'Covered · HITL',
    '3.3.9':'Covered · HITL','1.4.1':'Live · auto','1.4.3':'Live · auto',
    '1.4.4':'Live · auto','1.4.5':'Live · AI OCR','1.4.10':'Live · auto',
    '1.4.11':'Live · auto','1.4.12':'Live · auto','2.1.1':'Live · auto',
    '2.1.2':'Live · AI + human','2.4.1':'Roadmap','2.4.2':'Live · auto',
    '2.4.4':'Live · AI','2.4.3':'Live · auto','2.4.6':'Live · auto',
    '2.4.7':'Live · auto','4.1.2':'Live · auto','3.1.1':'Live · auto',
    '3.1.2':'Live · AI','3.3.2':'Live · auto','PDF/UA':'Roadmap',
    # slide 3 codes
    '1.4.4':'Live · auto','1.4.5':'Live · AI OCR','1.4.10':'Live · auto',
    '1.4.12':'Live · auto','2.4.2':'Live · auto','2.4.3':'Live · auto',
    '2.4.4':'Live · AI','2.4.7':'Live · auto','4.1.2':'Live · auto',
    '2.1.1':'Live · auto','2.1.2':'Live · AI + human','2.4.1':'Roadmap',
    '4.1.2':'Live · auto','2.1.1':'Live · auto','2.2.4':'Covered · HITL',
    '2.2.5':'Covered · HITL','2.2.6':'Covered · HITL',
    '2.4.3':'Live · auto','3.3.2':'Live · auto',
}

def status_for(sc):
    key = sc.strip()
    if key in STATUS:
        return STATUS[key]
    m = re.match(r'\d+\.\d+\.\d+', key)
    if m: return STATUS.get(m.group(), 'Planned')
    return 'Planned'

def status_color(text):
    if text.startswith('Live'):    return (59, 109, 17)    # green
    if text.startswith('Covered'): return (31, 95, 168)    # blue
    if text.startswith('Roadmap'): return (133, 79, 11)    # amber
    return (100, 100, 100)

# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------
def xtxt(xml_frag):
    """Extract plain text from an OOXML fragment."""
    # Use \b to avoid matching <a:txBody>, <a:tcPr>, etc.
    parts = re.findall(r'<a:t\b[^>]*>([\s\S]*?)<\/a:t>', xml_frag)
    def dec(s):
        return s.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>').replace('&quot;','"').replace('&apos;',"'")
    return ''.join(dec(p) for p in parts).strip()

def parse_slide_title(xml):
    """Return the big title string from a slide's non-table shapes."""
    candidates = []
    for sp in re.finditer(r'<p:sp>[\s\S]*?<\/p:sp>', xml):
        sp_xml = sp.group()
        if '<a:tbl>' in sp_xml:
            continue
        t = xtxt(sp_xml)
        if len(t) > 15:
            candidates.append(t)
    # Title-like shapes contain '1 of' or '2 of' or 'all'
    for c in candidates:
        if 'of 2' in c or 'all' in c.lower():
            return c
    return candidates[1] if len(candidates) > 1 else ''

def parse_table_rows(xml):
    """Return list of dicts: {kind, cells: [{text, color, bold}]}"""
    rows_xml = re.findall(r'<a:tr[ >][\s\S]*?<\/a:tr>', xml)
    result = []
    for row_xml in rows_xml:
        cells_xml = re.findall(r'<a:tc[ >][\s\S]*?<\/a:tc>', row_xml)
        real_cells = [c for c in cells_xml if 'hMerge="1"' not in c]
        cell_data = []
        for c in real_cells:
            text = xtxt(c)
            colors = re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', c)
            bold = 'b="1"' in c
            cell_data.append({'text': text, 'color': colors[0] if colors else '26262E', 'bold': bold})
        is_section = 'gridSpan=' in row_xml
        result.append({'kind': 'section' if is_section else 'data', 'cells': cell_data})
    return result

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
def load_font(size, bold=False):
    candidates = [
        '/System/Library/Fonts/Helvetica.ttc',
        '/Library/Fonts/Arial.ttf',
        '/System/Library/Fonts/SFNSDisplay.ttf',
        '/System/Library/Fonts/SFNS.ttf',
    ]
    bold_candidates = [
        '/Library/Fonts/Arial Bold.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ]
    search = (bold_candidates if bold else []) + candidates
    for path in search:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def text_size(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

# ---------------------------------------------------------------------------
# Slide renderer
# ---------------------------------------------------------------------------
W, H = 1920, 1080   # final slide size
SCALE = 2           # render at 2× then downscale for anti-aliasing
RW, RH = W * SCALE, H * SCALE

PINK      = (230, 0, 126)        # #E6007E  – brand magenta
DARK      = (38, 38, 46)         # #26262E
MUTED     = (110, 110, 122)      # #6E6E7A
GRAY_BG   = (242, 242, 245)      # header row bg
WHITE     = (255, 255, 255)
LINE      = (220, 220, 225)
PLUM      = (74, 52, 96)         # badge bg
TBL_LINE  = (200, 200, 208)

def render_slide(title_text, slide_num, total, rows):
    """Return a PIL Image of the slide at RW×RH before downscaling."""
    s = SCALE
    img = Image.new('RGB', (RW, RH), WHITE)
    d = ImageDraw.Draw(img)

    # ---- Fonts (at 2× size) ----
    f_badge   = load_font(20*s)
    f_legend  = load_font(18*s)
    f_title   = load_font(40*s, bold=True)
    f_hdr     = load_font(17*s, bold=True)
    f_section = load_font(18*s, bold=True)
    f_code    = load_font(16*s, bold=True)
    f_cell    = load_font(16*s)
    f_footer  = load_font(14*s)

    # ---- Badge header ("● HOW WE VALIDATE & FIX") ----
    badge_y = 38*s
    dot_r = 9*s
    dot_x, dot_cy = 52*s, badge_y + 14*s
    d.ellipse([dot_x - dot_r, dot_cy - dot_r, dot_x + dot_r, dot_cy + dot_r], fill=PINK)
    badge_text = 'HOW WE VALIDATE & FIX'
    d.text((dot_x + dot_r + 10*s, badge_y + 2*s), badge_text, font=f_badge, fill=DARK)

    # ---- Title ----
    title_y = 72*s
    d.text((52*s, title_y), title_text, font=f_title, fill=DARK)
    _, th = text_size(d, title_text, f_title)

    # ---- Legend ----
    legend_y = title_y + th + 18*s
    dot_r2 = 8*s
    items = [
        ((160, 160, 165), 'Deterministic  (static parse / auto-fix)'),
        (PINK,            'AI  (LLM / vision)'),
        (DARK,            'Human / AT sign-off'),
    ]
    lx = 52*s
    for color, label in items:
        d.ellipse([lx, legend_y + 2*s, lx + dot_r2*2, legend_y + 2*s + dot_r2*2], fill=color)
        d.text((lx + dot_r2*2 + 8*s, legend_y), label, font=f_legend, fill=MUTED)
        tw, _ = text_size(d, label, f_legend)
        lx += dot_r2*2 + 8*s + tw + 40*s

    # ---- Table layout ----
    tbl_top = legend_y + 36*s
    tbl_left = 52*s
    tbl_right = RW - 48*s
    tbl_w = tbl_right - tbl_left

    # Column proportions: Code / Doc check / Assessment / Remediation / Why human? / Status
    col_pcts = [0.075, 0.18, 0.20, 0.195, 0.175, 0.175]
    col_ws = [int(tbl_w * p) for p in col_pcts]
    col_ws[-1] = tbl_w - sum(col_ws[:-1])   # snap last column

    col_xs = [tbl_left]
    for w in col_ws[:-1]:
        col_xs.append(col_xs[-1] + w)

    ROW_H_HDR  = 32*s
    ROW_H_SEC  = 26*s
    ROW_H_DATA = 28*s

    PAD = 6*s

    def draw_row(row_dict, y, is_header=False):
        kind = row_dict['kind']
        cells = row_dict['cells']
        rh = ROW_H_HDR if is_header else (ROW_H_SEC if kind == 'section' else ROW_H_DATA)

        if is_header:
            d.rectangle([tbl_left, y, tbl_right, y + rh], fill=GRAY_BG)
        elif kind == 'section':
            d.rectangle([tbl_left, y, tbl_right, y + rh], fill=PINK)
        else:
            d.rectangle([tbl_left, y, tbl_right, y + rh], fill=WHITE)

        # horizontal separator
        d.line([tbl_left, y + rh, tbl_right, y + rh], fill=TBL_LINE, width=max(1, s))

        if kind == 'section':
            # Section label spans full width
            text = cells[0]['text'] if cells else ''
            d.text((col_xs[0] + PAD, y + (rh - 18*s) // 2), text, font=f_section, fill=WHITE)
        else:
            for ci, (cx, cw) in enumerate(zip(col_xs, col_ws)):
                if ci < len(cells):
                    cell = cells[ci]
                    text = cell['text']
                    # vertical grid line
                    if ci > 0:
                        d.line([cx, y, cx, y + rh], fill=TBL_LINE, width=max(1, s))
                    # choose font / color
                    if is_header:
                        font = f_hdr
                        color = DARK
                    elif ci == 0:
                        # Code column — always pink bold
                        font = f_code
                        color = PINK
                    else:
                        font = f_cell
                        # color from XML
                        clr = cell['color'].upper()
                        if clr == 'E6007E':
                            color = PINK
                        elif clr == '26262E':
                            color = DARK
                        else:
                            color = MUTED
                    # clip text to column width
                    max_w = cw - PAD * 2
                    drawn = text
                    while drawn:
                        tw, _ = text_size(d, drawn, font)
                        if tw <= max_w:
                            break
                        drawn = drawn[:-1]
                    if drawn != text:
                        drawn = drawn[:-1] + '…'
                    d.text((cx + PAD, y + (rh - 16*s) // 2), drawn, font=font, fill=color)
                # add Status column (ci == 5 for data rows when we're on the 6th column)
                # Status is computed separately below

        # Status column
        if not is_header and kind != 'section':
            # code is first cell
            sc_raw = cells[0]['text'] if cells else ''
            sc = re.search(r'\d+\.\d+\.\d+', sc_raw)
            sc = sc.group() if sc else sc_raw
            st = status_for(sc)
            st_color = status_color(st)
            ci = len(col_xs) - 1
            cx = col_xs[ci]
            cw = col_ws[ci]
            if ci > 0:
                d.line([cx, y, cx, y + rh], fill=TBL_LINE, width=max(1, s))
            # clip
            max_w = cw - PAD * 2
            drawn = st
            while drawn:
                tw, _ = text_size(d, drawn, f_cell)
                if tw <= max_w:
                    break
                drawn = drawn[:-1]
            if drawn != st:
                drawn = drawn[:-1] + '…'
            d.text((cx + PAD, y + (rh - 16*s) // 2), drawn, font=f_cell, fill=st_color)

        return rh

    # Draw header row
    hdr_row = {'kind': 'data', 'cells': [
        {'text': 'Code',           'color': '26262E', 'bold': True},
        {'text': 'Document check', 'color': '26262E', 'bold': True},
        {'text': 'Assessment',     'color': '26262E', 'bold': True},
        {'text': 'Remediation',    'color': '26262E', 'bold': True},
        {'text': 'Why human?',     'color': '26262E', 'bold': True},
        {'text': 'Status',         'color': '26262E', 'bold': True},
    ]}
    y = tbl_top
    d.rectangle([tbl_left, y, tbl_right, y + ROW_H_HDR], fill=GRAY_BG)
    for ci, (cx, cw) in enumerate(zip(col_xs, col_ws)):
        if ci > 0:
            d.line([cx, y, cx, y + ROW_H_HDR], fill=TBL_LINE, width=max(1, s))
        col_names = ['Code','Document check','Assessment','Remediation','Why human?','Status']
        d.text((cx + PAD, y + (ROW_H_HDR - 17*s) // 2), col_names[ci], font=f_hdr, fill=DARK)
    d.line([tbl_left, y + ROW_H_HDR, tbl_right, y + ROW_H_HDR], fill=TBL_LINE, width=max(1, s))
    y += ROW_H_HDR

    # Draw table rows (skip row 0 which is the header in original XML)
    for row in rows[1:]:
        rh = draw_row(row, y)
        y += rh

    # Outer table border
    d.rectangle([tbl_left, tbl_top, tbl_right, y], outline=TBL_LINE, width=max(1, s))

    # ---- Footer ----
    footer_text = 'Mova iO AccessOps  ·  Documents'
    page_text = str(slide_num)
    ft_y = RH - 32*s
    d.text((52*s, ft_y), footer_text, font=f_footer, fill=(180, 180, 185))
    pw, _ = text_size(d, page_text, f_footer)
    d.text((RW - 52*s - pw, ft_y), page_text, font=f_footer, fill=(180, 180, 185))

    return img

# ---------------------------------------------------------------------------
# PNG → bytes (deflate-compressed, for embedding in PPTX)
# ---------------------------------------------------------------------------
def img_to_png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=False)
    return buf.getvalue()

# ---------------------------------------------------------------------------
# Minimal PPTX slide XML with a full-bleed image shape
# ---------------------------------------------------------------------------
SLIDE_REL_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/slide{n}_img.png"/>
</Relationships>'''

def image_slide_xml(cx_emu, cy_emu):
    """A slide that is a single full-bleed image (no other shapes)."""
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/><a:chOff x="0" y="0"/><a:chExt cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>
      </p:grpSpPr>
      <p:pic>
        <p:nvPicPr>
          <p:cNvPr id="2" name="Slide"/>
          <p:cNvPicPr/>
          <p:nvPr/>
        </p:nvPicPr>
        <p:blipFill>
          <a:blip r:embed="rId2"/>
          <a:stretch><a:fillRect/></a:stretch>
        </p:blipFill>
        <p:spPr>
          <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
      </p:pic>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>'''

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f'Reading {SRC}')
    with zipfile.ZipFile(SRC) as src_zip:
        names = src_zip.namelist()

        # Read slide XMLs for parsing
        slide2_xml = src_zip.read('ppt/slides/slide2.xml').decode('utf-8', errors='replace')
        slide3_xml = src_zip.read('ppt/slides/slide3.xml').decode('utf-8', errors='replace')

        rows2 = parse_table_rows(slide2_xml)
        rows3 = parse_table_rows(slide3_xml)
        title2 = parse_slide_title(slide2_xml)
        title3 = parse_slide_title(slide3_xml)

        # Fallback titles
        if not title2: title2 = 'Assessment & remediation — all 20 codes  (1 of 2)'
        if not title3: title3 = 'Assessment & remediation — all 20 codes  (2 of 2)'

        print(f'Slide 2: {len(rows2)} rows — "{title2}"')
        print(f'Slide 3: {len(rows3)} rows — "{title3}"')

        # Render PNGs at 2× then downscale
        print('Rendering slide 2 image...')
        img2_hi = render_slide(title2, 2, 3, rows2)
        img2 = img2_hi.resize((W, H), Image.LANCZOS)
        png2 = img_to_png_bytes(img2)

        print('Rendering slide 3 image...')
        img3_hi = render_slide(title3, 3, 3, rows3)
        img3 = img3_hi.resize((W, H), Image.LANCZOS)
        png3 = img_to_png_bytes(img3)

        # Presentation dimensions (from source PPTX)
        prs_xml = src_zip.read('ppt/presentation.xml').decode()
        cx_m = re.search(r'cx="(\d+)"', prs_xml)
        cy_m = re.search(r'cy="(\d+)"', prs_xml)
        cx_emu = cx_m.group(1) if cx_m else '9144000'  # 16:9 default
        cy_emu = cy_m.group(1) if cy_m else '5143500'

        # Build new PPTX from scratch (copy everything, replace slides 2+3)
        DEST.parent.mkdir(parents=True, exist_ok=True)
        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, 'w', compression=zipfile.ZIP_DEFLATED) as out_zip:
            # Copy everything except slides 2 and 3 (and their rels) from source
            skip = {
                'ppt/slides/slide2.xml', 'ppt/slides/_rels/slide2.xml.rels',
                'ppt/slides/slide3.xml', 'ppt/slides/_rels/slide3.xml.rels',
            }
            for name in names:
                if name in skip:
                    continue
                data = src_zip.read(name)
                out_zip.writestr(name, data)

            # Write PNG images
            out_zip.writestr('ppt/media/slide2_img.png', png2)
            out_zip.writestr('ppt/media/slide3_img.png', png3)

            # Write new slide XMLs
            out_zip.writestr('ppt/slides/slide2.xml', image_slide_xml(cx_emu, cy_emu))
            out_zip.writestr('ppt/slides/slide3.xml', image_slide_xml(cx_emu, cy_emu))

            # Write slide rels
            out_zip.writestr('ppt/slides/_rels/slide2.xml.rels', SLIDE_REL_XML.format(n=2))
            out_zip.writestr('ppt/slides/_rels/slide3.xml.rels', SLIDE_REL_XML.format(n=3))

    DEST.write_bytes(out_buf.getvalue())
    print(f'Written {DEST} ({DEST.stat().st_size // 1024} KB)')
    print('Done. Also copy to dist/ if needed:')
    print(f'  cp {DEST} frontend/dist/exports/method-deck.pptx')

if __name__ == '__main__':
    main()
