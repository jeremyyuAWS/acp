import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'api'))
import activity


def test_interleaved_stages_keep_their_own_current_document(monkeypatch):
    state = {}
    monkeypatch.setitem(sys.modules, 'core', SimpleNamespace(set_job=lambda key, value: state.__setitem__(key, value), get_job_state=state.get))
    activity.record_file('stage-isolation', 'Assess Original.pdf', action='checking contrast', phase='analysing', force=True)
    activity.record('stage-isolation', file='Remediate Original.docx', action='describing image 1 of 1', phase='remediating', force=True)
    assert activity.current('stage-isolation', stage='assess')['file'] == 'Assess Original.pdf'
    assert activity.current('stage-isolation', stage='remediate')['file'] == 'Remediate Original.docx'
    activity.finish_file('stage-isolation', 'Assess Original.pdf')
    assert activity.current('stage-isolation', stage='assess')['in_flight'] == 0
    assert activity.current('stage-isolation', stage='remediate')['file'] == 'Remediate Original.docx'


def test_legacy_activity_fallback_requires_matching_phase(monkeypatch):
    state = {'activity:legacy': {'phase': 'remediating', 'file': 'legacy.docx'}}
    monkeypatch.setitem(sys.modules, 'core', SimpleNamespace(get_job_state=state.get))
    assert activity.current('legacy', stage='assess') is None
    assert activity.current('legacy', stage='remediate')['file'] == 'legacy.docx'
