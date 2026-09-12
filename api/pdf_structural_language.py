"""Bounded language repairs on existing, text-bearing tagged PDF leaves.

Only /P and /Span elements with their own /ActualText and marked-content
references qualify. We never infer text-to-MCID associations or create tags.
"""
from dataclasses import dataclass
import hashlib
import io
import re

import pikepdf


def valid_language(value):
    # BCP47-shaped syntax; semantic language accuracy remains a review decision.
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value))


@dataclass(frozen=True)
class PdfLanguageTarget:
    locator: str
    text: str
    current_language: str | None
    page_index: int | None
    suggested_language: str | None = None


def _targets(pdf):
    root = pdf.Root.get('/StructTreeRoot')
    if not isinstance(root, pikepdf.Dictionary):
        return []
    output, visited, count = [], set(), 0
    pages = {page.obj.objgen: i for i, page in enumerate(pdf.pages)}

    def walk(value, path, depth, inherited_page, inherited_language=None):
        nonlocal count
        count += 1
        if depth > 32 or count > 4000:
            raise ValueError('PDF structure exceeds bounded traversal')
        if isinstance(value, pikepdf.Array):
            for i, child in enumerate(value):
                walk(child, path + (i,), depth + 1, inherited_page, inherited_language)
            return
        if not isinstance(value, pikepdf.Dictionary):
            return
        ident = value.objgen if value.is_indirect else id(value)
        if ident in visited:
            raise ValueError('PDF structure has repeated or cyclic elements')
        visited.add(ident)
        page = value.get('/Pg', inherited_page)
        language = str(value.get('/Lang', inherited_language or '')).strip() or None
        kids = value.get('/K')
        parts = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
        # Every child must identify existing marked content. Nested structure is
        # excluded because its /ActualText cannot safely locate a single passage.
        leaf = bool(parts) and all(isinstance(k, int) and k >= 0 or
            isinstance(k, pikepdf.Dictionary) and str(k.get('/Type', '')) == '/MCR'
            and isinstance(k.get('/MCID'), int) and k.get('/MCID') >= 0 for k in parts)
        actual = value.get('/ActualText')
        if leaf and str(value.get('/S', '')) in {'/P', '/Span'} and isinstance(actual, pikepdf.String):
            text = str(actual).strip()
            if text and len(text) <= 8000:
                digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
                locator = 'pdf:lang:' + '.'.join(map(str, path)) + ':' + digest
                output.append((PdfLanguageTarget(locator, text, language,
                    pages.get(page.objgen) if isinstance(page, pikepdf.Dictionary) else None), value))
        if not leaf and kids is not None:
            walk(kids, path + (0,), depth + 1, page, language)

    walk(root.get('/K'), (0,), 0, None)
    return output


def collect_language_targets(pdf):
    """Return all exact targets, or fail closed on ambiguous/unbounded trees."""
    try:
        return [target for target, _ in _targets(pdf)]
    except Exception:
        return []


def deficient_language_targets(pdf):
    """High-confidence language suggestions, relative to explicit document language."""
    from dataclasses import replace
    try:
        import textchecks
        if not textchecks._langdetect_available():
            return []
        from langdetect import detect_langs
        primary = str(pdf.Root.get('/Lang', '')).split('-')[0].lower()
        if not primary:
            return []
        result = []
        for target in collect_language_targets(pdf):
            if len(target.text.split()) < 10:
                continue
            detected = detect_langs(target.text)
            if not detected or detected[0].prob < .95:
                continue
            language = detected[0].lang
            marked = (target.current_language or '').split('-')[0].lower()
            if language != primary and marked != language and valid_language(language):
                result.append(replace(target, suggested_language=language))
        return result[:20]
    except Exception:
        return []


def language_parts_checks(path):
    try:
        with pikepdf.open(path) as pdf:
            return [{'wcag': '3.1.2', 'location': t.locator,
                'description': 'Tagged passage lacks the matching language mark.',
                'message': 'Tagged passage lacks the matching language mark.',
                'severity': 'moderate'} for t in deficient_language_targets(pdf)]
    except Exception:
        return []


def language_marked_spans(path):
    """Text known to carry effective structural language, for text rechecks."""
    try:
        with pikepdf.open(path) as pdf:
            marked = {}
            for target in collect_language_targets(pdf):
                if target.current_language and valid_language(target.current_language):
                    base = target.current_language.split('-')[0].lower()
                    marked.setdefault(base, []).append(target.text)
            return {base: ' '.join(text) for base, text in marked.items()}
    except Exception:
        return {}


def apply_pdf_structure_language(data, values):
    """Apply approved /Lang changes and reopen; preserve every page content stream."""
    unresolved = list(values or {})
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            # Saving a signed candidate would invalidate its existing signature.
            form = pdf.Root.get('/AcroForm')
            if pdf.is_encrypted or pdf.Root.get('/Perms') is not None or (
                    isinstance(form, pikepdf.Dictionary) and int(form.get('/SigFlags', 0))):
                return data, [], unresolved
            targets = {t.locator: (t, node) for t, node in _targets(pdf)}
            content = [_page_content(page) for page in pdf.pages]
            applied = []
            for locator, value in (values or {}).items():
                if locator not in targets or not valid_language(value):
                    continue
                target, node = targets[locator]
                if target.current_language == value:
                    continue
                node['/Lang'] = pikepdf.String(value)
                applied.append({'locator': locator, 'rule_id': 'SC_3_1_2', 'value': value,
                    'before': target.current_language or '', 'after': value})
            if not applied:
                return data, [], unresolved
            out = io.BytesIO()
            pdf.save(out)
        candidate = out.getvalue()
        with pikepdf.open(io.BytesIO(candidate)) as reopened:
            if content != [_page_content(page) for page in reopened.pages]:
                return data, [], unresolved
            restored = {t.locator: t for t in collect_language_targets(reopened)}
            if any(restored.get(row['locator']) is None or restored[row['locator']].current_language != row['after'] for row in applied):
                return data, [], unresolved
        return candidate, applied, [k for k in unresolved if not any(r['locator'] == k for r in applied)]
    except Exception:
        return data, [], unresolved


def _page_content(page):
    value = page.obj.get('/Contents')
    streams = list(value) if isinstance(value, pikepdf.Array) else [value]
    return tuple(stream.read_bytes() for stream in streams if isinstance(stream, pikepdf.Stream))
