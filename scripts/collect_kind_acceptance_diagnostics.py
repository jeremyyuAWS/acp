"""Read-only, allow-listed evidence before the restore drill replaces app pods."""
import argparse
import json
from pathlib import Path
import re
import subprocess

APP_SELECTOR = 'app.kubernetes.io/instance=acp,app.kubernetes.io/component in (api,worker)'
EVENTS = {'job.claim', 'job.done', 'job.failed', 'job.retry', 'job.cancelled',
          'job.no_handler', 'stage.enter', 'stage.exit'}
SAFE_ID = re.compile(r'^[a-f0-9]{8,64}$')

DB_READ = r'''
import json, os
import psycopg2
from psycopg2.extras import RealDictCursor
from routes.system import _bundle_leaks, _secret_env_values
def category(value):
    text=str(value or '').lower()
    for name, terms in [('database_lock',('database is locked','deadlock','lock timeout','lock wait')),
                        ('connection_failure',('connection','connect','pool')),
                        ('timeout',('timeout','timed out')),('access_denied',('permission','denied','unauthorized')),
                        ('unavailable_input',('missing','not found','unavailable'))]:
        if any(term in text for term in terms): return name
    return 'other' if text else None
rows=[]
waits=[]
connection=None
available=False
try:
    connection=psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=5,
        options='-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=5000',
        application_name='acp-kind-diagnostics')
    connection.set_session(readonly=True,autocommit=False)
    with connection.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT id,type,status,attempts,max_attempts,phase,last_error FROM jobs ORDER BY created_at DESC LIMIT 100')
        rows=cur.fetchall()
        cur.execute("SELECT wait_event,COUNT(*) AS count FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' GROUP BY wait_event")
        waits=cur.fetchall()
    available=True
except Exception:
    rows=[]
    waits=[]
finally:
    if connection is not None:
        connection.close()
jobs=[]
for row in rows:
    phase=str(row.get('phase') or '').lower()
    stage=next((name for name in ('download','remediat','verif','publish','assess','scan','reconcil') if name in phase),'other' if phase else None)
    jobs.append({'id':row['id'],'type':row['type'],'status':row['status'],
        'attempts':row['attempts'],'max_attempts':row['max_attempts'],
        'stage_category':stage,'error_category':category(row.get('last_error'))})
bundle={'jobs':jobs,'redacted':True,'collection_status':'collected' if available else 'unavailable'}
bundle['database_lock_waits']=[{'kind':row['wait_event'] if row['wait_event'] in ('transactionid','relation','tuple','virtualxid','object','advisory') else 'other',
                              'count':row['count']} for row in waits]
if _bundle_leaks(bundle,_secret_env_values()):
    bundle={'redacted':True,'collection_status':'refused_secret_match'}
print('ACP_KIND_DIAGNOSTICS='+json.dumps(bundle))
'''


def safe_events(text):
    """Drop arbitrary logs entirely; retain only structural job diagnostics."""
    output = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict) or row.get('event') not in EVENTS:
            continue
        safe = {'event': row['event']}
        for key in ('job_id', 'scan_id'):
            if SAFE_ID.fullmatch(str(row.get(key, ''))):
                safe[key] = row[key]
        for key in ('attempt', 'max_attempts', 'ts'):
            if type(row.get(key)) in (int, float):
                safe[key] = row[key]
        if row.get('status') in ('queued', 'running', 'done', 'dead', 'cancelled', 'missing', 'unread'):
            safe['status'] = row['status']
        output.append(safe)
    return output


def command(args, *, runner=subprocess.run):
    try:
        result = runner(args, capture_output=True, text=True, timeout=45)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def collect(namespace, *, runner=subprocess.run):
    raw = command(['kubectl', '-n', namespace, 'get', 'pods', '-l', APP_SELECTOR, '-o', 'json'], runner=runner)
    try:
        pods = json.loads(raw).get('items', [])
    except (ValueError, AttributeError):
        pods = []
    evidence = {'redacted': True, 'pod_count': len(pods), 'workloads': [], 'database': {'collection_status': 'unavailable'}}
    for pod in pods:
        name = pod.get('metadata', {}).get('name')
        component = pod.get('metadata', {}).get('labels', {}).get('app.kubernetes.io/component')
        if not name or component not in ('api', 'worker'):
            continue
        statuses = pod.get('status', {}).get('containerStatuses', [])
        logs = command(['kubectl', '-n', namespace, 'logs', name, '--all-containers', '--tail=200'], runner=runner)
        evidence['workloads'].append({'component': component,
            'ready': bool(statuses) and all(s.get('ready') for s in statuses),
            'restarts': sum(s.get('restartCount', 0) for s in statuses), 'events': safe_events(logs)})
        if component == 'api' and evidence['database'].get('collection_status') == 'unavailable':
            result = command(['kubectl', '-n', namespace, 'exec', name, '--', 'python', '-c', DB_READ], runner=runner)
            for line in result.splitlines():
                if line.startswith('ACP_KIND_DIAGNOSTICS='):
                    try:
                        evidence['database'] = json.loads(line.split('=', 1)[1])
                    except ValueError:
                        pass
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collect(args.namespace), indent=2) + '\n')
