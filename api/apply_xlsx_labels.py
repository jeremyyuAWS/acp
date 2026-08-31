"""Write reviewer-approved structure labels into an xlsx file (WCAG 2.4.6).

api/proposals.propose_xlsx_labels drafts meaningful names for default-named sheet
tabs and table columns, keyed by:

    locator = 'sheet:<tab name>'                      e.g. 'sheet:Sheet1'
    locator = 'table:<displayName>#col:<colName>'     e.g. 'table:Sales#col:Column1'

This module is the missing write-back: approved labels rename the tabs and columns
inside the zip, so the next re-scan finds no default-named structures and clears 2.4.6.
"""
from __future__ import annotations
import io
import re
import zipfile


def _xesc_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── renaming a sheet means renaming every reference to it ─────────────────────
#
# WHY THIS EXISTS. A sheet's name is not stored once. `xl/workbook.xml` holds the tab, and every
# formula, defined name and chart series that points at the sheet spells the name out again, in
# its own part. Renaming only the tab leaves all of those naming a sheet that no longer exists,
# which Excel resolves to #REF! — so the workbook opens with broken cells.
#
# This was shipping. Renaming `Sheet1` produced, in one package:
#
#     xl/workbook.xml            <sheet name="Findings by quarter" …/>     ← renamed
#     xl/worksheets/sheet2.xml   <f>Sheet1!B1</f>                          ← dangling
#     xl/worksheets/sheet2.xml   <f>SUM(Sheet1!B1:B1)</f>                  ← dangling
#     xl/workbook.xml            <definedName>Sheet1!$B$1</definedName>    ← dangling
#
# and it was invisible from the outside: 2.4.6 cleared on the re-scan, the lane credited the
# value, and no detector reads formulas. Same shape as the 1.4.3 PDF contrast fixer — the
# remediation itself was the damage.
#
# QUOTING. A sheet name may appear bare (`Sheet1!A1`) or quoted (`'My Sheet'!A1`), and must be
# quoted whenever it is not a bare token; an apostrophe inside is doubled. Since the approved
# labels are prose ("Findings by quarter"), the replacement is ALWAYS emitted quoted — Excel
# accepts `'Sheet1'!A1` where quoting was not required, so this needs no needs-quoting predicate
# and cannot get one wrong.

# The sheet part of a reference: everything before a `!`, quoted or bare, one name or a 3-D
# range (`Sheet1:Sheet3!A1`). The bare form's lookbehind keeps it from matching the tail of a
# longer token — `MySheet1!A1` must not match `Sheet1`.
_SHEET_REF = re.compile(
    r"'((?:[^']|'')*)'(?=!)"
    r"|(?<![A-Za-z0-9_.'!])([A-Za-z0-9_.]+(?::[A-Za-z0-9_.]+)?)(?=!)")

# A double-quoted string literal inside a formula. `="Sheet1!A1"` is text a user typed, not a
# reference, and rewriting it would corrupt their data.
_STR_LITERAL = re.compile(r'"(?:[^"]|"")*"')


