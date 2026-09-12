"""Exact, approved edits to existing PDF tags; never invent text-to-MCID links.

Heading roles and table header scopes require source-anchored proposals. Reading
order accepts only a complete permutation of existing indirect siblings. Untagged
and image-only PDFs remain re-authoring work, rather than fabricated tagged PDFs.
"""
import hashlib
import io
import json
import re

import pikepdf
from pdf_structural_language import _page_content


def _children(node):
    kids = node.get('/K')
    return list(kids) if isinstance(kids, pikepdf.Array) else ([] if kids is None else [kids])


def _writable(pdf):
    if pdf.is_encrypted or pdf.Root.get('/Perms') is not None:
        return False
    form = pdf.Root.get('/AcroForm')
    if not isinstance(form, pikepdf.Dictionary):
        return True
    if int(form.get('/SigFlags', 0)):
        return False
    stack, seen = list(form.get('/Fields', [])), set()
    while stack:
        node = stack.pop()
        if not isinstance(node, pikepdf.Dictionary):
            return False
        key = node.objgen if node.is_indirect else id(node)
        if key in seen or len(seen) >= 2000:
            return False
        seen.add(key)
        if str(node.get('/FT', '')) == '/Sig':
            return False
        stack.extend(list(node.get('/Kids', [])))
    return True


def _marked_content_index(pdf):
    from collections import Counter
    indexes = []
    for page in pdf.pages:
        ids = []
        for instruction in pikepdf.parse_content_stream(page):
            if str(instruction.operator) != 'BDC' or len(instruction.operands) != 2:
                continue
            props = instruction.operands[1]
            if isinstance(props, pikepdf.Name):
                props = page.obj.get('/Resources', {}).get('/Properties', {}).get(props)
            if isinstance(props, pikepdf.Dictionary) and props.get('/MCID') is not None:
                mcid = props['/MCID']
                if type(mcid) is not int or mcid < 0:
                    raise ValueError('invalid content MCID')
                ids.append(mcid)
        indexes.append(Counter(ids))
    return indexes


def _parent_tree(root):
    tree = root.get('/ParentTree')
    if not isinstance(tree, pikepdf.Dictionary):
        raise ValueError('existing ParentTree is required')
    stack, seen, output = [tree], set(), {}
    while stack:
        node = stack.pop()
        key = node.objgen if node.is_indirect else id(node)
        if key in seen or len(seen) >= 4000:
            raise ValueError('ambiguous ParentTree')
        seen.add(key)
        nums = node.get('/Nums', [])
        if len(nums) % 2:
            raise ValueError('invalid ParentTree number pairs')
        for i in range(0, len(nums), 2):
            if type(nums[i]) is not int or nums[i] in output:
                raise ValueError('duplicate ParentTree key')
            output[nums[i]] = nums[i + 1]
        stack.extend(list(node.get('/Kids', [])))
    return output


