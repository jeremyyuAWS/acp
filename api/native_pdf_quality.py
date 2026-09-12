"""Frozen native-PDF-only model routing; never changes global provider selection."""
from dataclasses import replace
from types import MappingProxyType

PROFILE_ID = 'native-pdf-quality.v1'
MODELS = (('openai', 'gpt-4.1-2025-04-14'), ('anthropic', 'claude-sonnet-5'))


def profile_specs():
    # Reuse existing expiring, server-owned prices and limits verbatim.
    from ai_model_profiles import model_config
    from llm_waterfall_provider import TextModelSpec
    return tuple(TextModelSpec(**next(spec for spec in model_config(profile)
                                     if spec['provider'] == provider and spec['model'] == model))
                 for profile, (provider, model) in zip(('openai-balanced', 'anthropic-balanced'), MODELS))


class _AuthorizedNativeProviders:
    """Instance-local routing authorized by the explicitly saved native profile.

    Credential and endpoint lookups still use the configured providers module.
    No global/module function, environment or application setting is mutated.
    """
    def __init__(self, providers):
        self._providers = providers

    def __getattr__(self, name):
        return getattr(self._providers, name)

    def active_text_provider(self):
        return MODELS[0][0]

    def permitted_text_providers(self):
        return frozenset(provider for provider, _ in MODELS)


def configured_native_pdf_generator(ctx, *, provider_module=None, post=None):
    if (ctx.policy.get('document_wide_model_profile') != PROFILE_ID
            or ctx.policy.get('document_wide_input_mode') != 'native_pdf'
            or ctx.policy.get('document_wide_ai') is not True
            or ctx.policy.get('ai_zone') != 'any' or not ctx.enabled
            or not ctx.file.lower().endswith('.pdf')):
        raise ValueError('document_wide_native_profile_not_authorized')
    if provider_module is None:
        import providers as provider_module
    from llm_waterfall_provider import StrictTextGenerator
    specs = profile_specs()
    if tuple((spec.provider, spec.model) for spec in specs) != MODELS:
        raise ValueError('document_wide_native_profile_models_unavailable')
    return StrictTextGenerator(specs, provider_module=_AuthorizedNativeProviders(provider_module), post=post)


def native_profile_context(ctx):
    """Explicit native profile supersedes generic generation positions for this lane.

    Preserve the frozen original context and its shared accounting identities. Other
    files in a mixed run continue to use their accepted generic generation chain.
    """
    policy = dict(ctx.policy)
    policy.pop('generation_chain', None)
    return replace(ctx, policy=MappingProxyType(policy))
