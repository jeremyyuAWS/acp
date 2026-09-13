import logging


def test_failed_activity_is_reported_without_content(caplog):
    from ai_escalation_activity import emit

    class BrokenStore:
        def transaction(self):
            raise RuntimeError('private document contents and provider details')

    with caplog.at_level(logging.WARNING):
        emit(BrokenStore(), scan_id='scan', owner_id='owner', run_id='run',
             file='private.docx', operation_id='operation')
    assert 'ai_escalation_activity_unavailable error_type=RuntimeError' in caplog.text
    assert 'private' not in caplog.text
    assert 'provider details' not in caplog.text