def _inventory(pdf):
    root = pdf.Root.get('/StructTreeRoot')
    if not isinstance(root, pikepdf.Dictionary):
        return []
    pages = {page.obj.objgen: i for i, page in enumerate(pdf.pages)}
    rows, seen = [], set()
    marked, parent_tree = _marked_content_index(pdf), _parent_tree(root)

    def walk(node, path, page, depth, parent):
        if depth > 32 or len(rows) >= 4000:
            raise ValueError('unbounded PDF structure')
        if not isinstance(node, pikepdf.Dictionary) or str(node.get('/Type', '')) != '/StructElem':
            return
        if not node.is_indirect or node.objgen in seen:
            raise ValueError('ambiguous or cyclic PDF structure')
        seen.add(node.objgen)
        if not isinstance(node.get('/P'), pikepdf.Dictionary) or node['/P'].objgen != parent.objgen:
            raise ValueError('inconsistent structure parent')
        page = node.get('/Pg', page)
        page_index = pages.get(page.objgen) if isinstance(page, pikepdf.Dictionary) else None
        kids = _children(node)
        content = []
        for child in kids:
            if isinstance(child, int) and child >= 0:
                content.append(['mcid', child])
            elif isinstance(child, pikepdf.Dictionary) and str(child.get('/Type', '')) == '/MCR':
                if not isinstance(child.get('/MCID'), int) or child['/MCID'] < 0:
                    raise ValueError('invalid marked content')
                content.append(['mcr', child['/MCID'], pages.get(child.get('/Pg', page).objgen) if isinstance(child.get('/Pg', page), pikepdf.Dictionary) else None, hashlib.sha256(child['/Stm'].read_bytes()).hexdigest() if isinstance(child.get('/Stm'), pikepdf.Stream) else None])
            elif isinstance(child, pikepdf.Dictionary) and str(child.get('/Type', '')) == '/StructElem':
                content.append(['tag', str(child.get('/S', '')), str(child.get('/ActualText', ''))])
            else:
                # OBJR / mixed unsupported structure must not become a reorder target.
                content.append(['other', str(child)])
        for entry in content:
            if entry[0] not in {'mcid', 'mcr'}:
                continue
            content_page = page_index if entry[0] == 'mcid' else entry[2]
            if content_page is None or entry[0] == 'mcr' and entry[3] is not None:
                raise ValueError('unresolved page or XObject marked content')
            mcid = entry[1]
            if marked[content_page][mcid] != 1:
                raise ValueError('missing or duplicate page marked content')
            key = pdf.pages[content_page].obj.get('/StructParents')
            parents = parent_tree.get(key) if type(key) is int else None
            if not isinstance(parents, pikepdf.Array) or mcid >= len(parents) or not isinstance(parents[mcid], pikepdf.Dictionary) or parents[mcid].objgen != node.objgen:
                raise ValueError('marked content ParentTree does not identify this tag')
        identity = {'role': str(node.get('/S', '')), 'text': str(node.get('/ActualText', '')),
                    'id': str(node.get('/ID', '')), 'page': page_index, 'content': content, 'attributes': str(node.get('/A', ''))}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        locator = 'pdf:struct:' + '.'.join(map(str, path)) + ':' + digest
        row = dict(identity, locator=locator, path=path, node=node)
        rows.append(row)
        for i, child in enumerate(kids):
            walk(child, path + (i,), page, depth + 1, node)

    for i, child in enumerate(_children(root)):
        walk(child, (i,), None, 0, root)
    source = hashlib.sha256(json.dumps([{k: v for k, v in r.items() if k not in {'node', 'locator'}} for r in rows], sort_keys=True).encode() + b''.join(stream for page in pdf.pages for stream in _page_content(page))).hexdigest()
    for row in rows:
        row['locator'] = 'pdf:struct:' + '.'.join(map(str, row['path'])) + ':' + source
    return rows


def collect_structure_targets(pdf):
    try:
        return [{k: v for k, v in row.items() if k != 'node'} for row in _inventory(pdf)]
    except Exception:
        return []


def _plan(value):
    if isinstance(value, str) and len(value) <= 16000:
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('expected structured edit')
    return value


