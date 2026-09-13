import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('storage_check', Path(__file__).parents[1] / 'deploy/langfuse-v3/storage_check.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def stats(space=50, inodes=50, blocks=100, files=100):
    return SimpleNamespace(f_bavail=space, f_blocks=blocks, f_favail=inodes, f_files=files)


def test_inode_exhaustion_is_critical_even_when_bytes_available():
    assert module.capacity(stats(inodes=1))['severity'] == 'critical'


def test_space_and_inode_thresholds():
    for kwargs in ({'space': 9}, {'inodes': 9}):
        assert module.capacity(stats(**kwargs))['severity'] == 'warning'
    assert module.capacity(stats(space=5, inodes=10))['severity'] == 'warning'
    assert module.capacity(stats(space=10, inodes=10))['severity'] == 'healthy'
    assert module.capacity(stats(files=0))['severity'] == 'critical'


def test_missing_mount_cannot_report_os_disk_as_healthy():
    with patch.object(module.os.path, 'ismount', return_value=False):
        assert module.check()['severity'] == 'critical'
