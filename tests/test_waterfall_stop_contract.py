"""Stop decisions across real managed transport, spending and immutable history.

Synthetic provider responses are injected; no model quality score is inferred
from wording equality. Repeated unusable responses and unresolved reviews stop
at their configured bound, preserve usable drafts for a person, and cannot buy
more work on a worker retry.
"""
import hashlib
import json

import httpx
import pytest

from ai_attempt_history import AttemptHistory
from ai_review_chain import read_reviews
import llm_waterfall_provider as bounded
from test_llm_waterfall_provider import managed, specs, Response, result


@pytest.fixture
def stop_run(managed):
    managed.scan_id = 'stop-contract-scan'
    managed.file = 'synthetic-document.docx'
    managed.policy = {'ai_review': {'enabled': True, 'mode': 'threshold',
                                    'minimum_reliability': 95, 'max_review_attempts': 2}}
    history = AttemptHistory(managed.ledger.db)
    history.init_schema()
    from ai_review_chain import SCHEMA
    with managed.ledger.db.cursor() as cur:
        for statement in SCHEMA:
            managed.ledger.db.execute(cur, statement)
    return managed, history


def transport(monkeypatch, responses):
    calls = []
    def post(*args, **kwargs):
        model = kwargs['json']['model']
        calls.append(model)
        if not responses:
            pytest.fail('waterfall bought an additional attempt after its stopping point')
        content, issue = responses.pop(0)
        if issue == 'timeout':
            raise httpx.ReadTimeout('fixture charge unknown')
        data = result(model=model, text=content)
        if issue == 'refusal':
            data['choices'][0]['message']['refusal'] = 'Fixture provider refusal'
        else:
            data['choices'][0]['finish_reason'] = issue or 'stop'
        return Response(data)
    monkeypatch.setattr(httpx, 'post', post)
    return calls


@pytest.mark.parametrize('verdict', ['revise', 'unable', 'malformed'])
def test_same_unresolved_review_stops_at_two_checks_without_rewriting_or_paid_retry(stop_run, monkeypatch, verdict):
    ctx, history = stop_run
    draft_text = 'A source-grounded draft for a person to consider'
    review_text = ('not a review object' if verdict == 'malformed' else
                   json.dumps({'verdict': verdict, 'reason': 'Source evidence still needs a person.'}))
    calls = transport(monkeypatch, [(draft_text, None), (review_text, None), (review_text, None)])
    response = bounded.managed_text_generate('Synthetic source and task')
    replay = bounded.managed_text_generate('Synthetic source and task')
    assert calls == ['small-pinned-v1', 'large-pinned-v1', 'small-pinned-v1']
    assert response['text'] == replay['text'] == draft_text
    assert response['approval_required'] is replay['approval_required'] is True
    assert response['review']['verdict'] == ('unable' if verdict == 'malformed' else verdict)
    assert len(response['review']['steps']) == 2
    assert response['reason'] == 'automatic_application_not_supported_for_this_change'
    rows = history.list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert [row['purpose'] for row in rows] == ['draft', 'review', 'final_review']
    assert len({row['attempt_id'] for row in rows}) == 3
    receipts = read_reviews(ctx.ledger.db, ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert len(receipts) == 1
    assert receipts[0]['proposal_sha256'] == hashlib.sha256(draft_text.encode()).hexdigest()
    assert all(step['proposal_sha256'] == receipts[0]['proposal_sha256'] for step in receipts[0]['review']['steps'])
    assert ctx.ledger.snapshot(ctx.owner_id, ctx.run_id)['spent_units'] == 360


def test_accepted_first_review_stops_before_final_and_keeps_human_approval(stop_run, monkeypatch):
    ctx, history = stop_run
    calls = transport(monkeypatch, [('Usable draft', None),
        (json.dumps({'verdict': 'accept', 'reason': 'Suitable for human consideration.'}), None)])
    response = bounded.managed_text_generate('Synthetic source')
    assert response['review']['verdict'] == 'accept' and response['approval_required'] is True
    assert len(response['review']['steps']) == 1
    assert [row['purpose'] for row in history.list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)] == ['draft', 'review']
    assert calls == ['small-pinned-v1', 'large-pinned-v1']  # second model is a review, not another fix
    assert ctx.ledger.snapshot(ctx.owner_id, ctx.run_id)['spent_units'] == 240