def _edit(row, plan):
    node, role = row['node'], row['role']
    op = plan.get('op')
    if op == 'heading' and set(plan) == {'op', 'role'}:
        kids = _children(node)
        if role not in {'/P', '/Span', '/H', '/H1', '/H2', '/H3', '/H4', '/H5', '/H6'} or not row['text'].strip():
            raise ValueError('heading must target existing text-bearing leaf')
        if not kids or not all(isinstance(k, int) and k >= 0 or isinstance(k, pikepdf.Dictionary)
                and str(k.get('/Type', '')) == '/MCR' for k in kids):
            raise ValueError('heading cannot consume nested or object content')
        if not isinstance(plan['role'], str) or not re.fullmatch('H[1-6]', plan['role']):
            raise ValueError('invalid heading level')
        node['/S'] = pikepdf.Name('/' + plan['role'])
        return 'SC_2_4_6', role, '/' + plan['role']
    if op == 'header-scope' and set(plan) == {'op', 'scope'}:
        if role != '/TH' or plan['scope'] not in {'Row', 'Column', 'Both'}:
            raise ValueError('scope must target existing header')
        attributes = node.get('/A')
        # Do not discard attribute arrays, owner revisions, or another attribute owner.
        if attributes is None:
            attributes = pikepdf.Dictionary(O=pikepdf.Name.Table)
            node['/A'] = attributes
        if not isinstance(attributes, pikepdf.Dictionary) or str(attributes.get('/O', '')) != '/Table':
            raise ValueError('ambiguous table attributes')
        before = str(attributes.get('/Scope', ''))
        attributes['/Scope'] = pikepdf.Name('/' + plan['scope'])
        return 'SC_1_3_1', before, '/' + plan['scope']
    if op == 'table-headers' and set(plan) == {'op', 'headers'}:
        headers = plan['headers']
        if role != '/TD' or not isinstance(headers, list) or not headers or len(headers) > 100 or any(
                not isinstance(h, str) or not h or len(h) > 512 for h in headers) or len(set(headers)) != len(headers):
            raise ValueError('headers require exact existing header IDs')
        parent = node.get('/P')
        while isinstance(parent, pikepdf.Dictionary) and str(parent.get('/S', '')) != '/Table':
            parent = parent.get('/P')
        if not isinstance(parent, pikepdf.Dictionary):
            raise ValueError('cell is outside an existing table')
        stack, header_ids = [parent], []
        while stack:
            child = stack.pop()
            if not isinstance(child, pikepdf.Dictionary):
                continue
            # Nested tables have their own relationships and cannot supply these headers.
            if child.objgen != parent.objgen and str(child.get('/S', '')) == '/Table':
                continue
            if str(child.get('/S', '')) == '/TH' and isinstance(child.get('/ID'), pikepdf.String):
                header_ids.append(str(child['/ID']))
            stack.extend(k for k in _children(child) if isinstance(k, pikepdf.Dictionary)
                         and str(k.get('/Type', '')) == '/StructElem')
        if any(header_ids.count(h) != 1 for h in headers):
            raise ValueError('missing or duplicate header IDs in current table')
        tree_root = parent
        while str(tree_root.get('/Type', '')) != '/StructTreeRoot':
            tree_root = tree_root['/P']
        id_tree = tree_root.get('/IDTree')
        if not isinstance(id_tree, pikepdf.Dictionary):
            raise ValueError('existing header IDTree is required')
        stack, seen, mapped = [id_tree], set(), {}
        while stack:
            entry = stack.pop()
            key = entry.objgen if entry.is_indirect else id(entry)
            if key in seen or len(seen) >= 4000:
                raise ValueError('ambiguous IDTree')
            seen.add(key)
            names = entry.get('/Names', [])
            if len(names) % 2:
                raise ValueError('invalid IDTree name pairs')
            for i in range(0, len(names), 2):
                label = str(names[i])
                if label in mapped:
                    raise ValueError('duplicate IDTree name')
                mapped[label] = names[i + 1]
            stack.extend(list(entry.get('/Kids', [])))
        for h in headers:
            resolved = mapped.get(h)
            if not isinstance(resolved, pikepdf.Dictionary) or str(resolved.get('/S', '')) != '/TH' or str(resolved.get('/ID', '')) != h:
                raise ValueError('IDTree does not resolve this header')
            owner = resolved
            while str(owner.get('/S', '')) != '/Table':
                owner = owner['/P']
            if owner.objgen != parent.objgen:
                raise ValueError('IDTree header belongs to a different table')

        attributes = node.get('/A')
        if attributes is None:
            attributes = pikepdf.Dictionary(O=pikepdf.Name.Table)
            node['/A'] = attributes
        if not isinstance(attributes, pikepdf.Dictionary) or str(attributes.get('/O', '')) != '/Table':
            raise ValueError('ambiguous table attributes')
        before = json.dumps([str(h) for h in attributes.get('/Headers', [])])
        attributes['/Headers'] = pikepdf.Array([pikepdf.String(h) for h in headers])
        return 'SC_1_3_1', before, json.dumps(headers)
    if op == 'reading-order' and set(plan) == {'op', 'order'}:
        kids, order = _children(node), plan['order']
        if role not in {'/Document', '/Part', '/Sect', '/Div'} or len(kids) < 2:
            raise ValueError('order must target an existing section')
        if not all(isinstance(k, pikepdf.Dictionary) and k.is_indirect
                   and str(k.get('/Type', '')) == '/StructElem' for k in kids):
            raise ValueError('mixed content cannot be reordered')
        if not isinstance(order, list) or any(type(i) is not int for i in order) or sorted(order) != list(range(len(kids))):
            raise ValueError('order must be a complete sibling permutation')
        # Parent-tree references and each child /P stay intact; only traversal order changes.
        node['/K'] = pikepdf.Array([kids[i] for i in order])
        return 'SC_1_3_2', json.dumps(list(range(len(kids)))), json.dumps(order)
    raise ValueError('unsupported structure edit')


