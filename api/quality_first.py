"""Opt-in cloud quality routing, bounded by existing owner permissions and prices."""


def normalize_quality_first(policy):
    value = policy['quality_first']
    if type(value) is not bool:
        raise ValueError('quality_first must be a boolean')
    if value and (policy.get('ai') != 1 or policy.get('ai_zone') != 'any'
                  or policy.get('cloud_input_strategy') != 'automatic'
                  or policy.get('generation_chain')):
        raise ValueError('Quality-first requires automatic Cloud AI without a manual model chain')
    return value


def configured_quality_generator(*, provider_module=None, post=None):
    from native_pdf_quality import profile_specs
    from llm_waterfall_provider import StrictTextGenerator
    if provider_module is None:
        import providers as provider_module
    specs = profile_specs()
    # Keep the owner's selected provider first. Both vendors must already be allowed;
    # a key alone never grants permission. Reuse the verified quality model catalog.
    active = provider_module.active_text_provider()
    specs = tuple(sorted(specs, key=lambda spec: spec.provider != active))
    generator = StrictTextGenerator(specs, provider_module=provider_module, post=post)
    if any(zone != 'cloud' for zone in generator.zones.values()):
        raise ValueError('Quality-first requires cloud endpoints for every model')
    return generator
