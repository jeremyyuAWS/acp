-- Postgres runs this once on first init (against the default acpdb).
-- Create the second database Langfuse needs; acpdb is created by POSTGRES_DB.
SELECT 'CREATE DATABASE langfusedb'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfusedb')\gexec
