"""Local vision is zero-paid-cost; managed cloud vision still fails closed."""
from types import SimpleNamespace
import pytest
import ai
import providers
import llm_waterfall_provider as waterfall


def setup(monkeypatch, local=True):
    ctx=SimpleNamespace(local_drafting=local, enabled=False, deferred=[],scan_id='scan',file='file.docx')
    monkeypatch.setattr(waterfall,'managed_context',lambda:ctx)
    monkeypatch.setattr(waterfall,'defer_managed',lambda *a,**k:None)
    return ctx


def test_local_plan_reaches_real_ollama_vision_http_and_never_configured_cloud(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(ai,'_maybe_refresh_endpoint',lambda:None)
    monkeypatch.setattr(ai,'_tags_cached',lambda:[{'name':ai.OLLAMA_VISION_MODEL}])
    assert ai.vision_is_available()
    assert ai.vision_unavailable_reason() is None
    calls=[]
    def post(url,**kw):
        calls.append((url,kw))
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'response':'A red bicycle parked beside a brick wall.'})
    monkeypatch.setattr('httpx.post',post)
    monkeypatch.setattr(ai,'_trace_ai',lambda *a,**k:'vision-call')
    monkeypatch.setattr(providers,'active_vision_provider',lambda:pytest.fail('Local plan selected configured cloud provider'))
    result=ai._vision_generate('Describe this image',b'image bytes',scan_id='scan',file='file.docx')
    assert result=='A red bicycle parked beside a brick wall.'
    assert len(calls)==1 and calls[0][1]['json']['images']


def test_managed_cloud_plan_cannot_bypass_paid_vision_gate(monkeypatch):
    setup(monkeypatch,local=False)
    monkeypatch.setattr('httpx.post',lambda *a,**k:pytest.fail('Unmetered request'))
    assert not ai.vision_is_available()
    assert ai._vision_generate('Describe',b'image') is None
    assert providers.OllamaVisionProvider('http://localhost:11434','vision').generate('Describe',b'image')['ok'] is False


def test_local_plan_cannot_escalate_to_non_ollama_provider(monkeypatch):
    setup(monkeypatch)
    cloud=SimpleNamespace(generate=lambda *a,**k:pytest.fail('Cloud escalation'))
    assert ai._bounded_vision_generate(cloud,'Describe',b'image')['ok'] is False


def test_suggest_fix_local_vision_has_real_provenance(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(ai,'describe_image',lambda *a,**k:{'alt':'A chart showing revenue growth.','model':'vision','ai_call_id':'call-1'})
    result=ai.suggest_fix('1.1.1','Non-text Content','A','file.docx',image_bytes=b'image')
    assert result['is_template'] is False
    assert result['ai_call_id']=='call-1'


def test_local_plan_refuses_public_owned_azure_endpoint(monkeypatch):
    setup(monkeypatch)
    public='https://acp-ollama-gpu.purplebeach-80e1296b.westus2.azurecontainerapps.io'
    monkeypatch.setattr(ai,'OLLAMA_BASE_URL',public)
    monkeypatch.setattr(ai,'_maybe_refresh_endpoint',lambda:None)
    monkeypatch.setattr('httpx.post',lambda *a,**k:pytest.fail('Local consent cannot send to public endpoint'))
    assert ai.vision_is_available() is False
    assert 'private Ollama endpoint' in ai.vision_unavailable_reason()
    assert ai._vision_generate('Describe',b'image') is None
    assert providers.OllamaVisionProvider(public,'vision').generate('Describe',b'image')['ok'] is False


def test_cloud_consent_allows_configured_public_ollama_without_paid_adapter(monkeypatch):
    ctx=setup(monkeypatch,local=False);ctx.enabled=True
    public='https://acp-ollama-gpu.purplebeach-80e1296b.westus2.azurecontainerapps.io'
    monkeypatch.setattr(ai,'OLLAMA_BASE_URL',public)
    calls=[]
    monkeypatch.setattr('httpx.post',lambda url,**kw:(calls.append(url) or SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'response':'A bicycle by a brick wall.'})))
    res=ai._bounded_vision_generate(providers.OllamaVisionProvider(public,'vision'),'Describe',b'image')
    assert res['ok'] and res['cost_usd']==0 and res['zone']=='cloud'
    assert calls==[public+'/api/generate']
    cloud=SimpleNamespace(generate=lambda *a,**k:pytest.fail('Unmetered paid adapter'))
    assert ai._bounded_vision_generate(cloud,'Describe',b'image')['ok'] is False
