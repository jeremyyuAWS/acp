"""Managed history must not retain refusal/truncation as a reusable draft."""
import pytest
import vision_generation as vision
from ai_run_policy import run_context
from ai_attempt_history import AttemptHistory
from test_vision_generation import setup, image
from test_llm_waterfall_provider import specs


def test_plain_text_refusal_is_settled_but_never_drafted_or_replayed(setup):
    store, job, calls, outputs = setup
    outputs.extend(["I'm sorry, but I cannot describe this image."] * 2)
    with run_context(store, job['payload'], job) as ctx:
        first = vision.generate('Describe', image())
        second = vision.generate('Describe', image())
        rows = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert not first['ok'] and first['reason'] == 'provider_refused'
    assert not second.get('replayed')
    assert all(row['status'] == 'refused' and row['spending_state'] == 'settled' for row in rows)
    assert all(row['status'] != 'drafted' for row in rows)


def test_omission_marker_uses_only_existing_authorized_fallback_and_replays_success(setup):
    store, job, calls, outputs = setup
    outputs.extend(['Connect the hose and then…', 'A red bicycle leaning against a brick wall.'])
    with run_context(store, job['payload'], job) as ctx:
        first = vision.generate('Describe', image())
        second = vision.generate('Describe', image())
        rows = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert first['ok'] and first['text'] == 'A red bicycle leaning against a brick wall.'
    assert second['replayed'] and second['text'] == first['text']
    assert len(calls) == 2
    assert {row['status'] for row in rows} == {'unusable_response', 'drafted'}
    assert all(row['spending_state'] == 'settled' for row in rows)


def test_old_unvalidated_draft_is_not_replayed_under_new_quality_contract(setup, monkeypatch):
    import ai
    store, job, calls, outputs = setup
    outputs.extend(['Connect the hose and then…', 'A red bicycle beside a brick wall.'])
    with run_context(store, job['payload'], job):
        # Seed a historical successful draft under the pre-validator input shape.
        with monkeypatch.context() as old:
            old.setattr(vision, 'CAPTION_VALIDATION_VERSION', '')
            old.setattr(ai, '_description_quality_failure', lambda _: None)
            historical = vision.generate('Describe', image())
        fresh = vision.generate('Describe', image())
        replay = vision.generate('Describe', image())
    assert historical['ok'] and historical['text'].endswith('…')
    assert fresh['ok'] and fresh['text'] == 'A red bicycle beside a brick wall.'
    assert fresh['operation_id'] != historical['operation_id']
    assert not fresh.get('replayed') and replay['replayed']
    assert len(calls) == 2
