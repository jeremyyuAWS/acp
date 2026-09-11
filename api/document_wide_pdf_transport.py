"""Opt-in native PDF transport; retains the strict generator's measured accounting.

Official request contracts:
https://developers.openai.com/api/docs/guides/file-inputs
https://platform.claude.com/docs/en/build-with-claude/pdf-support
No file upload resource is created: exact bounded bytes are sent inline once.
"""
from __future__ import annotations

import base64
import copy
import hashlib
from io import BytesIO

import pikepdf
import pypdf
from llm_waterfall_provider import PreDispatchRejected

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100


def _validate_pdf(request, data):
    if request.manifest.document_format.value != 'pdf':
        raise ValueError('document_wide_native_pdf_only')
    if not isinstance(data, bytes) or not data or len(data) > MAX_PDF_BYTES:
        raise ValueError('document_wide_native_pdf_size_limit')
    if hashlib.sha256(data).hexdigest() != request.manifest.source_sha256:
        raise ValueError('document_wide_native_pdf_hash_mismatch')
    try:
        with pikepdf.open(BytesIO(data), attempt_recovery=False) as pdf:
            if pdf.is_encrypted:
                raise ValueError('encrypted')
            pages = len(pdf.pages)
            if not 0 < pages <= MAX_PDF_PAGES:
                raise ValueError('pages')
            if pdf.check_pdf_syntax():
                raise ValueError('syntax')
        reader = pypdf.PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) != pages:
            raise ValueError('inconsistent pages')
        # Bytes upper-bound ordinary text tokenization; do not silently truncate.
        text_bytes = sum(len((page.extract_text() or '').encode('utf-8')) for page in reader.pages)
    except Exception as exc:
        raise ValueError('document_wide_native_pdf_unreadable_or_limit') from exc
    return pages, text_bytes


class _ResponsesAccountingView:
    """Adapt only response shape, preserving the original HTTP failure and usage.

    StrictTextGenerator remains responsible for model identity, exact usage/cost,
    cache rejection, bounds, and durable attempts. Unknown response shape raises
    after transport so spend stays uncertain rather than becoming a free retry.
    """
    def __init__(self, response):
        self.response = response
        self.status_code = getattr(response, 'status_code', None)

    def raise_for_status(self):
        return self.response.raise_for_status()

    def json(self):
        data = self.response.json()
        usage = data.get('usage')
        if not isinstance(usage, dict):
            raise ValueError('provider usage missing')
        output = data.get('output')
        if not isinstance(output, list) or len(output) != 1 or output[0].get('type') != 'message':
            raise ValueError('expected exactly one response message')
        content = output[0].get('content')
        if not isinstance(content, list) or len(content) != 1:
            raise ValueError('expected exactly one response content block')
        block = content[0]
        if block.get('type') not in ('output_text', 'refusal'):
            raise ValueError('unsupported response content')
        status = data.get('status')
        if status not in ('completed', 'incomplete'):
            raise ValueError('unsupported response status')
        reason = (data.get('incomplete_details') or {}).get('reason')
        if status == 'incomplete' and reason not in ('max_output_tokens', 'content_filter'):
            raise ValueError('unknown incomplete response')
        return {'model': data.get('model'), 'id': data.get('id'),
                'usage': {'prompt_tokens': usage.get('input_tokens'),
                          'completion_tokens': usage.get('output_tokens'),
                          'prompt_tokens_details': usage.get('input_tokens_details'),
                          'completion_tokens_details': usage.get('output_tokens_details')},
                'choices': [{'message': {'content': block.get('text', ''),
                                         'refusal': block.get('refusal') if block['type'] == 'refusal' else None},
                             'finish_reason': 'length' if reason == 'max_output_tokens' else
                                              'content_filter' if reason == 'content_filter' else 'stop'}]}


def native_pdf_transport(generator, request, data, supported_models):
    pages, text_bytes = _validate_pdf(request, data)
    for model in generator.models[:2]:
        spec = generator.specs[model.name]
        spec.validate(generator.clock())
        if spec.plain_text_only or model.name not in supported_models.get(spec.provider, set()):
            raise ValueError('document_wide_native_pdf_model_unavailable')
    encoded = base64.b64encode(data).decode('ascii')
    wrapped = copy.copy(generator)

    def post(endpoint, **kwargs):
        payload = copy.deepcopy(kwargs['json'])
        spec = generator.specs[payload['model']]
        prompt = payload['messages'][0]['content']
        # Existing managed reservation uses the FULL verified context ceiling,
        # not text length. This admission check therefore fits both full-PDF input
        # and output within the already durable reservation before paid HTTP.
        # 8192/page bounds supported models' page image tokens and OCR/framing;
        # extracted text is additionally reserved using its UTF-8 byte count.
        combined = len(prompt.encode('utf-8')) + text_bytes + 8192 * pages + 1024
        if combined + spec.output_token_limit > spec.context_token_limit:
            raise PreDispatchRejected('document_wide_native_pdf_context_limit')
        if spec.provider == 'anthropic':
            payload['messages'][0]['content'] = [
                {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': encoded}},
                {'type': 'text', 'text': prompt}]
            return generator.post(endpoint, **{**kwargs, 'json': payload})
        if not endpoint.endswith('/chat/completions'):
            raise PreDispatchRejected('document_wide_native_pdf_endpoint_unavailable')
        endpoint = endpoint[:-len('/chat/completions')] + '/responses'
        payload = {'model': payload['model'], 'store': False,
                   'max_output_tokens': payload['max_completion_tokens'],
                   'input': [{'role': 'user', 'content': [
                       {'type': 'input_file', 'filename': 'document.pdf',
                        'file_data': 'data:application/pdf;base64,' + encoded},
                       {'type': 'input_text', 'text': prompt}]}]}
        return _ResponsesAccountingView(generator.post(endpoint, **{**kwargs, 'json': payload}))

    wrapped.post = post
    return wrapped
