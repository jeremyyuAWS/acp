"""Bounded 1.3.1 tagged-table header relationships, never whole-PDF semantics.

Read only existing well-formed tag/MCID/ParentTree associations. A header must
carry a valid Table Scope unless data-cell Headers resolve through unique IDs in
that same table. Structural presence is exact; semantic correctness of scopes,
complex table relationships, headings/lists and untagged reconstruction remain
outside this partial technique and a clean result is REVIEW, never certified PASS.
"""
from pathlib import Path
import pikepdf


def _attributes(node):
    value=node.get('/A')
    if value is None:
        return None
    if isinstance(value,pikepdf.Dictionary) and str(value.get('/O',''))=='/Table':
        return value
    return False


def _id_map(root):
    tree=root.get('/IDTree')
    if not isinstance(tree,pikepdf.Dictionary):
        return {}
    stack,seen,mapped=[tree],set(),{}
    while stack:
        node=stack.pop()
        if not isinstance(node,pikepdf.Dictionary):
            return {}
        key=node.objgen if node.is_indirect else id(node)
        if key in seen or len(seen)>=4000:
            return {}
        seen.add(key)
        names=node.get('/Names',[])
        if len(names)%2:
            return {}
        for i in range(0,len(names),2):
            if not isinstance(names[i],pikepdf.String) or str(names[i]) in mapped:
                return {}
            mapped[str(names[i])]=names[i+1]
        stack.extend(list(node.get('/Kids',[])))
    return mapped


def detect(path:Path)->list[dict]:
    from pdf_structure_repairs import _inventory
    findings=[]
    try:
        with pikepdf.open(str(path)) as pdf:
            rows=_inventory(pdf)
            by_path={r['path']:r for r in rows}
            root=pdf.Root.get('/StructTreeRoot')
            if not isinstance(root,pikepdf.Dictionary):
                return []
            ids=_id_map(root)
            for table in [r for r in rows if r['role']=='/Table']:
                cells=[]
                for row in rows:
                    if row['role'] not in {'/TH','/TD'} or row['path'][:len(table['path'])]!=table['path']:
                        continue
                    ancestors=[by_path.get(row['path'][:i]) for i in range(len(table['path'])+1,len(row['path']))]
                    if any(a and a['role']=='/Table' for a in ancestors):
                        continue
                    cells.append(row)
                headers=[r for r in cells if r['role']=='/TH']
                data=[r for r in cells if r['role']=='/TD']
                if not headers or not data:
                    continue
                header_ids={str(r['node'].get('/ID','')):r for r in headers if isinstance(r['node'].get('/ID'),pikepdf.String)}
                duplicate_ids={str(r['node'].get('/ID','')) for r in headers if sum(str(h['node'].get('/ID',''))==str(r['node'].get('/ID','')) for h in headers)>1}
                def valid_headers(cell):
                    attrs=_attributes(cell['node'])
                    values=attrs.get('/Headers') if isinstance(attrs,pikepdf.Dictionary) else None
                    if not isinstance(values,pikepdf.Array) or not values:
                        return False
                    names=[str(v) for v in values if isinstance(v,pikepdf.String)]
                    if len(names)!=len(values) or len(set(names))!=len(names):
                        return False
                    return all(name not in duplicate_ids and name in header_ids and isinstance(ids.get(name),pikepdf.Dictionary)
                               and ids[name].objgen==header_ids[name]['node'].objgen for name in names)
                linked=all(valid_headers(cell) for cell in data)
                if linked:
                    continue
                for header in headers:
                    attrs=_attributes(header['node'])
                    # Attribute arrays/revisions are outside this bounded parser, not
                    # evidence that a concrete Scope is missing.
                    if attrs is False:
                        continue
                    scope=str(attrs.get('/Scope','')) if isinstance(attrs,pikepdf.Dictionary) else ''
                    if scope in {'/Row','/Column','/Both'}:
                        continue
                    findings.append({'ruleId':'PDF_TABLE_HEADER_SCOPE_MISSING',
                        'wcag':'1.3.1 Info and Relationships','severity':'SERIOUS',
                        'location':header['locator'],
                        'detail':'Existing tagged table header has no valid Table Scope and data-cell Headers do not establish complete relationships.'})
    except Exception:
        # Unsupported malformed/complex associations never become proof of a clean
        # complete criterion; registry PARTIAL preserves REVIEW on a clean result.
        return []
    return findings
