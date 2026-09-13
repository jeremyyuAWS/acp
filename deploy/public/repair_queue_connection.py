"""Repair PostgreSQL scaler credentials without changing application connection strings.

KEDA uses Go's strict URL parser; libpq supports a broader connection-string grammar.
The authoritative libpq parser determines fields; URL generation preserves their meaning.
Secrets stay in captured memory and a mode-0600 PATCH file; provider error text is not echoed.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlencode

# This supported schema includes imageType/customMetricsSettings emitted by the
# current CLI. Pin reads and writes together so a future CLI cannot silently
# submit a newer template to an older API (which rejects unknown fields).
ARM_API_VERSION = '2025-10-02-preview'


class AzureOperationError(RuntimeError):
    """Only allowlisted operation/category fields; never provider messages."""


def canonical_connection(value):
    try:
        from psycopg2.extensions import parse_dsn
    except ImportError:
        raise ValueError('PostgreSQL scaler parser dependency is unavailable') from None
    try:
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
    names = [s.get('name') for s in secrets]
    configured_names = [s.get('name') for s in app['properties']['configuration'].get('secrets', [])]
    if (not all(names) or len(set(names)) != len(names) or not all(configured_names)
            or len(set(configured_names)) != len(configured_names)):
        raise ValueError('Application secret names are missing or ambiguous')
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
    resolved = {s['name']: s for s in secrets}
    for entry in preserved:
        if entry.get('keyVaultUrl'):
            continue
        value = resolved.get(entry['name'], {}).get('value')
        if value is None:
            raise ValueError('Existing application secret cannot be preserved safely')
        # ARM requires values on full secret-list updates; show omits them.
        # Resolve privately and retain every original value unchanged.
        entry['value'] = value
    preserved.extend(replacements.values())
    return {'properties': {'configuration': {'secrets': preserved}, 'template': template}}


def azure(*args):
    subscription = os.environ.get('AZURE_SUBSCRIPTION_ID', '8fab0f8f-b577-45d7-a485-ec32f73b22be')
    result = subprocess.run(['az', *args, '--subscription', subscription, '-o', 'json', '--only-show-errors'],
                            text=True, capture_output=True)
    if result.returncode:
        stage = ('rest_' + args[2]) if args[:2] == ('rest', '--method') else ('secret_read' if args[:3] == ('containerapp', 'secret', 'list') else 'app_read')
        status = re.search(r'\b([45][0-9]{2})\b', result.stderr)
        category = 'http_' + status.group(1) if status else 'provider_failure'
        raise AzureOperationError(stage + ':' + category)
    return json.loads(result.stdout) if result.stdout.strip() else None


def read_app(resource_group, name):
    identity = azure('containerapp', 'show', '-g', resource_group, '-n', name)
    return azure('rest', '--method', 'get', '--url',
                 'https://management.azure.com' + identity['id'] + '?api-version=' + ARM_API_VERSION)


def secrets_match(actual, actual_secrets, desired):
    actual_values = {s['name']: s.get('value') for s in actual_secrets}
    actual_config = {s['name']: s for s in actual['properties']['configuration'].get('secrets', [])}
    if set(actual_config) != {s['name'] for s in desired}:
        return False
    for entry in desired:
        configured = actual_config[entry['name']]
        if entry.get('keyVaultUrl'):
            valid = all(configured.get(k) == entry.get(k) for k in ('keyVaultUrl', 'identity'))
        else:
            valid = actual_values.get(entry['name']) == entry['value'] and not configured.get('keyVaultUrl')
        if not valid:
            return False
    return True


def verified_template(resource_group, name, desired, desired_secrets=None):
    # ARM accepts updates before subsequent GETs expose their new revision.
    # Read-only bounded polling prevents a successful PATCH being reported as
    # failed while preserving an exact comparison of all template fields.
    for attempt in range(12):
        actual = read_app(resource_group, name)
        if actual['properties'].get('provisioningState') == 'Failed':
            raise RuntimeError('PostgreSQL scaler provisioning failed')
        state = actual['properties'].get('provisioningState')
        if state in (None, 'Succeeded') and actual['properties']['template'] == desired:
            if desired_secrets is None:
                return actual
            actual_secrets = azure('containerapp', 'secret', 'list', '-g', resource_group, '-n', name,
                                   '--show-values')
            if secrets_match(actual, actual_secrets, desired_secrets):
                return actual
        if attempt < 11:
            time.sleep(5)
    raise RuntimeError('PostgreSQL scaler repair verification failed')


def repair(resource_group, name):
    app = read_app(resource_group, name)
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
              'https://management.azure.com' + app['id'] + '?api-version=' + ARM_API_VERSION,
              '--body', '@' + str(path))
    verified_template(resource_group, name, patch['properties']['template'],
                      patch['properties']['configuration']['secrets'])
    print(name + ': dedicated PostgreSQL scaler credential reference verified')


VALIDATION_REASON_CODES = {
    'PostgreSQL scaler parser dependency is unavailable': 'dsn_parser_unavailable',
    'PostgreSQL scaler connection could not be normalized safely': 'dsn_normalization_invalid',
    'Application secret names are missing or ambiguous': 'secret_names_ambiguous',
    'PostgreSQL scaler connection secret is missing': 'scaler_secret_missing',
    'Worker application database secret is ambiguous or missing': 'database_secret_reference_invalid',
    'PostgreSQL scaler secret value cannot be resolved safely': 'database_secret_value_unavailable',
    'Existing application secret cannot be preserved safely': 'preserved_secret_value_unavailable',
    'Supply resource group and worker app names': 'worker_targets_missing',
}


def report_failure(error):
    # Only exact developer-authored messages become retained diagnostic codes.
    # Never forward a DSN parser/provider message, credential or arbitrary exception text.
    reason_code = VALIDATION_REASON_CODES.get(str(error)) if isinstance(error, ValueError) else None
    if isinstance(error, AzureOperationError) and re.fullmatch(
            r'(?:rest_(?:get|patch)|secret_read|app_read):(?:http_[45][0-9]{2}|provider_failure)', str(error)):
        reason_code = str(error)
    detail = ':' + reason_code if reason_code else ''
    print('PostgreSQL scaler repair failed (' + type(error).__name__ + detail + ')', file=sys.stderr)


if __name__ == '__main__':
    try:
        group, *apps = sys.argv[1:]
        if not apps:
            raise ValueError('Supply resource group and worker app names')
        for app_name in apps:
            repair(group, app_name)
    except Exception as error:
        report_failure(error)
        sys.exit(1)