def _quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _outside_literals(text: str, fn) -> str:
    """Apply `fn` to the parts of a formula that are code, never to its string literals.

    `="Sheet1!A1"` and `="Sales[Column1]"` are text a user typed. They look exactly like a
    reference and are not one, so both rewriters go through here rather than each remembering
    to skip them — the column rewriter did not, and corrupted that text.
    """
    out, last = [], 0
    for m in _STR_LITERAL.finditer(text):
        out.append(fn(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(fn(text[last:]))
    return "".join(out)


def _rewrite_sheet_refs(text: str, renames: dict[str, str]) -> str:
    """Point every sheet reference in one formula/defined-name expression at its new name."""
    if not renames or not text:
        return text

    def _sub(m: re.Match) -> str:
        quoted, bare = m.group(1), m.group(2)
        raw = quoted.replace("''", "'") if quoted is not None else bare
        # A 3-D range names two sheets; either end may be renamed, or neither.
        parts = raw.split(":")
        if not any(p in renames for p in parts):
            return m.group(0)
        return _quote_sheet(":".join(renames.get(p, p) for p in parts))

    return _outside_literals(text, lambda seg: _SHEET_REF.sub(_sub, seg))


def _rewrite_column_refs(text: str, col_renames: dict[tuple[str, str], str]) -> str:
    """Point every structured table reference at its new column name.

    `Sales[Column1]` and `Sales[[#All],[Column1]]` both name the column inside brackets, and a
    column rename breaks them exactly as a sheet rename breaks `Sheet1!A1`.
    """
    if not col_renames or not text:
        return text
    by_table: dict[str, dict[str, str]] = {}
    for (tbl, col), new in col_renames.items():
        by_table.setdefault(tbl, {})[col] = new

    def _sub(m: re.Match) -> str:
        table, body = m.group(1), m.group(2)
        cols = by_table.get(table)
        if not cols:
            return m.group(0)
        if "[" in body:
            # `Sales[[#All],[Column1]]` — rewrite each bracketed name that is a renamed column,
            # leaving item specifiers (`#All`, `#Headers`, …) and other columns alone.
            inner = re.sub(r"\[([^\[\]]*)\]",
                           lambda c: "[" + cols.get(c.group(1), c.group(1)) + "]", body)
        else:
            inner = cols.get(body, body)        # `Sales[Column1]` — the body IS the column
        return f"{table}[{inner}]"

    # One optional level of nesting, which is all a structured reference has.
    return _outside_literals(
        text,
        lambda seg: re.sub(r"([A-Za-z_][A-Za-z0-9_.]*)\[((?:[^\[\]]|\[[^\]]*\])*)\]", _sub, seg))


# The element text that can carry a formula, per part. Worksheets hold cell formulas, shared
# formulas, data-validation bounds and conditional-formatting expressions; workbook.xml holds
# defined names; charts spell out their series ranges.
_FORMULA_TAGS = ("f", "formula1", "formula2", "definedName", "c:f")


def _rewrite_formula_parts(name: str, raw: bytes, renames: dict[str, str],
                           col_renames: dict[tuple[str, str], str]) -> bytes:
    """Rewrite every formula-bearing element in one XML part."""
    if not (renames or col_renames):
        return raw
    if not (name == "xl/workbook.xml"
            or re.fullmatch(r"xl/(worksheets|chartsheets)/sheet\d+\.xml", name)
            or re.fullmatch(r"xl/charts/chart\d+\.xml", name)):
        return raw
    xml = raw.decode("utf-8", errors="replace")
    for tag in _FORMULA_TAGS:
        def _sub(m: re.Match) -> str:
            body = _rewrite_sheet_refs(m.group(2), renames)
            body = _rewrite_column_refs(body, col_renames)
            return m.group(1) + body + m.group(3)
        xml = re.sub(rf"(<{tag}\b[^>]*>)([^<]*)(</{tag}>)", _sub, xml)
    return xml.encode("utf-8")


def apply_xlsx_labels(
    data: bytes, values: dict[str, str]
) -> tuple[bytes, list[dict], list[str]]:
    """Rename default sheet tabs and table columns approved by a reviewer.

    `values` is {locator: approved_label} where locator comes from propose_xlsx_labels:
      'sheet:Sheet1'          → rename workbook.xml sheet tab
      'table:Sales#col:Col1'  → rename table column in xl/tables/tableN.xml

    Returns (fixed_bytes, applied, unresolved).
    applied entries: {locator, before, after}.
    unresolved: locators present in values but not found in the document.
    """
    if not values:
        return data, [], []

    sheet_values: dict[str, str] = {}
    col_values: dict[tuple[str, str], str] = {}
    for locator, label in values.items():
        if locator.startswith("sheet:"):
            sheet_values[locator[len("sheet:"):]] = label
        elif locator.startswith("table:") and "#col:" in locator:
            rest = locator[len("table:"):]
            tbl, col = rest.split("#col:", 1)
            col_values[(tbl, col)] = label

    applied: list[dict] = []
    unresolved: list[str] = list(values.keys())

    try:
        buf_in = io.BytesIO(data)
        buf_out = io.BytesIO()
        with zipfile.ZipFile(buf_in, "r") as zin, zipfile.ZipFile(buf_out, "w") as zout:
            # Which renames this workbook will ACTUALLY perform, settled before anything is
            # written. References live in parts that may come before or after the part carrying
            # the name, so the map cannot be built as the loop goes — and it must describe real
            # renames only: rewriting references for a sheet or column that was never found
            # would break the workbook on behalf of a rename that did not happen.
            applied_sheets = _sheet_renames_in_effect(zin, sheet_values)
            applied_cols = _column_renames_in_effect(zin, col_values)

            for name in zin.namelist():
                raw = zin.read(name)
                info = zin.getinfo(name)

                if name == "xl/workbook.xml" and sheet_values:
                    raw = _rename_sheet_tabs(raw, sheet_values, applied, unresolved)

                elif re.fullmatch(r"xl/tables/table\d+\.xml", name) and col_values:
                    raw = _rename_table_columns(raw, col_values, applied, unresolved)

                # Every part that spells the old name out again — the half this module used to
                # skip, which left the workbook opening with #REF! wherever it was referenced.
                raw = _rewrite_formula_parts(name, raw, applied_sheets, applied_cols)

                new_info = zipfile.ZipInfo(name)
                new_info.compress_type = info.compress_type
                zout.writestr(new_info, raw)

        return buf_out.getvalue(), applied, unresolved
    except Exception:
        return data, [], list(values.keys())


def _sheet_renames_in_effect(zin: zipfile.ZipFile,
                             sheet_values: dict[str, str]) -> dict[str, str]:
    """{old: new} for the sheet tabs this workbook actually has."""
    if not sheet_values:
        return {}
    try:
        xml = zin.read("xl/workbook.xml").decode("utf-8", errors="replace")
    except KeyError:
        return {}
    present = set(re.findall(r'<sheet\b[^>]*\bname="([^"]*)"', xml))
    return {old: new for old, new in sheet_values.items() if old in present}


def _column_renames_in_effect(zin: zipfile.ZipFile,
                              col_values: dict[tuple[str, str], str]) -> dict[tuple[str, str], str]:
    """{(table, old col): new} for the table columns this workbook actually has."""
    if not col_values:
        return {}
    out: dict[tuple[str, str], str] = {}
    for name in zin.namelist():
        if not re.fullmatch(r"xl/tables/table\d+\.xml", name):
            continue
        xml = zin.read(name).decode("utf-8", errors="replace")
        disp_m = re.search(r'\bdisplayName="([^"]*)"', xml)
        if not disp_m:
            continue
        table = disp_m.group(1)
        cols = set(re.findall(r'<tableColumn\b[^>]*\bname="([^"]*)"', xml))
        for (tbl, col), new in col_values.items():
            if tbl == table and col in cols:
                out[(tbl, col)] = new
    return out


def _rename_sheet_tabs(
    raw: bytes,
    sheet_values: dict[str, str],
    applied: list[dict],
    unresolved: list[str],
) -> bytes:
    xml = raw.decode("utf-8", errors="replace")
    pending = dict(sheet_values)   # consume as matched

    def _replace(m: re.Match) -> str:
        tag = m.group(0)
        nm_m = re.search(r'\bname="([^"]*)"', tag)
        if not nm_m or nm_m.group(1) not in pending:
            return tag
        old_name = nm_m.group(1)
        new_name = pending.pop(old_name)
        locator = f"sheet:{old_name}"
        applied.append({"locator": locator, "before": old_name, "after": new_name})
        if locator in unresolved:
            unresolved.remove(locator)
        return tag[:nm_m.start(1)] + _xesc_attr(new_name) + tag[nm_m.end(1):]

    xml = re.sub(r'<sheet\b[^>]*/>', _replace, xml)
    return xml.encode("utf-8")


def _rename_table_columns(
    raw: bytes,
    col_values: dict[tuple[str, str], str],
    applied: list[dict],
    unresolved: list[str],
) -> bytes:
    xml = raw.decode("utf-8", errors="replace")
    disp_m = re.search(r'\bdisplayName="([^"]*)"', xml)
    if not disp_m:
        return raw
    tbl_name = disp_m.group(1)
    pending = {col: label for (tbl, col), label in col_values.items() if tbl == tbl_name}
    if not pending:
        return raw

    def _replace(m: re.Match) -> str:
        tag = m.group(0)
        nm_m = re.search(r'\bname="([^"]*)"', tag)
        if not nm_m or nm_m.group(1) not in pending:
            return tag
        old_col = nm_m.group(1)
        new_col = pending.pop(old_col)
        locator = f"table:{tbl_name}#col:{old_col}"
        applied.append({"locator": locator, "before": old_col, "after": new_col})
        if locator in unresolved:
            unresolved.remove(locator)
        return tag[:nm_m.start(1)] + _xesc_attr(new_col) + tag[nm_m.end(1):]

    xml = re.sub(r'<tableColumn\b[^>]*/>', _replace, xml)
    return xml.encode("utf-8")
