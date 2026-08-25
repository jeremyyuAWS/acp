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
            for name in zin.namelist():
                raw = zin.read(name)
                info = zin.getinfo(name)

                if name == "xl/workbook.xml" and sheet_values:
                    raw = _rename_sheet_tabs(raw, sheet_values, applied, unresolved)

                elif re.fullmatch(r"xl/tables/table\d+\.xml", name) and col_values:
                    raw = _rename_table_columns(raw, col_values, applied, unresolved)

                new_info = zipfile.ZipInfo(name)
                new_info.compress_type = info.compress_type
                zout.writestr(new_info, raw)

        return buf_out.getvalue(), applied, unresolved
    except Exception:
        return data, [], list(values.keys())


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
