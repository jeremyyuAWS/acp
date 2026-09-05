"""Grafana's datasource variables, derived from a DSN — run as the real shell script.

WHY THIS IS A SHELL TEST AND NOT A PYTHON REIMPLEMENTATION. The thing that ships is
`deploy/grafana/acp-entrypoint.sh`, and a second implementation of its parsing in Python would
pass while the shipped one was wrong — which is the whole failure mode. The script is executed
here, with `ACP_GRAFANA_ENTRYPOINT` pointed at `env` instead of Grafana's `/run.sh`, and the
variables are read back out of the environment it hands over.

WHAT MADE THIS WORTH TESTING RATHER THAN EYEBALLING. `deploy/public/deploy.sh` has done the same
parse since the Grafana app was first deployed, with four sed expressions:

    _PG_USER=... 's|.*://\\([^:]*\\):.*|\\1|'
    _PG_PASS=... 's|.*://[^:]*:\\([^@]*\\)@.*|\\1|'
    _PG_HOST=... 's|.*@\\([^/]*\\)/.*|\\1|'
    _PG_DB=...   's|.*/\\([^?]*\\).*|\\1|'

`[^@]*` stops at the FIRST '@', so a password containing '@' — which a generated Postgres
password may — is truncated to whatever precedes it. (The host survives, because `.*@` is greedy;
that half was checked rather than assumed.) This one anchors on the last '@' and the first '/'
after it. The cases below are the ones that distinguish the two.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "grafana" / "acp-entrypoint.sh"

KEYS = ("ACP_GRAFANA_PG_HOST", "ACP_GRAFANA_PG_DB",
        "ACP_GRAFANA_PG_USER", "ACP_GRAFANA_PG_PASS")


def run(env: dict[str, str]) -> dict[str, str]:
    """The script, handing over to `env` rather than Grafana. Returns what it exported."""
    proc = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, timeout=30,
                          env={"PATH": "/usr/bin:/bin",
                               "ACP_GRAFANA_ENTRYPOINT": "/usr/bin/env", **env})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k in KEYS:
                out[k] = v
    return out


def test_the_script_is_executable_and_hands_over():
    """The premise. If it did not exec, every assertion below would be about an empty dict."""
    assert SCRIPT.is_file()
    assert run({"DATABASE_URL": "postgresql://u:p@h:5432/d"}), "the script exported nothing"


def test_an_ordinary_dsn_splits_into_four():
    got = run({"DATABASE_URL": "postgresql://acpadmin:s3cret@db.example.org:5432/acpdb"})
    assert got == {"ACP_GRAFANA_PG_USER": "acpadmin",
                   "ACP_GRAFANA_PG_PASS": "s3cret",
                   "ACP_GRAFANA_PG_HOST": "db.example.org:5432",
                   "ACP_GRAFANA_PG_DB": "acpdb"}


def test_a_query_string_does_not_become_part_of_the_database_name():
    """`?sslmode=require` is on the production DSN. A database called `acpdb?sslmode=require`
    fails to connect, and the datasource reports it as an authentication problem."""
    got = run({"DATABASE_URL":
               "postgresql://acpadmin:s3cret@db.example.org:5432/acpdb?sslmode=require"})
    assert got["ACP_GRAFANA_PG_DB"] == "acpdb"


def test_a_password_containing_an_at_sign_survives():
    """THE CASE THAT SEPARATES THIS FROM deploy.sh's parse, MEASURED RATHER THAN REASONED.

    Running deploy.sh's four sed expressions against
    `postgresql://acpadmin:p@ss@db.example.org:5432/acpdb` gives:

        USER acpadmin   PASS p   HOST db.example.org:5432   DB acpdb

    So exactly ONE field is wrong: the password truncates at the first '@'. The host is fine —
    `.*@` is greedy and lands on the last '@' — which the first draft of this docstring claimed
    was broken too, on reasoning rather than a run. The failure that produces is a Grafana that
    cannot authenticate, reported as "the dashboards are empty", with a password that looks
    almost right anywhere it is echoed.

    Latent rather than live: it only bites when the Postgres password contains '@', which this
    repository cannot see. deploy.sh is deliberately not changed here."""
    got = run({"DATABASE_URL": "postgresql://acpadmin:p@ss@db.example.org:5432/acpdb"})
    assert got["ACP_GRAFANA_PG_PASS"] == "p@ss"
    assert got["ACP_GRAFANA_PG_HOST"] == "db.example.org:5432"


def test_a_password_containing_a_slash_survives():
    got = run({"DATABASE_URL": "postgresql://acpadmin:a/b@db.example.org/acpdb"})
    assert got["ACP_GRAFANA_PG_PASS"] == "a/b"
    assert got["ACP_GRAFANA_PG_HOST"] == "db.example.org"
    assert got["ACP_GRAFANA_PG_DB"] == "acpdb"


def test_a_host_without_a_port_is_fine():
    got = run({"DATABASE_URL": "postgresql://u:p@db.example.org/acpdb"})
    assert got["ACP_GRAFANA_PG_HOST"] == "db.example.org"


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_both_postgres_schemes_parse(scheme):
    """SQLAlchemy and psycopg accept both spellings and ACP's own DATABASE_URL has used each."""
    got = run({"DATABASE_URL": f"{scheme}://u:p@h/d"})
    assert got["ACP_GRAFANA_PG_DB"] == "d"


