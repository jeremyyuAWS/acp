-- Create a read-only Postgres role for Power BI DirectQuery.
--
-- Run once as a database superuser:
--   psql "$DATABASE_URL" -f scripts/create_powerbi_role.sql
--
-- Then configure the Power BI data source with:
--   Host / Port  : your Postgres host
--   Database     : acp  (or whatever DATABASE_URL names)
--   Username     : powerbi_ro
--   Password     : <set below, or via ALTER ROLE after creation>
--   DirectQuery  : enabled
--
-- The role can SELECT from the three compliance views only.
-- It cannot read underlying tables, write anything, or log in as a superuser.
-- Re-running this script is idempotent.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'powerbi_ro') THEN
        CREATE ROLE powerbi_ro
            LOGIN
            PASSWORD 'changeme'   -- change before production use
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
    END IF;
END
$$;

-- Allow the role to connect. Replace 'acp' with your actual database name
-- if DATABASE_URL points at a different one.
GRANT CONNECT ON DATABASE acp TO powerbi_ro;

GRANT USAGE ON SCHEMA public TO powerbi_ro;

-- Read access to the three Power BI views only — not to underlying tables.
GRANT SELECT ON vw_scan_summary    TO powerbi_ro;
GRANT SELECT ON vw_finding_detail  TO powerbi_ro;
GRANT SELECT ON vw_rule_coverage   TO powerbi_ro;

-- Revoke any accidental future table grants if default privileges change.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM powerbi_ro;
