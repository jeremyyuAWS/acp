#!/usr/bin/env bash
# Provision Grafana datasource + four ACP dashboards.
# All credentials come from environment — no defaults for secrets.
#
# Required env vars:
#   GRAFANA_URL   https://acp-grafana.<env>.azurecontainerapps.io
#   GRAFANA_USER  admin
#   GRAFANA_PASS  <grafana admin password>
#   PG_HOST       <postgres fqdn>
#   PG_USER       <postgres admin user>
#   PG_PASS       <postgres admin password>
#   PG_DB         acpdb
#
# Usage: source .env.grafana && bash scripts/provision_grafana.sh
set -euo pipefail

: "${GRAFANA_URL:?GRAFANA_URL required}"
: "${GRAFANA_USER:?GRAFANA_USER required}"
: "${GRAFANA_PASS:?GRAFANA_PASS required}"
: "${PG_HOST:?PG_HOST required}"
: "${PG_USER:?PG_USER required}"
: "${PG_PASS:?PG_PASS required}"
: "${PG_DB:?PG_DB required}"

AUTH="$GRAFANA_USER:$GRAFANA_PASS"
echo "== Grafana provisioning → $GRAFANA_URL =="

# Wait for Grafana to be ready
for i in $(seq 1 24); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$GRAFANA_URL/api/health" 2>/dev/null || echo 000)
  [ "$code" = "200" ] && { echo "  Grafana ready"; break; }
  echo "  waiting ($i/24) — status $code"
  sleep 5
done

echo "== 1/2  datasource =="
curl -sf -u "$AUTH" -X POST "$GRAFANA_URL/api/datasources" \
  -H 'Content-Type: application/json' \
  -d "{
    \"name\": \"ACP Postgres\",
    \"type\": \"postgres\",
    \"url\": \"${PG_HOST}:5432\",
    \"database\": \"${PG_DB}\",
    \"user\": \"${PG_USER}\",
    \"secureJsonData\": {\"password\": \"${PG_PASS}\"},
    \"jsonData\": {\"sslmode\": \"require\", \"postgresVersion\": 1600},
    \"access\": \"proxy\",
    \"isDefault\": true
  }" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  id:', d.get('datasource',{}).get('id') or d.get('id','?'))"

DS_UID=$(curl -sf -u "$AUTH" "$GRAFANA_URL/api/datasources/name/ACP%20Postgres" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('uid',''))")
echo "  datasource uid: $DS_UID"

echo "== 2/2  dashboards =="

post_dashboard() {
  local title="$1" panels="$2"
  curl -sf -u "$AUTH" -X POST "$GRAFANA_URL/api/dashboards/db" \
    -H 'Content-Type: application/json' \
    -d "{
      \"dashboard\": {
        \"title\": \"$title\", \"uid\": null, \"timezone\": \"browser\",
        \"refresh\": \"30s\", \"time\": {\"from\": \"now-30d\", \"to\": \"now\"},
        \"panels\": $panels
      },
      \"overwrite\": true, \"folderTitle\": \"ACP\"
    }" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  created:', d.get('title','?'), '→', d.get('url','?'))"
}

