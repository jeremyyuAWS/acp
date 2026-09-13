#!/usr/bin/env python3
"""Read-only capacity alerts. No telemetry contents, retention, or deletion."""
import json
import os
from pathlib import Path

MOUNT = Path('/mnt/data')
DATA = MOUNT / 'docker/volumes/langfuse_miniodata/_data'


def capacity(stats):
    # Use available capacity, not root's reserved blocks.
    space = stats.f_bavail / stats.f_blocks if stats.f_blocks > 0 else None
    inodes = stats.f_favail / stats.f_files if stats.f_files > 0 else None
    values = [space, inodes]
    severity = 'critical' if any(v is None or v < .05 for v in values) else 'warning' if any(v < .10 for v in values) else 'healthy'
    return {'severity': severity, 'free_space_percent': None if space is None else round(space * 100, 2), 'free_inodes_percent': None if inodes is None else round(inodes * 100, 2)}


def check(mount=MOUNT, data=DATA):
    # A missing mount must never report the OS filesystem as healthy telemetry storage.
    if not os.path.ismount(mount) or not data.is_dir():
        return {'severity': 'critical', 'reason': 'telemetry_storage_unavailable'}
    try:
        if mount.stat().st_dev != data.stat().st_dev:
            return {'severity': 'critical', 'reason': 'unexpected_telemetry_filesystem'}
        return capacity(os.statvfs(data))
    except OSError:
        return {'severity': 'critical', 'reason': 'telemetry_storage_check_failed'}


def main():
    result = check()
    priority = {'critical': 3, 'warning': 4, 'healthy': 6}[result['severity']]
    print(f'<{priority}>telemetry_storage ' + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['severity'] == 'healthy' else 1


if __name__ == '__main__':
    raise SystemExit(main())
