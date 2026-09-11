from hashlib import sha256
from types import SimpleNamespace
import pytest
from store import _SQLiteAdapter
from ai_spending_budget import BudgetLedger
from ai_attempt_history import AttemptHistory
from ai_review_chain import SCHEMA as REVIEW_SCHEMA
from ai_run_policy import RUN_POLICY_SCHEMA
from remediation_contribution import SCHEMA as CONTRIBUTION_SCHEMA
from remediation_run_insights import SCHEMA, MAX_PROPOSAL_BYTES, capture_proposals, read_insights

OWNER = 'owner@example.test'
CTX = SimpleNamespace(owner_id=OWNER, run_id='run-1', scan_id='scan-1', file='one.pdf')

class Store:
    def __init__(self, db): self._db = db
    def get_stage_execution(self, run_id, owner=None):
        with self._db.cursor() as cur:
            self._db.execute(cur, 'SELECT * FROM stage_executions WHERE execution_id=%s AND owner_email=%s', (run_id, owner))
            return self._db.fetchone(cur)

@pytest.fixture
def store(tmp_path):
    db = _SQLiteAdapter(str(tmp_path / 'insights.db'))
    ledger = BudgetLedger(db); ledger.init_schema(); ledger.create_budget(OWNER, 'run-1', 100)
    history = AttemptHistory(db); history.init_schema()
    with db.cursor() as cur:
        db.execute(cur, RUN_POLICY_SCHEMA)
        for statement in SCHEMA + REVIEW_SCHEMA + CONTRIBUTION_SCHEMA[:2]:
            db.execute(cur, statement)
        db.execute(cur, 'CREATE TABLE stage_executions(execution_id TEXT PRIMARY KEY,owner_email TEXT,scan_id TEXT,stage TEXT)')
        db.execute(cur, 'INSERT INTO stage_executions VALUES(%s,%s,%s,%s)', ('run-1', OWNER, 'scan-1', 'remediate'))
        db.execute(cur, 'CREATE TABLE hitl_events(id TEXT,model_call_id TEXT,scan_id TEXT,file TEXT,rule_id TEXT,item_id TEXT,action TEXT,edited INT,proposal_snapshot_ids TEXT,created_at TEXT)')
        db.execute(cur, 'CREATE TABLE ai_validation_outcomes(id TEXT,model_call_id TEXT,scan_id TEXT,file TEXT,rule_id TEXT,item_id TEXT,outcome TEXT,detail TEXT,regressions TEXT,created_at TEXT)')
    return Store(db)

def link(store, *, attempt='first', purpose='draft', file='one.pdf', call='call-1'):
    history = AttemptHistory(store._db)
    history.begin(OWNER, 'scan-1', 'run-1', 'operation-' + attempt, attempt, file=file,
        input_sha256=sha256(b'input').hexdigest(), model='fixture-model', provider='fixture', purpose=purpose)
    with store._db.cursor() as cur:
        store._db.execute(cur, 'INSERT INTO ai_attempt_trace_links VALUES(%s,%s,%s,%s)', (OWNER, 'run-1', attempt, call))

def capture(store, proposals, ctx=CTX):
    with store._db.cursor() as cur:
        return capture_proposals(store._db, cur, ctx, scan_id='scan-1', file='one.pdf', rule_id='1.1.1', item_id='item-1', proposals=proposals)

def proposal(value='A useful description', call='call-1'):
    return dict(before='', proposed_value=value, locator='page-1/image-1', rationale='A visible tree',
                model='fixture-model', model_call_id=call, secret_prompt='NEVER RETAIN')

def test_saved_content_is_immutable_allowlisted_and_exactly_linked(store):
    link(store)
    first = capture(store, [proposal()])
    assert capture(store, [proposal()]) == first
    capture(store, [proposal('Another version')])
    result = read_insights(store, OWNER, 'scan-1', 'run-1')
    assert len(result['proposals']) == 2
    assert result['contribution'] == dict(unit='proposal_versions', draft=2, fallback=0, unattributed=0,
        total=2, complete=True, note='Saved proposal versions, not unique findings or verified fixes. Revisions may cover the same issue.')
    saved = result['proposals'][0]
    assert saved['proposal']['proposed_value'] == 'A useful description'
    assert 'secret_prompt' not in saved['proposal']
    assert saved['attempt_id'] == 'first'
    assert saved['source_excerpt_sha256']
    assert result['outcomes']['verified_fix_count'] is None
    assert result['estimate']['available'] is False
    assert result['batch_id'] == 'run-1'

