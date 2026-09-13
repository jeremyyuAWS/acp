"""Settle only whole native-chart review rows already repaired and rechecked.

This records a deterministic result, never grants AI provenance, and never
shrinks a mixed image/chart finding count or changes a reviewer's decision.
"""
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone


def settle(store, job, scan_id, filename, original, corrected, verification):
    if not verification.cleared({'1.1.1'}) or not job.get('id'):
        return []
    import chart_data
    import proposals
    from remediation_run_insights import PROPOSAL_KEYS
    ext = Path(filename).suffix.lower()
    if ext not in {'.docx', '.pptx', '.xlsx'}:
        return []
    with zipfile.ZipFile(io.BytesIO(original)) as old, zipfile.ZipFile(io.BytesIO(corrected)) as new:
        old_parts = {n: old.read(n) for n in old.namelist()}
        new_parts = {n: new.read(n) for n in new.namelist()}
    parts = sorted(n for n in old_parts if chart_data._CHART_PART.match(n))
    if not parts or any(old_parts[n] != new_parts.get(n) for n in parts):
        return []
    # Charts may store only references into worksheet cells. Identical chart XML
    # does not establish that the plotted categories/values remained unchanged.
    # Compare the fully resolved original/current dataset before accepting the
    # already-written description as the repair for the assessed source.
    for part in parts:
        old_chart = chart_data.parse_chart_part(old_parts[part], old_parts, part)
        new_chart = chart_data.parse_chart_part(new_parts[part], new_parts, part)
        if old_chart is None or old_chart != new_chart:
            return []
    # Match against the exact proposer output for the assessed bytes; source labels
    # alone are insufficient authorization for a deterministic close-out.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ('source' + ext)
        path.write_bytes(original)
        expected = {p['locator']: p for p in proposals.propose_chart_datasheet(path, ext)}
    digest = hashlib.sha256(corrected).hexdigest()
    settled = []
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT j.batch_id,j.payload,s.owner_email,e.input_snapshot_id
          FROM jobs j JOIN scan_runs s ON s.id=j.scan_id
          JOIN stage_executions e ON e.execution_id=j.batch_id AND e.scan_id=j.scan_id
          WHERE j.id=%s AND j.scan_id=%s AND j.type='remediate_file'
          AND e.stage='remediate' AND e.is_current=1 AND e.cancel_requested_at IS NULL
          AND e.owner_email=s.owner_email AND e.state IN ('accepted','queued','processing')''', (job['id'], scan_id))
        execution = store._db.fetchone(cur)
        if not execution or execution['input_snapshot_id'] != store.remediation_source_revision(scan_id):
            return []
        payload = execution['payload']
        payload = json.loads(payload) if isinstance(payload, str) else payload
        if (payload.get('owner') != execution['owner_email'] or payload.get('file') != filename
                or payload.get('stage_execution_id') != execution['batch_id']):
            return []
        store._db.execute(cur, "SELECT corrected_sha256 FROM file_records WHERE scan_id=%s AND file=%s", (scan_id, filename))
        record = store._db.fetchone(cur)
        if not record or record['corrected_sha256'] != digest:
            return []
        store._db.execute(cur, "SELECT * FROM hitl_queue WHERE scan_id=%s AND file=%s AND rule_id='1.1.1' AND status='pending'", (scan_id, filename))
        rows = store._db.fetchall(cur)
        for row in rows:
            try:
                current = json.loads(row['proposals'] or '[]')
                snapshots = json.loads(row['proposal_snapshot_ids'] or '[]')
            except (ValueError, TypeError):
                continue
            if not current or row['finding_count'] != len(current) or len(snapshots) != len(current) or not all(snapshots):
                continue
            actual = []
            for index, proposal in enumerate(current):
                if not isinstance(proposal, dict) or proposal != expected.get(proposal.get('locator')):
                    break
                chart_index = int(proposal['locator'].split()[1]) - 1
                part = parts[chart_index]
                if not chart_data.has_exact_chart_data_alt(new_parts, ext, part):
                    break
                canonical = json.dumps({k:proposal[k] for k in PROPOSAL_KEYS if k in proposal},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
                store._db.execute(cur, '''SELECT proposal_sha256 FROM ai_proposal_snapshots WHERE snapshot_id=%s
                  AND owner_id=%s AND scan_id=%s AND run_id=%s AND item_id=%s AND file=%s
                  AND rule_id='1.1.1' AND proposal_index=%s''',
                  (snapshots[index],execution['owner_email'],scan_id,execution['batch_id'],row['id'],filename,index))
                snapshot=store._db.fetchone(cur)
                if not snapshot or snapshot['proposal_sha256'] != hashlib.sha256(canonical.encode()).hexdigest():
                    break
                chart = chart_data.parse_chart_part(new_parts[part],new_parts,part)
                actual.append({**proposal,'approved_value':chart_data.exact_numeric_chart_description(chart)})
            if len(actual) != len(current):
                continue
            store._db.execute(cur, '''UPDATE hitl_queue SET status='approved', applied=1, validated=1,
              proposals=%s, reviewer_note=%s, reviewed_at=%s, approved_source_revision=%s,
              approved_proposal_snapshot_ids=%s, approved_value_sha256=%s,
              decision_version=decision_version+1
              WHERE id=%s AND status='pending' AND decision_version=%s
              AND proposals IS NOT DISTINCT FROM %s AND proposal_snapshot_ids IS NOT DISTINCT FROM %s
              AND EXISTS(SELECT 1 FROM file_records f WHERE f.scan_id=%s AND f.file=%s AND f.corrected_sha256=%s)
              AND EXISTS(SELECT 1 FROM stage_executions e WHERE e.execution_id=%s AND e.scan_id=%s
                AND e.is_current=1 AND e.cancel_requested_at IS NULL AND e.input_snapshot_id=%s
                AND e.state IN ('accepted','queued','processing'))''',
              (json.dumps(actual),'Deterministic chart data alt written and confirmed by actual corrected-file recheck',datetime.now(timezone.utc).isoformat(),execution['input_snapshot_id'],
               json.dumps(snapshots,separators=(',',':')),hashlib.sha256(json.dumps([p['approved_value'] for p in actual],ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
               row['id'],row['decision_version'],row['proposals'],row['proposal_snapshot_ids'],scan_id,filename,digest,
               execution['batch_id'],scan_id,execution['input_snapshot_id']))
            if cur.rowcount:
                settled.append(row['id'])
    for item_id in settled:
        store.log_decision('system','native_chart.review_settled',scan_id=scan_id,file=filename,
                           rule_id='1.1.1',detail=json.dumps({'item_id':item_id,'source_sha256':hashlib.sha256(original).hexdigest(),'artifact_sha256':digest,'verification':'actual_corrected_file_recheck','approval_identity':'deterministic_chart_data'}))
    return settled
