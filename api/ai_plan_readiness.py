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
        models = response.json().get('models')
        if not isinstance(models, list):
            return {'state': 'local_endpoint_unreachable', 'blocked': True}
        text_available = ai._tags_have(models, ai.OLLAMA_MODEL)
        vision_available = ai._tags_have(models, ai.OLLAMA_VISION_MODEL)
    except Exception:
        return {'state': 'local_endpoint_unreachable', 'blocked': True}
    # Local drafting includes text and image proposals. A reachable endpoint with
    # unrelated tags, or only one configured model, cannot fulfill that permission.
    models_ready = text_available and vision_available
    return {'state': 'local_endpoint_reachable' if models_ready else 'local_models_missing',
            'blocked': not models_ready,
            'text_model_available': text_available, 'vision_model_available': vision_available}