def test_fallback_contribution_is_saved_versions_not_calls_or_findings(store):
    link(store, attempt='first')
    link(store, attempt='next', purpose='fallback', call='call-2')
    capture(store, [proposal(call='call-2')])
    result = read_insights(store, OWNER, 'scan-1', 'run-1')
    assert len(result['attempts']) == 2
    assert result['contribution']['draft'] == 0
    assert result['contribution']['fallback'] == 1

def test_file_and_trace_must_both_match_no_inferred_lineage(store):
    link(store, file='different.pdf')
    capture(store, [proposal()])
    result = read_insights(store, OWNER, 'scan-1', 'run-1')
    assert result['proposals'][0]['attempt_id'] is None
    assert result['contribution']['unattributed'] == 1

@pytest.mark.parametrize('owner,scan,run', [('other', 'scan-1', 'run-1'),
    (OWNER, 'other-scan', 'run-1'), (OWNER, 'scan-1', 'other-run'), ('', 'scan-1', 'run-1')])
def test_read_never_crosses_owner_scan_or_execution(store, owner, scan, run):
    with pytest.raises(PermissionError): read_insights(store, owner, scan, run)

def test_capture_rejects_other_owner_or_file_context(store):
    assert capture(store, [proposal()], SimpleNamespace(owner_id='other',run_id='run-1',scan_id='scan-1',file='one.pdf')) == []
    assert capture(store, [proposal()], SimpleNamespace(owner_id=OWNER,run_id='run-1',scan_id='scan-1',file='other.pdf')) == []
    assert read_insights(store, OWNER, 'scan-1', 'run-1')['proposals'] == []

def test_large_output_has_digest_and_explicit_retention_limit(store):
    capture(store, [proposal('x' * (MAX_PROPOSAL_BYTES + 1))])
    saved = read_insights(store, OWNER, 'scan-1', 'run-1')['proposals'][0]
    assert saved['proposal'] is None
    assert saved['retention'] == 'omitted_size_limit'
    assert len(saved['proposal_sha256']) == 64