# ── Dashboard 1: Scan Overview ────────────────────────────────────────────────
post_dashboard "ACP — Scan Overview" "[
  {\"id\":1,\"type\":\"timeseries\",\"title\":\"Files scanned per run\",
   \"gridPos\":{\"x\":0,\"y\":0,\"w\":12,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT completed_at::timestamptz AS time, files AS \\\"files scanned\\\" FROM scan_runs ORDER BY 1\",\"format\":\"time_series\",\"refId\":\"A\"}]},
  {\"id\":2,\"type\":\"timeseries\",\"title\":\"Average compliance score\",
   \"gridPos\":{\"x\":12,\"y\":0,\"w\":12,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT completed_at::timestamptz AS time, avg_score AS \\\"avg score\\\" FROM scan_runs ORDER BY 1\",\"format\":\"time_series\",\"refId\":\"A\"}]},
  {\"id\":3,\"type\":\"stat\",\"title\":\"Total scans\",
   \"gridPos\":{\"x\":0,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM scan_runs\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":4,\"type\":\"stat\",\"title\":\"Total files\",
   \"gridPos\":{\"x\":6,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COALESCE(SUM(files),0) AS value FROM scan_runs\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":5,\"type\":\"stat\",\"title\":\"Certifiable files\",
   \"gridPos\":{\"x\":12,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COALESCE(SUM(certifiable),0) AS value FROM scan_runs\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":6,\"type\":\"stat\",\"title\":\"Overall avg score\",
   \"gridPos\":{\"x\":18,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT ROUND(AVG(avg_score)) AS value FROM scan_runs WHERE avg_score IS NOT NULL\",\"format\":\"table\",\"refId\":\"A\"}]}
]"

# ── Dashboard 2: WCAG Breakdown ───────────────────────────────────────────────
post_dashboard "ACP — WCAG Breakdown" "[
  {\"id\":1,\"type\":\"barchart\",\"title\":\"Issues by WCAG SC (top 20)\",
   \"gridPos\":{\"x\":0,\"y\":0,\"w\":24,\"h\":10},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"options\":{\"xField\":\"wcag\"},
   \"targets\":[{\"rawSql\":\"SELECT wcag, COUNT(*) AS issues FROM issue_records GROUP BY wcag ORDER BY issues DESC LIMIT 20\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":2,\"type\":\"barchart\",\"title\":\"Issues by severity\",
   \"gridPos\":{\"x\":0,\"y\":10,\"w\":12,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"options\":{\"xField\":\"severity\"},
   \"targets\":[{\"rawSql\":\"SELECT severity, COUNT(*) AS count FROM issue_records GROUP BY severity ORDER BY count DESC\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":3,\"type\":\"piechart\",\"title\":\"File status distribution\",
   \"gridPos\":{\"x\":12,\"y\":10,\"w\":12,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT status, COUNT(*) AS count FROM file_records GROUP BY status\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":4,\"type\":\"table\",\"title\":\"Rule PASS/FAIL/SKIP rates\",
   \"gridPos\":{\"x\":0,\"y\":18,\"w\":24,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT rule_id, rule_name, level, COUNT(*) FILTER (WHERE outcome='PASS') AS pass, COUNT(*) FILTER (WHERE outcome='FAIL') AS fail, COUNT(*) FILTER (WHERE outcome='SKIP') AS skip, SUM(finding_count) AS total_findings FROM scan_rule_traces GROUP BY rule_id, rule_name, level ORDER BY fail DESC\",\"format\":\"table\",\"refId\":\"A\"}]}
]"

# ── Dashboard 3: HITL Queue ───────────────────────────────────────────────────
post_dashboard "ACP — HITL Queue" "[
  {\"id\":1,\"type\":\"timeseries\",\"title\":\"HITL items created over time\",
   \"gridPos\":{\"x\":0,\"y\":0,\"w\":24,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT created_at::timestamptz AS time, 1 AS \\\"item\\\" FROM hitl_queue ORDER BY 1\",\"format\":\"time_series\",\"refId\":\"A\"}]},
  {\"id\":2,\"type\":\"stat\",\"title\":\"Pending\",
   \"gridPos\":{\"x\":0,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM hitl_queue WHERE status='pending'\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":3,\"type\":\"stat\",\"title\":\"Approved\",
   \"gridPos\":{\"x\":6,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM hitl_queue WHERE status='approved'\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":4,\"type\":\"stat\",\"title\":\"Rejected\",
   \"gridPos\":{\"x\":12,\"y\":8,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM hitl_queue WHERE status='rejected'\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":5,\"type\":\"table\",\"title\":\"Recent HITL items\",
   \"gridPos\":{\"x\":0,\"y\":12,\"w\":24,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT created_at, file, rule_name, finding_count, status, reviewer_note FROM hitl_queue ORDER BY created_at DESC LIMIT 50\",\"format\":\"table\",\"refId\":\"A\"}]}
]"

# ── Dashboard 4: Remediation ──────────────────────────────────────────────────
post_dashboard "ACP — Remediation" "[
  {\"id\":1,\"type\":\"stat\",\"title\":\"Files remediated\",
   \"gridPos\":{\"x\":0,\"y\":0,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM file_records WHERE remediated_at IS NOT NULL\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":2,\"type\":\"stat\",\"title\":\"Saved to Drive\",
   \"gridPos\":{\"x\":6,\"y\":0,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM file_records WHERE drive_write_url IS NOT NULL\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":3,\"type\":\"stat\",\"title\":\"Drive-sourced files\",
   \"gridPos\":{\"x\":12,\"y\":0,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT COUNT(*) AS value FROM file_records WHERE drive_file_id IS NOT NULL\",\"format\":\"table\",\"refId\":\"A\"}]},
  {\"id\":4,\"type\":\"stat\",\"title\":\"Remediation rate\",
   \"gridPos\":{\"x\":18,\"y\":0,\"w\":6,\"h\":4},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE remediated_at IS NOT NULL) / NULLIF(COUNT(*),0)) AS value FROM file_records\",\"format\":\"table\",\"refId\":\"A\"}],
   \"fieldConfig\":{\"defaults\":{\"unit\":\"percent\"}}},
  {\"id\":5,\"type\":\"timeseries\",\"title\":\"Remediation events over time\",
   \"gridPos\":{\"x\":0,\"y\":4,\"w\":24,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT remediated_at::timestamptz AS time, COUNT(*) AS remediations FROM file_records WHERE remediated_at IS NOT NULL GROUP BY 1 ORDER BY 1\",\"format\":\"time_series\",\"refId\":\"A\"}]},
  {\"id\":6,\"type\":\"table\",\"title\":\"Recently remediated files\",
   \"gridPos\":{\"x\":0,\"y\":12,\"w\":24,\"h\":8},\"datasource\":{\"uid\":\"$DS_UID\"},
   \"targets\":[{\"rawSql\":\"SELECT file, engine, status, score, remediated_at, drive_write_url FROM file_records WHERE remediated_at IS NOT NULL ORDER BY remediated_at DESC LIMIT 50\",\"format\":\"table\",\"refId\":\"A\"}]}
]"

echo ""
echo "== done =="
echo "   Grafana:    $GRAFANA_URL"
echo "   Datasource: $DS_UID"
echo "   Dashboards: Scan Overview · WCAG Breakdown · HITL Queue · Remediation"