def apply_pdf_structure_repairs(data, values):
    """Atomic validated batch; stale/invalid plans return the original bytes untouched."""
    unresolved = list(values or {})
    if not unresolved:
        return data, [], []
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            if not _writable(pdf):
                return data, [], unresolved
            rows = {row['locator']: row for row in _inventory(pdf)}
            content = [_page_content(page) for page in pdf.pages]
            applied = []
            for locator, value in values.items():
                row = rows[locator]
                plan = _plan(value)
                rule, before, after = _edit(row, plan)
                if before == after:
                    raise ValueError('no change')
                applied.append({'locator': locator, 'rule_id': rule, 'value': value,
                                'before': before, 'after': after})
            expected = [{k: v for k, v in r.items() if k not in {'node', 'locator'}} for r in _inventory(pdf)]
            out = io.BytesIO(); pdf.save(out)
        candidate = out.getvalue()
        with pikepdf.open(io.BytesIO(candidate)) as reopened:
            if content != [_page_content(page) for page in reopened.pages]:
                raise ValueError('page content changed')
            # Object numbers may change on save; structure remains navigable and bounded.
            restored = [{k: v for k, v in r.items() if k not in {'node', 'locator'}} for r in _inventory(reopened)]
            if restored != expected:
                raise ValueError('structure edit did not survive save')
        return candidate, applied, []
    except Exception:
        return data, [], unresolved


def propose_tagged_repairs(pdf, headings=()):
    """Only exact text-bearing existing tags and unambiguous first-row header scopes."""
    from proposals import heading_level_sequence, proposal
    try:
        if not _writable(pdf):
            return []
        rows = _inventory(pdf)
        if not rows:
            return []
        output = []
        levels = heading_level_sequence(size for _, _, size in headings)
        for (text, page, _), level in zip(headings, levels):
            matches = [r for r in rows if r['role'] in {'/P', '/Span'} and r['text'].strip() == text.strip() and r['page'] == page]
            if len(matches) != 1:
                continue
            row = matches[0]
            plan = {'op': 'heading', 'role': 'H' + str(level)}
            # Verify writability on a disposable open candidate via structural preconditions.
            kids = _children(row['node'])
            if not kids or not all(isinstance(k, int) and k >= 0 or isinstance(k, pikepdf.Dictionary)
                                   and str(k.get('/Type', '')) == '/MCR' for k in kids):
                continue
            output.append(proposal(locator=row['locator'], before=row['role'],
                proposed_value=json.dumps(plan), kind='pdf-tag-heading',
                rationale='Existing tagged text exactly matches this visual heading; promote its role without changing text or marked content.',
                source='exact tagged text and page match; document font hierarchy (heuristic)'))
            output[-1]['subject_text'] = row['text'][:500]
        for row in rows:
            if row['role'] != '/Table':
                continue
            table_rows = _children(row['node'])
            if not table_rows or not all(isinstance(r, pikepdf.Dictionary) and str(r.get('/S', '')) == '/TR' for r in table_rows):
                continue
            header = _children(table_rows[0])
            if not header or not all(isinstance(cell, pikepdf.Dictionary) and str(cell.get('/S', '')) == '/TH' for cell in header):
                continue
            body = [_children(r) for r in table_rows[1:]]
            if not body or not all(len(cells) == len(header) and all(isinstance(c, pikepdf.Dictionary)
                    and str(c.get('/S', '')) == '/TD' for c in cells) for cells in body):
                continue
            cells = header + [c for cells in body for c in cells]
            if any(c.get('/A') is not None and (not isinstance(c['/A'], pikepdf.Dictionary)
                    or str(c['/A'].get('/O', '')) != '/Table'
                    or int(c['/A'].get('/RowSpan', 1)) != 1 or int(c['/A'].get('/ColSpan', 1)) != 1) for c in cells):
                continue
            for cell in header:
                attr = cell.get('/A')
                if attr is not None and attr.get('/Scope') is not None:
                    continue
                target = next(r for r in rows if r['node'].objgen == cell.objgen)
                output.append(proposal(locator=target['locator'], before='(existing table header has no scope)',
                    proposed_value=json.dumps({'op': 'header-scope', 'scope': 'Column'}), kind='pdf-table-header-scope',
                    rationale='The existing first row contains only header cells above a rectangular body; mark these as column headers.',
                    source='existing tagged rectangular table topology (heuristic)'))
                output[-1]['subject_text'] = target['text'][:500]
        return output[:100]
    except Exception:
        return []
