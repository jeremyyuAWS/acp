#!/usr/bin/env python3
"""Load configured baked models once at GPU startup; never download or swap models."""
import json
import os
import re
import time
import urllib.request
import urllib.error


def warm_models(base_url, models, *, timeout=120, keep_alive='30m', opener=urllib.request.urlopen, clock=time.monotonic, sleep=time.sleep):
    # This startup utility may only access its own loopback Ollama process.
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1','localhost','::1'}:
        raise ValueError('Startup warming requires the loopback Ollama endpoint')
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,4}(?:ms|s|m|h))',str(keep_alive)):
        keep_alive='30m'
    deadline = clock() + timeout
    while True:
        try:
            with opener(base_url + '/api/tags', timeout=min(3,max(0.1,deadline-clock()))) as response:
                tags = json.load(response)
            if not isinstance(tags,dict) or not isinstance(tags.get('models'),list):
                raise ValueError('Invalid model inventory')
            break
        except (OSError,urllib.error.URLError):
            if clock() >= deadline:
                return [{'state':'unavailable','model':model} for model in models]
            sleep(min(1,max(0,deadline-clock())))
    installed = {row.get('name') or row.get('model') for row in tags['models'] if isinstance(row,dict)}
    results=[]
    for model in dict.fromkeys(models):
        if model not in installed:
            results.append({'model':model,'state':'not_installed'})
            continue
        remaining = deadline-clock()
        if remaining <= 0:
            results.append({'model':model,'state':'deadline_exceeded'})
            continue
        request=urllib.request.Request(base_url+'/api/generate',method='POST',
            headers={'Content-Type':'application/json'},
            data=json.dumps({'model':model,'prompt':'','stream':False,'keep_alive':keep_alive}).encode())
        try:
            with opener(request,timeout=remaining) as response:
                data=json.load(response)
            results.append({'model':model,'state':'loaded' if isinstance(data,dict) and data.get('done') is True else 'not_confirmed',
                            'model_load_ms':data.get('load_duration',0)/1_000_000 if isinstance(data,dict) and type(data.get('load_duration')) is int else None})
        except (OSError,urllib.error.URLError,ValueError):
            results.append({'model':model,'state':'failed'})
    return results


def main():
    models=os.environ.get('ACP_OLLAMA_WARM_MODELS','llava:13b').split(',')
    models=[model.strip() for model in models if model.strip()]
    timeout=min(300,max(1,float(os.environ.get('ACP_OLLAMA_WARM_TIMEOUT','120'))))
    try:
        results=warm_models(os.environ.get('ACP_OLLAMA_UPSTREAM','http://127.0.0.1:11500'),models,timeout=timeout,
                            keep_alive=os.environ.get('ACP_OLLAMA_KEEP_ALIVE','30m'))
        for result in results:
            print('[ollama-warm] '+json.dumps(result),flush=True)
    except Exception:
        # Availability of the auth gate is independent of optional preloading.
        print('[ollama-warm] startup preload unavailable',flush=True)

if __name__=='__main__':
    main()
