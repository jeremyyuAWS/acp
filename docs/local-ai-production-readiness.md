# Local AI production readiness

A successful request to the public GPU endpoint does not make that endpoint eligible for a Local AI plan. Local AI requires a private/internal endpoint. Keep endpoint provenance and authorization checks aligned; do not allow-list a public Azure hostname as local.

Production's private Ollama service is `acp-ollama`, in `mdk-accessibility-env` (East US). Its HTTPS address is `https://acp-ollama.internal.greenwater-4bf2c997.eastus2.azurecontainerapps.io`. The public GPU service is in a different Container Apps environment in West US; its address cannot be substituted into a local-only plan.

## Operational recovery

1. Verify the private endpoint from the production application network using `/api/tags`. Check both configured model names, rather than treating HTTP 200 as sufficient.
2. Verify text generation and image generation using synthetic inputs. Do not use a customer's document for a connectivity test. The private service image includes `llama3.1:8b` and `moondream`; the public GPU's `llava:13b` configuration does not match it.
3. Keep one private service replica running when predictable plan startup is required. This incurs idle compute usage. With zero minimum replicas, a large model image may take several minutes to pull and start; a quick readiness timeout cannot establish that the service is permanently down.
4. Wait until production has no queued/running jobs before switching shared runtime endpoint/model settings. Set `ai_base_url`, `ai_text_model`, and `ai_vision_model` to the verified private endpoint and models. Record the prior values and the administrative change. Never change AI permission, plan approval, or spending as part of this network repair.
5. Recheck readiness for the exact Local AI policy. Both text and vision models must be available, the endpoint must classify as local, and readiness must be unblocked. Other replicas pick up runtime settings within about 30 seconds; no worker restart is required.
6. If the new endpoint fails, restore the recorded settings, and keep the plan blocked or offer Rules Only. Do not silently fall back to the public GPU for a local-only authorization.

The planner retries a transient timeout or 502/503/504 once, with a three-second metadata-request timeout per attempt. It does not retry denied access, generate content during readiness, or relax local-only admission. Azure container exec rate limits must be respected, including their Retry-After interval.
