"""At most two configured Ollama text models on the same endpoint."""
import os
import time


def generate(prompt, endpoint, primary, *, headers=None, local_only=False, on_attempt=None,
             timeout_seconds=90, max_attempts=2):
    import httpx
    from providers import zone_for_url
    zone = zone_for_url(endpoint)
    if local_only and zone != 'local':
        return None
    fallback = os.environ.get('OLLAMA_FALLBACK_MODEL', '').strip()
    models = [primary] + ([fallback] if fallback and fallback != primary else [])
    if not 0 < timeout_seconds <= 90 or max_attempts not in (1, 2):
        raise ValueError('Bounded local timeout and one or two attempts required')
    models = models[:max_attempts]
    attempts = []
    for model in models:
        started = time.monotonic()
        data = {}
        try:
            response = httpx.post(endpoint.rstrip('/') + '/api/generate',
                json={'model': model, 'prompt': prompt, 'stream': False,
                      'options': {'temperature': 0.4, 'num_predict': 800}},
                headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            data = response.json()
            text = (data.get('response') or '').strip().strip('"').strip()
            reason = ('truncated' if data.get('done_reason') == 'length' or data.get('done') is False
                      else 'empty_response' if not text else None)
        except Exception:
            text, reason = '', 'request_failed'
        attempts.append({'model': model, 'provider': 'ollama', 'zone': zone,
                         'ok': reason is None, 'reason': reason})
        call_id = on_attempt(model, text, data, started, reason) if on_attempt else None
        if reason is None:
            return {'text': text, 'model': model, 'zone': zone, 'attempts': attempts,
                    'call_id': call_id}
    return None
