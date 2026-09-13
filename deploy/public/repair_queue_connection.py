"""Repair PostgreSQL scaler credentials without changing application connection strings.

KEDA uses Go's strict URL parser; libpq supports a broader connection-string grammar.
The authoritative libpq parser determines fields; URL generation preserves their meaning.
Secrets stay in captured memory and a mode-0600 PATCH file; provider error text is not echoed.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote, urlencode


def canonical_connection(value):
    try:
        from psycopg2.extensions import parse_dsn
        parts = parse_dsn(value)
        if not {'host', 'dbname', 'user', 'password'} <= parts.keys():
            raise ValueError()
        host, port = parts.pop('host'), parts.pop('port', '5432')
        if not port.isdigit() or not (0 < int(port) < 65536) or any(c in host for c in '/@?#,'):
            raise ValueError()
        user, password, database = parts.pop('user'), parts.pop('password'), parts.pop('dbname')
        if ':' in host and not host.startswith('['):
            host = '[' + host + ']'
        result = ('postgresql://' + quote(user, safe='') + ':' + quote(password, safe='')
                  + '@' + host + ':' + port + '/' + quote(database, safe='')
                  + ('?' + urlencode(parts) if parts else ''))
        original = parse_dsn(value)
        original.setdefault('port', '5432')
        if parse_dsn(result) != original:
            raise ValueError()
        return result
    except Exception:
        raise ValueError('PostgreSQL scaler connection could not be normalized safely') from None


def repair_patch(app, secrets):
    template = deepcopy(app['properties']['template'])
    rules = template.get('scale', {}).get('rules', [])
    replacements = {}
    env_refs = [env.get('secretRef') for container in template.get('containers', [])
                for env in container.get('env', []) if env.get('name') == 'DATABASE_URL']
    for rule in rules:
        custom = rule.get('custom', {})
        if custom.get('type') != 'postgresql':
            continue
        for auth in custom.get('auth', []):
            if auth.get('triggerParameter') != 'connection':
                continue
            source = auth.get('secretRef')
            if source is None:
                raise ValueError('PostgreSQL scaler connection secret is missing')
            if len(env_refs) != 1 or not env_refs[0]:
                raise ValueError('Worker application database secret is ambiguous or missing')
            # Use the working application's source of truth, not a malformed or
            # stale credential currently bound to its queue scaler.
            database_secret = env_refs[0]
            entry = next((s for s in secrets if s.get('name') == database_secret), None)
            if not entry or not entry.get('value'):
                raise ValueError('PostgreSQL scaler secret value cannot be resolved safely')
            normalized = canonical_connection(entry['value'])
            # Stable dedicated secret means reruns do not create successive secrets.
            name = database_secret + '-keda'
            replacements[name] = {'name': name, 'value': normalized}
            auth['secretRef'] = name
    if not replacements:
        return None
    preserved = deepcopy(app['properties']['configuration'].get('secrets', []))
    preserved = [s for s in preserved if s.get('name') not in replacements]
    preserved.extend(replacements.values())
    return {'properties': {'configuration': {'secrets': preserved}, 'template': template}}


def azure(*args):
    subscription = os.environ.get('AZURE_SUBSCRIPTION_ID', '8fab0f8f-b577-45d7-a485-ec32f73b22be')
    result = subprocess.run(['az', *args, '--subscription', subscription, '-o', 'json', '--only-show-errors'],
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Azure scaler operation failed; provider output withheld to protect credentials')
    return json.loads(result.stdout) if result.stdout.strip() else None


def repair(resource_group, name):
    app = azure('containerapp', 'show', '-g', resource_group, '-n', name)
    secrets = azure('containerapp', 'secret', 'list', '-g', resource_group, '-n', name,
                   '--show-values')
    patch = repair_patch(app, secrets)
    if patch is None:
        print(name + ': no PostgreSQL scaler to repair')
        return
    if patch['properties']['template'] == app['properties']['template']:
        desired = {s['name']: s['value'] for s in patch['properties']['configuration']['secrets']
                   if s.get('name', '').endswith('-keda') and 'value' in s}
        actual_values = {s['name']: s.get('value') for s in secrets}
        if all(actual_values.get(key) == value for key, value in desired.items()):
            print(name + ': PostgreSQL scaler credential already verified')
            return
    with tempfile.TemporaryDirectory(prefix='acp-queue-connection-') as folder:
        path = Path(folder) / 'patch.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(patch, stream)
        azure('rest', '--method', 'patch', '--url',
              'https://management.azure.com' + app['id'] + '?api-version=2025-07-01',
              '--body', '@' + str(path))
    actual = azure('containerapp', 'show', '-g', resource_group, '-n', name)
    if actual['properties']['template']['scale'] != patch['properties']['template']['scale']:
        raise RuntimeError('PostgreSQL scaler repair verification failed')
    print(name + ': dedicated PostgreSQL scaler credential reference verified')


if __name__ == '__main__':
    try:
        group, *apps = sys.argv[1:]
        if not apps:
            raise ValueError('Supply resource group and worker app names')
        for app_name in apps:
            repair(group, app_name)
    except Exception as error:
        # Never echo URL parser, Azure response, or secret-containing exception text.
        print('PostgreSQL scaler repair failed (' + type(error).__name__ + ')', file=sys.stderr)
        sys.exit(1)
