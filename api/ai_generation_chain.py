"""Immutable, opt-in generation positions. No network requests or approval effects."""
import re

STEP_IDS = ('primary', 'fallback_1', 'fallback_2')
ELIGIBLE = frozenset({'empty_response', 'truncated', 'invalid_required_structure',
                      'incomplete_requested_content'})


def normalize_chain(value):
    if not isinstance(value, dict) or value.get('version') != 1 or type(value.get('version')) is not int:
        raise ValueError('Generation chain version 1 is required.')
    steps = value.get('steps')
    if not isinstance(steps, list) or len(steps) not in (2, 3):
        raise ValueError('Two or three generation positions are required.')
    normalized = []
    for position, step in enumerate(steps):
        if (not isinstance(step, dict) or step.get('step_id') != STEP_IDS[position]
                or type(step.get('position')) is not int or step['position'] != position
                or step.get('enabled') is not True or step.get('capabilities') != ['text']
                or step.get('provider') not in ('openai', 'anthropic')
                or not isinstance(step.get('model'), str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,199}', step['model'])):
            raise ValueError('Explicit ordered enabled text generation positions are required.')
        normalized.append({key: step[key] for key in
                           ('step_id', 'position', 'provider', 'model', 'enabled', 'capabilities')})
    if len({s['model'] for s in normalized}) != len(steps):
        raise ValueError('Generation model positions must be distinct.')
    if len({s['provider'] for s in normalized}) != 1:
        raise ValueError('All positions must use the same allowed provider.')
    return {'version': 1, 'steps': normalized}


def normalize_execution(value):
    """Only bounded server-owned lineage may be committed before dispatch."""
    if not isinstance(value, dict):
        raise ValueError('Execution lineage is required.')
    position = value.get('generation_position')
    if (type(position) is not int or position not in (0, 1, 2)
            or type(value.get('chain_version')) is not int or value.get('chain_version') != 1 or value.get('step_id') != STEP_IDS[position]):
        raise ValueError('Invalid generation position.')
    for key in ('source_sha256',):
        if not isinstance(value.get(key), str) or not re.fullmatch('[0-9a-f]{64}', value[key]):
            raise ValueError('Exact assessed source is required.')
    for key in ('assessment_revision', 'request_id', 'adapter_id', 'locator'):
        if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= 4096:
            raise ValueError('Bounded execution identity is required.')
    ids = value.get('finding_ids')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 100
            or any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Explicit finding membership is required.')
    parent, reason = value.get('parent_attempt_id'), value.get('escalation_reason')
    if position == 0:
        if parent is not None or reason is not None:
            raise ValueError('Primary has no generation parent.')
    elif not isinstance(parent, str) or not 1 <= len(parent) <= 256 or reason not in ELIGIBLE:
        raise ValueError('Fallback requires a linked eligible preceding result.')
    return {key: value.get(key) for key in ('chain_version', 'step_id', 'generation_position',
            'parent_attempt_id', 'escalation_reason', 'source_sha256', 'assessment_revision',
            'finding_ids', 'request_id', 'adapter_id', 'locator')}


def chain_options(rows=()):
    """Read-only server catalog; credentials/prices/content are never returned."""
    result = {'supported': False, 'reason': 'Verified third model configuration is unavailable.',
              'version': 1, 'default_steps': [], 'models': [], 'max_steps': 3,
              'supported_adapters': ['pptx-slide-title.v1']}
    try:
        from llm_waterfall_provider import configured_generator
        generator = configured_generator()
    except (ValueError, TypeError, KeyError):
        return result
    for position, model in enumerate(generator.models):
        spec = generator.specs[model.name]
        result['models'].append({'provider': spec.provider, 'model': model.name,
                                'capabilities': ['text'], 'allowed': True, 'available': True,
                                'access_verified': False,
                                'reason': 'Configuration verified; account model access has not been tested.'})
        if position < 2:
            result['default_steps'].append({'step_id': STEP_IDS[position], 'position': position,
                'provider': spec.provider, 'model': model.name, 'enabled': True, 'capabilities': ['text']})
    if len(generator.models) < 3:
        return result
    if not any(str(row.get('file', '')).lower().endswith('.pptx')
               and row.get('criterion', row.get('rule_id')) == '2.4.6'
               and row.get('finding_count') == 1 for row in rows):
        result['reason'] = 'Second fallback requires a supported PPTX slide-title finding with an exact source binding.'
        return result
    # A supported scope gets the complete verified chain by default. The run
    # policy still snapshots this choice, and execution remains fail-closed on
    # the exact source/adapter checks before any third-model dispatch.
    third = generator.models[2]
    third_spec = generator.specs[third.name]
    result['default_steps'].append({'step_id': STEP_IDS[2], 'position': 2,
        'provider': third_spec.provider, 'model': third.name, 'enabled': True,
        'capabilities': ['text']})
    result.update(supported=True, reason=None)
    return result