@pytest.mark.parametrize('issue,reason,held', [('refusal', 'provider_refused', 0),
                                            ('timeout', 'provider_usage_unknown', 8448)])
def test_review_refusal_or_unknown_charge_cannot_trigger_final_review(stop_run, monkeypatch, issue, reason, held):
    ctx, history = stop_run
    calls = transport(monkeypatch, [('Keep this draft for the person', None), ('Refusal explanation', issue)])
    response = bounded.managed_text_generate('Synthetic source')
    replay = bounded.managed_text_generate('Synthetic source')
    assert response['review']['verdict'] == 'unable'
    assert response['review']['reason'] == reason
    assert response['text'] == replay['text'] == 'Keep this draft for the person'
    assert response['approval_required'] is replay['approval_required'] is True
    assert len(response['review']['steps']) == 1
    assert calls == ['small-pinned-v1', 'large-pinned-v1']
    rows = history.list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert [row['purpose'] for row in rows] == ['draft', 'review']
    assert rows[-1]['status'] == ('refused' if issue == 'refusal' else 'usage_unknown')
    budget = ctx.ledger.snapshot(ctx.owner_id, ctx.run_id)
    assert budget['held_units'] == held
    assert budget['spent_units'] == (240 if issue == 'refusal' else 120)


def test_budget_denial_stops_review_but_retains_paid_draft_for_human(stop_run, monkeypatch):
    ctx, history = stop_run
    ctx.ledger.create_budget(ctx.owner_id, 'review-budget-tight', 8500)
    ctx.run_id = 'review-budget-tight'
    calls = transport(monkeypatch, [('Paid usable draft', None)])
    response = bounded.managed_text_generate('Synthetic source')
    assert response['text'] == 'Paid usable draft' and response['approval_required'] is True
    assert response['review']['verdict'] == 'unable'
    assert response['review']['reason'] == 'budget_admission_denied'
    assert len(response['review']['steps']) == 1
    assert calls == ['small-pinned-v1']
    assert len(history.list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)) == 1
    budget = ctx.ledger.snapshot(ctx.owner_id, ctx.run_id)
    assert budget['spent_units'] == 120 and budget['held_units'] == 0
    receipt = read_reviews(ctx.ledger.db, ctx.owner_id, ctx.scan_id, ctx.run_id)[0]
    assert receipt['review']['reason'] == 'budget_admission_denied'


@pytest.mark.parametrize('text,finish', [('', 'stop'), ('Same incomplete output', 'length')])
def test_two_unusable_outputs_stop_before_review_and_do_not_repurchase(stop_run, monkeypatch, text, finish):
    ctx, history = stop_run
    calls = transport(monkeypatch, [(text, finish), (text, finish)])
    response = bounded.managed_text_generate('Synthetic source')
    replay = bounded.managed_text_generate('Synthetic source')
    assert response['deferred'] and response['reason'] == 'attempts_exhausted'
    assert not response['text'] and not replay['text'] and replay['deferred']
    assert calls == ['small-pinned-v1', 'large-pinned-v1']
    rows = history.list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert [row['purpose'] for row in rows] == ['draft', 'fallback']
    assert all(row['status'] == ('empty_response' if not text else 'unusable_response') for row in rows)
    assert read_reviews(ctx.ledger.db, ctx.owner_id, ctx.scan_id, ctx.run_id) == []
    assert ctx.ledger.snapshot(ctx.owner_id, ctx.run_id)['spent_units'] == 240
