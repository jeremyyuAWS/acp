# Local / VPC stack — `docker compose`

Runs the **entire ACP platform** on one machine with no Azure and no MDK
dependency — exactly what a customer needs to run it inside their own VPC.

```bash
cd deploy/compose
cp .env.example .env          # edit secrets (see below)
docker compose up --build
```

| Service | URL | Notes |
|---------|-----|-------|
| `acp-app` | http://localhost:8077 | the platform (FastAPI + React SPA) |
| `grafana` | http://localhost:3000 | 10-panel ACP dashboard, anonymous viewer |
| `langfuse` | http://localhost:3001 | LLM tracing; self-register on first visit |
| `db` | localhost:5432 | Postgres 16 — `acpdb` + `langfusedb` |

## One build prerequisite

The `acp-app` image bundles **both analysis engines as compiled artifacts** (it does
not build them). The Python PDF engine now comes straight from the tracked tree
(`engine/pdf-analyser/`, ADR 0029) and needs nothing from you. Only the .NET CLI is a
compiled output, so before `docker compose up --build`:

1. **.NET Office CLI** — `spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll`
   must exist. Build it once:
   ```bash
   dotnet build -c Release spike/dotnet/AcpScan.Cli
   ```

If the CLI is missing the app still boots and HTML/PDF scans work; Office scans report
an engine-missing error per file.

Verify both engines actually loaded, rather than assuming — `/readyz` reports the PDF
engine directly, and a scan of the bundled corpus exercises all three analysers:

```bash
curl -s localhost:8077/readyz | jq .engines
```

## First-run Langfuse wiring (one time)

Langfuse keys don't exist until the service is up:

1. `docker compose up --build` and wait for all four to be healthy.
2. Open http://localhost:3001 → sign up → create a project.
3. Project settings → API keys → copy the `pk-...` and `sk-...`.
4. Paste them into `.env` as `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.
5. `docker compose up -d acp-app` to restart the app with tracing enabled.

Scans run before step 5 still work — they just aren't traced.

## Data persistence

Postgres data lives in the `acp-db` named volume. `docker compose down` keeps it;
`docker compose down -v` wipes it (fresh databases on next up).

## Production hardening (before a real customer deploy)

- Replace the dev passwords in `.env` with secrets from your vault.
- Put a TLS-terminating reverse proxy in front (`acp-app` and `grafana` speak plain
  HTTP).
- For high trace volume, move Langfuse to v3 (adds ClickHouse + Redis + S3/MinIO) —
  v2 here keeps the dependency surface to a single Postgres for easy standup.
- Lock Grafana down: set `GF_AUTH_ANONYMOUS_ENABLED=false` and provision real users
  if the dashboards shouldn't be open inside the VPC.