# ── what it must NOT do ───────────────────────────────────────────────────────

def test_explicit_variables_win_over_the_dsn():
    """ADDITIVE, and this is what makes it safe to ship. Compose sets the four directly and
    deploy.sh still passes them; if the DSN overrode them, adding this script would silently
    repoint two working deployments at whatever DATABASE_URL happened to say."""
    got = run({"DATABASE_URL": "postgresql://dsnuser:dsnpass@dsnhost/dsndb",
               "ACP_GRAFANA_PG_HOST": "explicit-host",
               "ACP_GRAFANA_PG_DB": "explicit-db",
               "ACP_GRAFANA_PG_USER": "explicit-user",
               "ACP_GRAFANA_PG_PASS": "explicit-pass"})
    assert got == {"ACP_GRAFANA_PG_HOST": "explicit-host",
                   "ACP_GRAFANA_PG_DB": "explicit-db",
                   "ACP_GRAFANA_PG_USER": "explicit-user",
                   "ACP_GRAFANA_PG_PASS": "explicit-pass"}


def test_a_partially_supplied_environment_is_completed_not_replaced():
    """The mixed case, which is the one a hand-written override produces: an operator pins the
    host and leaves the rest to the DSN."""
    got = run({"DATABASE_URL": "postgresql://dsnuser:dsnpass@dsnhost/dsndb",
               "ACP_GRAFANA_PG_HOST": "pinned-host"})
    assert got["ACP_GRAFANA_PG_HOST"] == "pinned-host"
    assert got["ACP_GRAFANA_PG_USER"] == "dsnuser"


def test_no_dsn_sets_nothing_rather_than_empty_strings():
    """Empty is worse than absent here: Grafana substitutes ${VAR} with the empty string and
    provisions a datasource with four blank fields, which starts cleanly and fails at query
    time. Leaving them unset at least leaves the ${VAR} text visible in the datasource."""
    assert run({}) == {}


def test_the_deploy_script_still_passes_the_four_explicitly():
    """A guard on the OTHER caller. This script is additive only while deploy.sh keeps setting
    the four; if somebody deletes them there on the strength of this file, production starts
    depending on a parse that has to be right rather than on one that already is."""
    deploy = (SCRIPT.parents[2] / "deploy" / "public" / "deploy.sh").read_text(encoding="utf-8")
    for key in KEYS:
        assert key in deploy, f"deploy.sh no longer sets {key}"
