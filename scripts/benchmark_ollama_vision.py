#!/usr/bin/env python3
"""Replay-first model-load versus inference benchmark; never calls a paid provider.

Default fixture values are synthetic controls, not performance claims. Live mode
is explicit and loopback-only, uses one synthetic image, and never unloads models.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))
from ollama_runtime import keep_alive, timings

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/ollama_benchmark/replay.json'
# Fixed 32×32 blue-square PNG control; meaningful quality evaluation is separate.
IMAGE=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAO0lEQVR4nO3RQREAMAjEwKNWaq2yEVMJ4cMvK+CYCXVfZ9NZXY8HBvwBMhEyETIRMhEyETIRMhEyUcgHXg8Bo52J/v4AAAAASUVORK5CYII=')
PROMPT='Describe only the visible content of this synthetic image in one sentence.'


def summarize(record):
    samples=record.get('samples')
    if not isinstance(samples,list) or not samples:
        raise ValueError('At least one recorded sample is required')
    rows=[]
    for sample in samples:
        if not isinstance(sample,dict) or not isinstance(sample.get('response'),dict):
            raise ValueError('Every sample requires a recorded Ollama response')
        response=sample['response']
        rows.append({'phase':sample.get('phase','observed'), 'elapsed_ms':sample.get('elapsed_ms'),
                     'completed':response.get('done') is True,
                     'nonempty':isinstance(response.get('response'),str) and bool(response['response'].strip()),
                     'truncated':response.get('done_reason')=='length',
                     **timings(response)})
    phases={}
    for phase in dict.fromkeys(row['phase'] for row in rows):
        group=[row for row in rows if row['phase']==phase]
        metrics={}
        for key in ['elapsed_ms','total_ms','model_load_ms','prompt_eval_ms','inference_ms','output_tokens_per_second']:
            values=[row[key] for row in group if type(row.get(key)) in (int,float)]
            if values: metrics[key+'_median']=round(statistics.median(values),3)
        phases[phase]={'samples':len(group),**metrics}
    return {'mode':'synthetic_replay' if record.get('synthetic') is True else record.get('mode','recorded_replay'),
            'model':record.get('model'), 'samples':rows, 'phases':phases,
            'note':'Model-load time, prompt evaluation and token inference are separate observations. First observed does not prove a forced cold start. No remediation quality or accessibility pass is inferred.'}


def live_local(base_url, model, repetitions=3, timeout=120, opener=urllib.request.urlopen, clock=time.monotonic):
    parsed=urlparse(base_url)
    if parsed.scheme!='http' or parsed.hostname not in {'localhost','127.0.0.1','::1'} or parsed.username or parsed.password:
        raise ValueError('Live benchmarking requires an unauthenticated loopback HTTP endpoint')
    if not 1<=repetitions<=10 or not 0<timeout<=300:
        raise ValueError('Repetitions must be 1–10 and timeout at most 300 seconds')
    samples=[]
    deadline=clock()+timeout
    for index in range(repetitions):
        remaining=deadline-clock()
        if remaining<=0: raise TimeoutError('Benchmark deadline exhausted')
        request=urllib.request.Request(base_url.rstrip('/')+'/api/generate',method='POST',headers={'Content-Type':'application/json'},
            data=json.dumps({'model':model,'prompt':PROMPT,'images':[base64.b64encode(IMAGE).decode()],
                             'stream':False,'keep_alive':keep_alive(),'options':{'temperature':0,'num_predict':100}}).encode())
        started=clock()
        with opener(request,timeout=remaining) as response: data=json.load(response)
        samples.append({'phase':'first_observed' if index==0 else 'repeated','elapsed_ms':round((clock()-started)*1000,3),'response':data})
    return {'mode':'live_local_synthetic','model':model,'samples':samples,
            'input_sha256':hashlib.sha256(PROMPT.encode()+IMAGE).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records',type=Path,default=FIXTURE)
    parser.add_argument('--live-local',help='Explicit loopback-only synthetic benchmark; never unloads a model')
    parser.add_argument('--model',default='llava:13b')
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    record=live_local(args.live_local,args.model,args.repetitions,args.timeout) if args.live_local else json.loads(args.records.read_text())
    output=summarize(record)
    encoded=json.dumps(output,indent=2,allow_nan=False)+'\n'
    if args.output: args.output.write_text(encoded)
    else: print(encoded,end='')
if __name__=='__main__':main()
