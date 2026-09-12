"""Read only the choices frozen into this owner's accepted remediation jobs."""
import json

_KEYS = frozenset({'rule_based', 'ai', 'ai_zone', 'ai_budget_usd', 'auto_approve_ai',
                   'document_wide_ai', 'document_wide_input_mode', 'document_wide_model_profile', 'generation_chain', 'ai_review'})

def read_accepted_plan(store, owner, scan_id, run_id):
    stage = store.get_stage_execution(run_id, owner=owner)
    if not stage or stage.get('scan_id') != scan_id or stage.get('stage') != 'remediate':
        return None
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT payload FROM jobs WHERE scan_id=%s AND batch_id=%s AND type='remediate_file'", (scan_id, run_id))
        rows = store._db.fetchall(cur)
    policies = []
    for row in rows:
        try:
            payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            saved = payload.get('remediation_impact_policy')
            if not isinstance(saved, dict):
                continue
            policies.append({k: v for k, v in saved.items() if k in _KEYS})
        except (ValueError, TypeError, AttributeError):
            continue
    policy = policies[0] if policies and all(p == policies[0] for p in policies) else None
    return {'scan_id': scan_id, 'run_id': run_id, 'policy': policy,
            'accepted_at': stage.get('created_at'),
            'available': policy is not None}
