"""Native Word revision companion; the assessed corrected copy stays accepted.

This is a bounded comparison of two exact packages, not a generic Word diff.
Unsupported edits remain visible in the corrected companion and are reported;
existing author revisions are never accepted, rejected, or nested by ACP.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from html import escape
from xml.etree import ElementTree as ET

from remediated_copy_audit import inspect

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_P = re.compile(r'<w:p\b[^>]*>.*?</w:p>', re.S)
_R = re.compile(r'<w:r\b[^>]*>.*?</w:r>', re.S)
_RPR = re.compile(r'<w:rPr\b[^>]*/>|<w:rPr\b[^>]*>.*?</w:rPr>', re.S)
_T = re.compile(r'<w:t\b[^>]*>[^<]*</w:t>', re.S)
_LINK = re.compile(r'(<w:hyperlink\b[^>]*>)(.*?)(</w:hyperlink>)', re.S)
_REVISION = re.compile(r'<w:(?:ins|del|moveFrom|moveTo|\w*Change)\b')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _runs_only(xml):
    """No fields, drawings, bookmarks or revision wrappers in a revision target."""
    runs = list(_R.finditer(xml))
    if not runs or _R.sub('', xml).strip():
        return False
    for run in runs:
        inner = re.sub(r'^<w:r\b[^>]*>|</w:r>$', '', run.group(0))
        if _T.sub('', _RPR.sub('', inner)).strip() or not _T.search(inner):
            return False
    return True


def _body(para):
    opening = re.match(r'<w:p\b[^>]*>', para).group(0)
    body = para[len(opening):-len('</w:p>')]
    prop = re.match(r'\s*(<w:pPr\b[^>]*/>|<w:pPr\b[^>]*>.*?</w:pPr>)', body, re.S)
    ppr = prop.group(0) if prop else ''
    return opening, ppr, body[len(ppr):]


def build_tracked_companion(original: bytes, corrected: bytes, *,
                            author: str = 'Mova.io ACP', date: str | None = None):
    """Return (companion DOCX bytes or None, exact-artifact comparison report).

    Native revisions cover simple paragraph text and hyperlink labels. Metadata,
    formatting and structural edits use the ordinary before/after audit instead.
    A companion is emitted only when at least one supported native edit exists.
    """
    report = {'source_sha256': _hash(original), 'corrected_sha256': _hash(corrected),
              'companion_sha256': None, 'tracked_changes': [], 'untracked_changes': [],
              'complete': False, 'primary_copy_has_accepted_changes': True}
    def unsupported(part, reason, paragraph=None):
        row = {'part': part, 'reason': reason}
        if paragraph is not None:
            row['paragraph'] = paragraph
        if len(report['untracked_changes']) < 1000:
            report['untracked_changes'].append(row)
        else:
            report['untracked_changes_omitted'] = report.get('untracked_changes_omitted', 0) + 1
    try:
        def read(data):
            if len(data) > 128 * 1024 * 1024:
                raise ValueError('Package exceeds companion size limit')
            inventory = inspect(data, 'docx')
            if not inventory['readable']:
                raise ValueError('; '.join(inventory['errors']))
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if len(z.infolist()) > 10000 or sum(i.file_size for i in z.infolist()) > 256 * 1024 * 1024:
                    raise ValueError('Expanded package exceeds companion size limit')
                if len(z.namelist()) != len(set(z.namelist())):
                    raise ValueError('duplicate package entry')
                entries = {n: z.read(n) for n in z.namelist()}
            if 'word/document.xml' not in entries:
                raise ValueError('not a Word package')
            for name, raw in entries.items():
                if name.endswith('.xml'):
                    if re.search(r'<!\s*(DOCTYPE|ENTITY)', raw.decode('utf-8-sig'), re.I):
                        raise ValueError('unsafe XML declaration')
                    ET.fromstring(raw)
            return entries
        before, after = read(original), read(corrected)
    except (ValueError, KeyError, UnicodeError, zipfile.BadZipFile, ET.ParseError) as exc:
        unsupported('package', 'Unreadable or unsupported Word package: ' + type(exc).__name__)
        return None, report
    date = date or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Package-wide fresh IDs preserve author revisions and avoid collisions.
    ids = [int(n) for raw in after.values() for n in
           re.findall(rb'w:id=["\']([0-9]+)["\']', raw)]
    next_id = max(ids, default=0) + 1
    def revision(old, new):
        nonlocal next_id
        attrs = f'w:author="{escape(author, quote=True)}" w:date="{escape(date, quote=True)}"'
        deleted = re.sub(r'<(/?)w:t\b', r'<\1w:delText', old)
        out = f'<w:del w:id="{next_id}" {attrs}>{deleted}</w:del>'
        next_id += 1
        out += f'<w:ins w:id="{next_id}" {attrs}>{new}</w:ins>'
        next_id += 1
        return out
    output = dict(after)
    for name in sorted(set(before) | set(after)):
        if before.get(name) == after.get(name):
            continue
        if not re.fullmatch(r'word/(?:document|header\d+|footer\d+)\.xml', name):
            unsupported(name, 'Metadata, relationships or non-text edits are recorded in the change audit')
            continue
        if name not in before or name not in after:
            unsupported(name, 'Added or removed document part')
            continue
        old_xml, new_xml = before[name].decode('utf-8'), after[name].decode('utf-8')
        # Fixed prefixes permit surgical preservation of namespace declarations.
        if ET.fromstring(new_xml).tag not in {f'{{{_W}}}document', f'{{{_W}}}hdr', f'{{{_W}}}ftr'}:
            unsupported(name, 'Unsupported namespace')
            continue
        old_ps, new_ps = list(_P.finditer(old_xml)), list(_P.finditer(new_xml))
        if len(old_ps) != len(new_ps) or _P.sub('', old_xml) != _P.sub('', new_xml):
            unsupported(name, 'Paragraph population or surrounding structure changed')
            continue
        pieces, tail = [], 0
        for index, (old_p, new_p) in enumerate(zip(old_ps, new_ps), 1):
            old, new = old_p.group(0), new_p.group(0)
            if old == new:
                continue
            if len(report['tracked_changes']) >= 1000:
                unsupported(name, 'Native comparison limit reached; remaining edits use change audit', index)
                continue
            opening, ppr, inner = _body(new)
            old_open, old_ppr, old_inner = _body(old)
            rebuilt = None
            if _REVISION.search(old + new):
                unsupported(name, 'Existing revisions overlap this paragraph; left unchanged', index)
            elif opening != old_open or ppr != old_ppr:
                unsupported(name, 'Paragraph properties changed; retained in accepted corrected copy', index)
            elif _runs_only(old_inner) and _runs_only(inner):
                if ''.join(_T.findall(old_inner)) != ''.join(_T.findall(inner)):
                    rebuilt = opening + ppr + revision(old_inner, inner) + '</w:p>'
                else:
                    unsupported(name, 'Run formatting edit is not represented as text revisions', index)
            else:
                old_links, new_links = list(_LINK.finditer(old_inner)), list(_LINK.finditer(inner))
                if (old_links and len(old_links) == len(new_links)
                        and _LINK.sub('', old_inner) == _LINK.sub('', inner)):
                    rebuilt_inner, link_tail, changed = [], 0, False
                    for a, b in zip(old_links, new_links):
                        if a.group(0) == b.group(0):
                            continue
                        if a.group(1) != b.group(1) or not _runs_only(a.group(2)) or not _runs_only(b.group(2)):
                            changed = False
                            break
                        rebuilt_inner += [inner[link_tail:b.start()], b.group(1),
                                          revision(a.group(2), b.group(2)), b.group(3)]
                        link_tail, changed = b.end(), True
                    if changed:
                        rebuilt = opening + ppr + ''.join(rebuilt_inner) + inner[link_tail:] + '</w:p>'
                if rebuilt is None:
                    unsupported(name, 'Complex runs, fields, drawings or structural edits cannot be tracked safely', index)
            if rebuilt is not None:
                pieces += [new_xml[tail:new_p.start()], rebuilt]
                tail = new_p.end()
                report['tracked_changes'].append({'part': name, 'paragraph': index, 'kind': 'text'})
        pieces.append(new_xml[tail:])
        output[name] = ''.join(pieces).encode('utf-8')
    if not report['tracked_changes']:
        return None, report
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in output.items():
            z.writestr(name, raw)
    data = buf.getvalue()
    report['companion_sha256'] = _hash(data)
    report['complete'] = not report['untracked_changes'] and not report.get('untracked_changes_omitted')
    return data, report
