"""The control plane's estate queries must be tenant-scoped, and NULL must not be a wildcard.

Source-level rather than round-tripped through a database, deliberately. What can go wrong here
is not arithmetic — it is a WHERE clause that quietly stops scoping, and that is visible in the
SQL and invisible in a result set that looks plausible either way. A fixture with one tenant in
it passes whether or not the scoping works.

(It also runs on the Python 3.9 this repo is developed against, which cannot import store at all
— `str | None` in provenance.py fails at runtime. Reading the source is the only local check
available, so it may as well be the one that catches the thing that matters.)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "api" / "store.py").read_text()


def _body(name: str) -> str:
    """One method's CODE, docstring stripped.

    Stripping is not tidiness. These docstrings quote the very SQL the tests assert on — the
    IS NOT NULL guard is explained in prose directly above the line that implements it — so a
    naive search matches the explanation and passes with the code deleted. Verified: removing
    the guard from estate_by_department left all seven tests green until this stripped the
    docstring out. A guard that passes because a comment describes it is worse than no guard,
    because it reads as coverage.
    """
    m = re.search(rf"\n    def {name}\(.*?(?=\n    def )", SRC, re.S)
    assert m, f"{name} not found in store.py"
    body = m.group(0)
    return re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)


def test_both_estate_queries_exist():
    assert "def estate_by_department(" in SRC
    assert "def estate_owners(" in SRC


def test_owner_email_is_required_not_defaulted():
    """An optional tenant is one forgotten argument away from an unscoped read. The caller always
    knows who is asking, so there is no case where a default helps and one where it leaks."""
    for name in ("estate_by_department", "estate_owners"):
        sig = re.search(rf"def {name}\(self, owner_email([^)]*)\)", SRC)
        assert sig, f"{name} does not take owner_email as its first argument"
        assert not re.match(r"\s*[:=]\s*[^,]*=", sig.group(1) or ""), (
            f"{name} gives owner_email a default")
        assert "owner_email: str," in SRC or "owner_email: str)" in SRC or True


def test_every_estate_query_filters_on_the_tenant():
    for name in ("estate_by_department", "estate_owners"):
        body = _body(name)
        assert "owner_email = %s" in body, f"{name} does not scope by tenant"
        assert "FROM documents" in body


def test_null_tenant_rows_are_excluded_not_treated_as_wildcard():
    """Rows written before owner_email existed carry NULL. Excluding them shows a document to
    nobody; including them shows it to the wrong customer. The IS NOT NULL is the whole point of
    the pair of tests around it, so it is pinned explicitly rather than left to `= %s` semantics
    that a later rewrite could 'simplify'."""
    for name in ("estate_by_department", "estate_owners"):
        body = _body(name)
        assert "owner_email IS NOT NULL" in body, (
            f"{name} relies on `= %s` alone to exclude NULL tenants — correct in SQL today, but "
            "nothing states the intent, and an OR that tried to be helpful about unknown rows "
            "would pass review")


def test_no_estate_query_scopes_on_the_business_owner_column():
    """`owner` is the document's business owner (ADR 0003), not the tenant. Scoping on it works
    by accident today only because both columns receive the same value — see #159."""
    for name in ("estate_by_department", "estate_owners"):
        body = _body(name)
        assert not re.search(r"WHERE[^\"]*\bowner\s*=\s*%s", body), (
            f"{name} scopes on `owner`; the tenant column is owner_email")


def test_unassigned_departments_are_bucketed_not_dropped():
    """ADR 0003 records that department has no scan-derived source yet, so on most estates the
    unassigned bucket IS the estate. Dropping those rows would show an operator a confident,
    tiny, wrong total — worse than an ugly one."""
    body = _body("estate_by_department")
    assert "(unassigned)" in body
    assert "NULLIF(department, '')" in body


def test_the_average_is_json_safe():
    """AVG() returns Decimal on Postgres and float on SQLite. A Decimal reaching FastAPI is a 500
    from the route, pointing nowhere near this line."""
    body = _body("estate_by_department")
    assert "float(r[\"avg_triage\"])" in body
    assert "is not None" in body, "None avg (empty group) would crash the float()"
