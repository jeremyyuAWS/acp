"""Read-only readiness for the exact proposed AI zone; never dispatch generation."""


def plan_ai_readiness(policy, ai_enabled=True):
    if not policy or not policy.get('ai'):
        return {'state': 'not_required', 'blocked': False}
    if not ai_enabled:
        return {'state': 'ai_disabled', 'blocked': True}
    if policy.get('ai_zone') != 'local':
        return {'state': 'governed_cloud', 'blocked': False}
    import ai
    import providers
    # A reachable public endpoint is still outside a local-only authorization.
    # Check this before any connection test. No endpoint or credentials are disclosed.
    ai._maybe_refresh_endpoint()
    if providers.zone_for_url(ai.OLLAMA_BASE_URL) != 'local':
        return {'state': 'local_endpoint_required', 'blocked': True}
    try:
        import httpx
        # The normal worker probe can wait 90 seconds for a cold start. A plan
        # preview must remain responsive and may only make this bounded metadata GET.
        response = httpx.get(f'{ai.OLLAMA_BASE_URL.rstrip("/")}/api/tags',
                             headers=ai._OLLAMA_HEADERS, timeout=3.0)
        response.raise_for_status()
        if not isinstance(response.json().get('models'), list):
            return {'state': 'local_endpoint_unreachable', 'blocked': True}
    except Exception:
        return {'state': 'local_endpoint_unreachable', 'blocked': True}
    return {'state': 'local_endpoint_ready', 'blocked': False}
