"""
HTML fixer: html.table-headers
Adds scope attributes to <th> elements and promotes first-row <td> cells to <th scope="col">
where table header markup is missing or incomplete.
Handles axe rules: td-headers-attr, th-has-data-cells, scope-attr-valid.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus


class HtmlTableHeaderFixer(BaseFixer):
    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            tables = _find_target_tables(document, issue)
            if not tables:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No target tables found for this issue",
                    issue_id=issue.issue_id,
                )

            fixed_tables = 0
            total_changes = 0

            for table in tables:
                changes = _fix_table(table)
                if changes > 0:
                    fixed_tables += 1
                    total_changes += changes

            if total_changes == 0:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="Tables already have adequate header markup",
                    issue_id=issue.issue_id,
                )

            return FixerResult(
                status=FixStatus.FIXED,
                description=(
                    f"Fixed table headers in {fixed_tables} table(s): "
                    f"{total_changes} scope attribute(s) added or corrected — review header relationships"
                ),
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to fix table headers: {exc}",
                issue_id=issue.issue_id,
            )


def _find_target_tables(soup: BeautifulSoup, issue: A11yIssue) -> list[Tag]:
    selector = issue.location.x_path if issue.location else None
    if selector:
        try:
            targets = [el for el in soup.select(selector) if isinstance(el, Tag)]
            # Selector may point to a td/th inside the table — walk up to the table
            tables: list[Tag] = []
            for el in targets:
                table = el if el.name == "table" else _find_ancestor_table(el)
                if table is not None and table not in tables:
                    tables.append(table)
            if tables:
                return tables
        except Exception:
            pass
    # Fallback: all tables in the document
    return [el for el in soup.find_all("table") if isinstance(el, Tag)]


def _find_ancestor_table(el: Tag) -> Tag | None:
    for parent in el.parents:
        if isinstance(parent, Tag) and parent.name == "table":
            return parent
    return None


def _fix_table(table: Tag) -> int:
    """
    Apply header fixes to a single table. Returns the number of changes made.

    Strategy:
    1. If the table has a <thead>, ensure every <th> in it has scope="col" and
       promote any bare <td> in the first header row to <th scope="col">.
    2. If there is no <thead> but the first <tr> contains only <th> elements,
       treat it as a column-header row and add scope="col" to each.
    3. For <th> elements outside the first header row (row headers), add scope="row"
       if no scope is present.
    4. Remove invalid headers="" attributes that reference non-existent IDs.
    """
    changes = 0

    thead = table.find("thead")
    tbody = table.find("tbody") or table  # fall back to the table itself if no tbody

    # ── Column headers ────────────────────────────────────────────────────────

    if isinstance(thead, Tag):
        first_header_row = thead.find("tr")
        if isinstance(first_header_row, Tag):
            for cell in first_header_row.find_all(["th", "td"]):
                if not isinstance(cell, Tag):
                    continue
                if cell.name == "td":
                    # Promote bare td to th with scope="col"
                    cell.name = "th"
                    cell["scope"] = "col"
                    changes += 1
                elif not cell.get("scope"):
                    cell["scope"] = "col"
                    changes += 1

        # Remaining thead rows: add scope="col" to any th lacking one
        for row in thead.find_all("tr"):
            if row is first_header_row:
                continue
            for th in row.find_all("th"):
                if isinstance(th, Tag) and not th.get("scope"):
                    th["scope"] = "col"
                    changes += 1

    else:
        # No <thead>: check if first row looks like a header row (all th, or first cell is th)
        all_rows = table.find_all("tr")
        first_row = all_rows[0] if all_rows else None
        if isinstance(first_row, Tag):
            cells = [c for c in first_row.find_all(["th", "td"]) if isinstance(c, Tag)]
            is_header_row = cells and all(c.name == "th" for c in cells)
            if is_header_row:
                for th in cells:
                    if not th.get("scope"):
                        th["scope"] = "col"
                        changes += 1

    # ── Row headers ───────────────────────────────────────────────────────────

    # Any <th> that is the first cell of a body row gets scope="row" if unscoped
    body_container = tbody if isinstance(tbody, Tag) else table
    for row in body_container.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        # Skip rows that belong to a thead
        if isinstance(thead, Tag) and _is_descendant(row, thead):
            continue
        row_cells = [c for c in row.find_all(["th", "td"]) if isinstance(c, Tag)]
        if row_cells and row_cells[0].name == "th" and not row_cells[0].get("scope"):
            row_cells[0]["scope"] = "row"
            changes += 1

    # ── Orphaned headers="" attributes ────────────────────────────────────────

    all_ids = {el.get("id") for el in table.find_all(True) if isinstance(el, Tag) and el.get("id")}
    for cell in table.find_all(["td", "th"]):
        if not isinstance(cell, Tag):
            continue
        headers_attr = cell.get("headers", "").strip()
        if not headers_attr:
            continue
        referenced = set(headers_attr.split())
        valid = referenced & all_ids
        if not valid:
            del cell["headers"]
            changes += 1
        elif valid != referenced:
            cell["headers"] = " ".join(sorted(valid))
            changes += 1

    return changes


def _is_descendant(el: Tag, ancestor: Tag) -> bool:
    for parent in el.parents:
        if parent is ancestor:
            return True
    return False