def test_exact_call_events_do_not_verify_an_unproven_proposal_version(store):
    link(store); capture(store, [proposal()])
    db = store._db
    with db.cursor() as cur:
        for identity, call, file in [('exact', 'call-1', 'one.pdf'), ('wrong-call', 'other', 'one.pdf'), ('wrong-file','call-1','other.pdf')]:
            db.execute(cur, 'INSERT INTO ai_validation_outcomes VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (identity, call, 'scan-1', file, '1.1.1', 'item-1', 'verified', 'check passed', '[]', '2026-09-08'))
    result = read_insights(store, OWNER, 'scan-1', 'run-1')
    assert [row['id'] for row in result['proposals'][0]['validation_events']] == ['exact']
    assert result['proposals'][0]['version_verified'] is False
    assert result['outcomes']['verified_fix_count'] is None


def test_paging_bounds_output_but_keeps_full_run_contribution(store):
    link(store, attempt='first')
    link(store, attempt='second', purpose='fallback', call='call-2')
    link(store, attempt='third', purpose='fallback', call='call-3')
    capture(store, [proposal('first'), proposal('second', call='call-2'), proposal('third', call='call-3')])
    pages = [read_insights(store, OWNER, 'scan-1', 'run-1', offset=i, limit=1) for i in range(3)]
    assert all(len(page['attempts']) == len(page['proposals']) == 1 for page in pages)
    assert len({page['proposals'][0]['snapshot_id'] for page in pages}) == 3
    assert len({page['attempts'][0]['attempt_id'] for page in pages}) == 3
    assert [page['pagination']['has_more'] for page in pages] == [True, True, False]
    assert all(page['pagination']['total_attempts'] == page['pagination']['total_proposals'] == 3 for page in pages)
    assert all(page['contribution']['draft'] == 1 and page['contribution']['fallback'] == 2 for page in pages)
    assert all(page['contribution']['total'] == 3 and page['contribution']['complete'] for page in pages)
    beyond = read_insights(store, OWNER, 'scan-1', 'run-1', offset=10, limit=1)
    assert beyond['attempts'] == beyond['proposals'] == []
    assert beyond['contribution']['total'] == 3
    assert beyond['pagination']['has_more'] is False


@pytest.mark.parametrize('kwargs', [{'offset': -1}, {'offset': True}, {'offset': '0'},
    {'limit': 0}, {'limit': 201}, {'limit': True}, {'limit': '100'}])
def test_paging_rejects_invalid_limits(store, kwargs):
    with pytest.raises(ValueError):
        read_insights(store, OWNER, 'scan-1', 'run-1', **kwargs)


def set_policy(store, *, ai=None, ai_zone=None, ai_budget_usd=None):
    import json
    policy = {}
    if ai is not None: policy['ai'] = ai
    if ai_zone is not None: policy['ai_zone'] = ai_zone
    if ai_budget_usd is not None: policy['ai_budget_usd'] = ai_budget_usd
    with store._db.cursor() as cur:
        store._db.execute(cur, 'DELETE FROM ai_spending_run_policies WHERE owner_id=%s AND run_id=%s', (OWNER, 'run-1'))
        store._db.execute(cur, 'INSERT INTO ai_spending_run_policies VALUES(%s,%s,%s,%s)',
                          (OWNER, 'run-1', 'scan-1', json.dumps(policy)))


def approve(store, snapshot_id, *, action='approve', call='call-1'):
    with store._db.cursor() as cur:
        store._db.execute(cur, 'INSERT INTO hitl_events VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            ('event-' + snapshot_id, call, 'scan-1', 'one.pdf', '1.1.1', 'item-1', action, 0, '[]', '2026-09-08'))


def test_activity_summary_counts_attempts_by_model_and_applied_suggestions(store):
    link(store)
    saved = capture(store, [proposal()])
    approve(store, saved[0])
    result = read_insights(store, OWNER, 'scan-1', 'run-1')
    summary = result['activity_summary']
    assert summary['by_model'] == [{'provider': 'fixture', 'model': 'fixture-model', 'attempts': 1, 'completed': 0}]
    assert summary['attempted'] == 1
    assert summary['suggestions_generated'] == 1
    assert summary['suggestions_applied'] == 1
    assert summary['suggestions_needs_input'] == 0
    assert summary['not_used_reason'] is None


def test_activity_summary_explains_why_ai_was_not_used(store):
    # No policy row saved at all — the pre-field/legacy case.
    assert read_insights(store, OWNER, 'scan-1', 'run-1')['activity_summary']['not_used_reason'] \
        == "AI suggestions were not enabled for this run's plan."
    set_policy(store, ai=0, ai_budget_usd='5.00')
    assert read_insights(store, OWNER, 'scan-1', 'run-1')['activity_summary']['not_used_reason'] \
        == "AI suggestions were not enabled for this run's plan."
    set_policy(store, ai=1, ai_zone='any', ai_budget_usd='0.00')
    assert read_insights(store, OWNER, 'scan-1', 'run-1')['activity_summary']['not_used_reason'] \
        == 'Cloud AI not used: the run spending limit prevents a request.'
    # A zero paid budget does not block a LOCAL-only run — Ollama has nothing to meter.
    set_policy(store, ai=1, ai_zone='local', ai_budget_usd='0.00')
    assert read_insights(store, OWNER, 'scan-1', 'run-1')['activity_summary']['not_used_reason'] \
        == 'AI was enabled for this run, but no eligible findings needed a suggestion.'
    set_policy(store, ai=1, ai_zone='any', ai_budget_usd='5.00')
    assert read_insights(store, OWNER, 'scan-1', 'run-1')['activity_summary']['not_used_reason'] \
        == 'AI was enabled for this run, but no eligible findings needed a suggestion.'


def test_activity_summary_has_no_reason_once_something_was_attempted(store):
    set_policy(store, ai=1, ai_zone='any', ai_budget_usd='0.00')
    link(store)
    result = read_insights(store, OWNER, 'scan-1', 'run-1')
    assert result['activity_summary']['attempted'] == 1
    assert result['activity_summary']['not_used_reason'] is None


def test_review_receipts_are_paged_even_without_any_proposal_or_attempt(store):
    db = store._db
    with db.cursor() as cur:
        for index in range(3):
            db.execute(cur, '''INSERT INTO ai_review_receipts
                (owner_id,scan_id,run_id,operation_id,proposal_sha256,review_json,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                (OWNER, 'scan-1', 'run-1', f'op-{index}', sha256(str(index).encode()).hexdigest(), '{"verdict":"accept"}', '2026-09-08'))
    first = read_insights(store, OWNER, 'scan-1', 'run-1', offset=0, limit=2)
    second = read_insights(store, OWNER, 'scan-1', 'run-1', offset=2, limit=2)
    assert len(first['review_receipts']) == 2
    assert len(second['review_receipts']) == 1
    assert first['pagination']['total_review_receipts'] == 3
    assert first['pagination']['has_more'] is True
    assert second['pagination']['has_more'] is False
