"""Finite model residency and measured Ollama timings, independent of AI policy."""
import math
import os
import re

DEFAULT_KEEP_ALIVE = '30m'


def keep_alive():
    value = os.environ.get('ACP_OLLAMA_KEEP_ALIVE', DEFAULT_KEEP_ALIVE).strip()
    # Permit explicit unloading, but don't quietly pin models indefinitely or accept
    # arbitrary invalid duration strings. Operations may use a longer finite duration.
    return value if re.fullmatch(r'(?:0|[1-9][0-9]{0,4}(?:ms|s|m|h))', value) else DEFAULT_KEEP_ALIVE


def timings(data):
    result = {}
    for source, destination in [('total_duration', 'total_ms'), ('load_duration', 'model_load_ms'),
                                ('prompt_eval_duration', 'prompt_eval_ms'), ('eval_duration', 'inference_ms')]:
        value = data.get(source)
        if type(value) in (int, float) and 0 <= value <= 2**63-1 and math.isfinite(value):
            result[destination] = round(value / 1_000_000, 3)
    count = data.get('eval_count')
    duration = result.get('inference_ms')
    if type(count) is int and 0 <= count <= 2**31-1 and duration is not None and duration > 0:
        result['output_tokens_per_second'] = round(count * 1000 / duration, 3)
    # A server's actual model-load time is separate from inference. These are
    # observed durations, not guesses that every slow response was a cold start.
    return result
