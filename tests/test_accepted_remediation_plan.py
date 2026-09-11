from accepted_remediation_plan import read_accepted_plan
from test_ai_run_policy import seed, enqueue


def test_reads_frozen_choices_not_current_defaults(isolated_store):
    s = isolated_store
    seed(s)
    run = enqueue(s)
    s.set_setting('remediation_rule_based', '0')
    result = read_accepted_plan(s, 'owner', 'scan', run['batch_id'])
    assert result['policy']['rule_based'] == 2
    assert result['policy']['ai_budget_usd'] == '0.10'
    assert 'snapshot_id' not in result['policy']
    assert read_accepted_plan(s, 'other', 'scan', run['batch_id']) is None
    assert read_accepted_plan(s, 'owner', 'other', run['batch_id']) is None


def test_rules_only_without_budget_still_has_saved_choices(isolated_store):
    seed(isolated_store)
    run = enqueue(isolated_store, ai=0, amount=None)
    assert read_accepted_plan(isolated_store, 'owner', 'scan', run['batch_id'])['policy'] == {'ai': 0, 'rule_based': 2}


def test_native_pdf_selection_is_saved_in_run_context_and_summary(isolated_store):
    from ai_run_policy import run_context
    from remediation_impact_settings import snapshot_impact_policy
    store = isolated_store
    seed(store)
    policy = snapshot_impact_policy(store, 'owner', {
        'rule_based': 2, 'ai': 1, 'ai_zone': 'any', 'ai_budget_usd': '1.00',
        'document_wide_ai': True, 'document_wide_input_mode': 'native_pdf',
    })
    run = store.enqueue_stage_batch('scan', 'remediate', 'remediate_file', [{
        'owner': 'owner', 'scan_id': 'scan', 'file': 'a.pdf',
        'remediation_impact_policy': policy,
    }], snapshot_id='snapshot', request_fingerprint='native-pdf')
    job = store.get_job(run['job_ids'][0])
    with run_context(store, job['payload'], job) as ctx:
        assert ctx.policy['document_wide_input_mode'] == 'native_pdf'
    assert read_accepted_plan(store, 'owner', 'scan', run['batch_id'])['policy']['document_wide_input_mode'] == 'native_pdf'
