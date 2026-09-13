import json
import io
import importlib.util
from pathlib import Path
import pytest
from ollama_runtime import keep_alive, timings
ROOT=Path(__file__).resolve().parents[1]


def module(path):
    spec=importlib.util.spec_from_file_location(path.stem,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def test_residency_is_finite_and_can_be_explicitly_disabled(monkeypatch):
    monkeypatch.delenv('ACP_OLLAMA_KEEP_ALIVE',raising=False);assert keep_alive()=='30m'
    for value in ['0','15m','1h','300s']:
        monkeypatch.setenv('ACP_OLLAMA_KEEP_ALIVE',value);assert keep_alive()==value
    for value in ['-1','indefinite','NaN','999999999h']:
        monkeypatch.setenv('ACP_OLLAMA_KEEP_ALIVE',value);assert keep_alive()=='30m'


def test_timings_do_not_confuse_model_loading_and_generation():
    result=timings({'total_duration':24_000_000_000,'load_duration':20_000_000_000,'prompt_eval_duration':1_000_000_000,'eval_duration':3_000_000_000,'eval_count':12})
    assert result=={'total_ms':24000,'model_load_ms':20000,'prompt_eval_ms':1000,'inference_ms':3000,'output_tokens_per_second':4}
    assert timings({'load_duration':True,'total_duration':float('nan'),'eval_duration':-1})=={}
    assert timings({'load_duration':10**400,'eval_duration':1,'eval_count':10**400})=={'inference_ms':0.0}


def test_ollama_provider_keeps_existing_model_and_returns_measured_timings(monkeypatch):
    import httpx
    import providers
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'response':'A blue square.','load_duration':2_000_000_000,'eval_duration':3_000_000_000,'eval_count':12}
    calls=[]
    monkeypatch.setattr(httpx,'post',lambda *args,**kwargs:(calls.append((args,kwargs)) or Response()))
    result=providers.OllamaVisionProvider('http://localhost:11434','existing-model').generate('visible contents',b'fake-image')
    assert result['ok'] is True
    assert result['model']=='existing-model'
    assert result['timing']['model_load_ms']==2000
    assert result['timing']['inference_ms']==3000
    assert calls[0][1]['json']['keep_alive']=='30m'
    assert calls[0][1]['json']['options']=={'temperature':0.2,'num_predict':200}


def test_startup_warming_loads_only_baked_models_without_inference_or_downloads():
    warm=module(ROOT/'deploy/ollama/acp-ollama-warm.py')
    calls=[]
    def opener(request,**kwargs):
        calls.append(request)
        return io.BytesIO(json.dumps({'models':[{'name':'llava:13b'}]} if isinstance(request,str) else {'done':True,'load_duration':2_000_000_000}).encode())
    results=warm.warm_models('http://127.0.0.1:11500',['llava:13b','missing-model'],opener=opener)
    assert [row['state'] for row in results]==['loaded','not_installed']
    assert len(calls)==2
    payload=json.loads(calls[1].data)
    assert payload=={'model':'llava:13b','prompt':'','stream':False,'keep_alive':'30m'}
    assert '/api/generate' in calls[1].full_url


def test_startup_warming_never_calls_an_external_endpoint():
    warm=module(ROOT/'deploy/ollama/acp-ollama-warm.py')
    with pytest.raises(ValueError):warm.warm_models('https://paid-provider.example',['llava:13b'])


def test_replay_control_shows_load_change_without_claiming_faster_inference():
    benchmark=module(ROOT/'scripts/benchmark_ollama_vision.py')
    result=benchmark.summarize(json.loads(benchmark.FIXTURE.read_text()))
    assert result['mode']=='synthetic_replay'
    assert result['phases']['first_observed']['model_load_ms_median']==20000
    assert result['phases']['repeated']['inference_ms_median']==3000
    assert result['phases']['first_observed']['inference_ms_median']==3000
    assert all('response' not in row for row in result['samples'])


def test_benchmark_rejects_external_and_unbounded_live_calls():
    benchmark=module(ROOT/'scripts/benchmark_ollama_vision.py')
    with pytest.raises(ValueError):benchmark.live_local('https://paid.example','existing')
    with pytest.raises(ValueError):benchmark.live_local('http://localhost:11434','existing',repetitions=100)


def test_gpu_startup_preserves_gate_and_models_and_existing_capacity():
    docker=(ROOT/'deploy/ollama/Dockerfile.gpu').read_text()
    start=(ROOT/'deploy/ollama/acp-start-gpu.sh').read_text()
    assert 'ollama pull llava:13b' in docker and 'ollama pull llama3.1:8b' in docker
    assert 'OLLAMA_MAX_LOADED_MODELS=2' in docker
    assert 'export OLLAMA_HOST=127.0.0.1:11500' in start
    assert 'python3 /usr/local/bin/acp-ollama-warm.py &' in start
    assert 'exec python3 /usr/local/bin/acp-ollama-gate.py' in start


def test_benchmark_uses_a_readable_synthetic_png():
    benchmark=module(ROOT/'scripts/benchmark_ollama_vision.py')
    from PIL import Image
    with Image.open(io.BytesIO(benchmark.IMAGE)) as image:
        assert image.size==(32,32)
        image.verify()


def test_benchmark_reports_empty_and_truncated_responses_without_claiming_success():
    benchmark=module(ROOT/'scripts/benchmark_ollama_vision.py')
    result=benchmark.summarize({'samples':[{'response':{'done':True,'response':'','done_reason':'stop'}},
                                           {'response':{'done':True,'response':'Part of a','done_reason':'length'}}]})
    assert result['samples'][0]['nonempty'] is False
    assert result['samples'][1]['truncated'] is True


def test_startup_warming_unavailable_server_is_bounded():
    warm=module(ROOT/'deploy/ollama/acp-ollama-warm.py')
    now=[0]
    def fail(*args,**kwargs):raise OSError('not listening')
    results=warm.warm_models('http://127.0.0.1:11500',['llava:13b'],timeout=2,
                            opener=fail,clock=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
    assert results==[{'state':'unavailable','model':'llava:13b'}]
    assert now[0]<=2


def test_startup_warming_respects_existing_operator_optout_and_reuses_bake_layer():
    start=(ROOT/'deploy/ollama/acp-start-gpu.sh').read_text()
    docker=(ROOT/'deploy/ollama/Dockerfile.gpu').read_text()
    assert 'ACP_OLLAMA_KEEPALIVE:-1' in start
    assert docker.index('ollama pull llava:13b')<docker.index('ENV OLLAMA_KEEP_ALIVE=30m')


def test_empty_vision_response_keeps_failure_reason_and_measured_load_time(monkeypatch):
    import httpx
    import providers
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'response':'','done_reason':'stop','load_duration':2_000_000_000}
    monkeypatch.setattr(httpx,'post',lambda *args,**kwargs:Response())
    result=providers.OllamaVisionProvider('http://localhost:11434','existing-model').generate('visible contents',b'fake-image')
    assert result['ok'] is False
    assert result['reason']==providers.REASON_EMPTY
    assert result['timing']['model_load_ms']==2000
