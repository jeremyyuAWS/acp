#!/bin/sh
# Derive Grafana's datasource variables from a Postgres DSN, then hand over to Grafana.
#
# WHY THIS EXISTS. provisioning/datasources/acp-postgres.yaml needs FOUR separate values — url,
# database, user, password — because that is the shape of a Grafana datasource file. Grafana's
# provisioning only substitutes $VAR / ${VAR}; it cannot split a connection string. So something
# has to do the splitting, and until now that something was `deploy/public/deploy.sh`, which
# parsed DATABASE_URL with four sed expressions and passed the parts in as container environment
# variables — including the password, in plaintext, in the app's stored configuration.
#
# That works, and it makes every OTHER deployment path reimplement the same parse. The Helm chart
# has one `database-url` secret and no way to split it: Kubernetes can interpolate whole env vars
# into each other, not substrings of them. Doing it here means the knowledge lives once, beside
# the file whose format demands it, and a caller only has to supply the DSN it already has.
#
# ONLY FILLS WHAT IS MISSING. If ACP_GRAFANA_PG_* are already set — Compose sets them explicitly,
# and deploy.sh still passes them — they are left exactly as they are. This is additive: no
# existing caller changes behaviour, and a caller that supplies both a DSN and the parts keeps the
# parts.
#
# `exec /run.sh "$@"` — the base image's entrypoint, read from the registry config of
# grafana/grafana:11.6.0 rather than assumed (Entrypoint ["/run.sh"], User 472).
#
# ACP_GRAFANA_ENTRYPOINT exists so the parsing above can be tested without a Grafana: the test
# points it at `env` and reads the four variables back. It is not a configuration knob — nothing
# sets it in any deployment path — and defaulting it to /run.sh means forgetting it changes
# nothing.
set -e

if [ -n "${DATABASE_URL:-}" ]; then
    # postgresql://user:pass@host[:port]/db[?params]
    #
    # Anchored on the LAST '@' and the FIRST '/' after it, because a password may contain '@' and
    # a query string may contain '/'. deploy.sh's version is not anchored that way; it is left
    # alone here rather than changed as a side effect of this file.
    _rest="${DATABASE_URL#*://}"
    _creds="${_rest%@*}"
    _hostpart="${_rest##*@}"

    [ -n "${ACP_GRAFANA_PG_USER:-}" ] || ACP_GRAFANA_PG_USER="${_creds%%:*}"
    [ -n "${ACP_GRAFANA_PG_PASS:-}" ] || ACP_GRAFANA_PG_PASS="${_creds#*:}"
    [ -n "${ACP_GRAFANA_PG_HOST:-}" ] || ACP_GRAFANA_PG_HOST="${_hostpart%%/*}"
    if [ -z "${ACP_GRAFANA_PG_DB:-}" ]; then
        _db="${_hostpart#*/}"
        ACP_GRAFANA_PG_DB="${_db%%\?*}"
    fi

    export ACP_GRAFANA_PG_USER ACP_GRAFANA_PG_PASS ACP_GRAFANA_PG_HOST ACP_GRAFANA_PG_DB
    unset _rest _creds _hostpart _db
fi

exec "${ACP_GRAFANA_ENTRYPOINT:-/run.sh}" "$@"
