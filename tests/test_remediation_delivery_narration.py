"""Exercise the actual mirror branches, preserving delivery failures without false alarms."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE = (Path(__file__).resolve().parents[1] / 'api' / 'handlers.py').read_text()
TREE = ast.parse(SOURCE)
MIRROR = next(node for node in ast.walk(TREE) if isinstance(node, ast.If)
              and ast.unparse(node.test) == "source == 'drive' and core.store.get_drive_mirror_enabled()")


def execute(statements, **values):
    env = dict(core=SimpleNamespace(store=Mock()), filename='fixture.pdf', scan_id='fixture',
               delivery_status='saved_in_acp', delivery_reason='source_delivery_unavailable')
    env.update(values)
    exec(compile(ast.Module(body=statements, type_ignores=[]), '<mirror fixture>', 'exec'), env)
    return env


def test_disabled_delivery_is_saved_in_acp_not_an_error():
    core = SimpleNamespace(store=Mock())
    core.store.get_drive_mirror_enabled.return_value = False
    result = execute([MIRROR], core=core, source='drive')
    assert result['delivery_status'] == 'saved_in_acp'
    assert result['delivery_reason'] == 'delivery_disabled'


def test_non_drive_source_is_saved_in_acp_without_claiming_delivery():
    result = execute([MIRROR], source='sharepoint')
    assert result['delivery_status'] == 'saved_in_acp'
    assert result['delivery_reason'] == 'source_delivery_unavailable'


def test_permission_and_provider_errors_emit_allowlisted_reasons():
    handler = next(node for node in ast.walk(MIRROR) if isinstance(node, ast.ExceptHandler)
                   and isinstance(node.type, ast.Name) and node.type.id == 'HttpError')
    for status, reason in [(403, 'write_permission_required'), (500, 'provider_error')]:
        result = execute(handler.body, e=SimpleNamespace(resp=SimpleNamespace(status=status)),
                         delivery_status='failed')
        assert result['delivery_status'] == 'failed'
        assert result['delivery_reason'] == reason
        assert 'SimpleNamespace' not in result['delivery_reason']
