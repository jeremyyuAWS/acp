"""Reject obvious model non-answers, without pretending to verify rewrite meaning."""
import re

NON_ANSWER_REASON = 'AI rewrite returned a refusal or request for source text; review or author a replacement instruction'

# Match conversational model requests/refusals, not ordinary document instructions
# such as "Please provide your patient ID" or quoted form labels.
_NON_ANSWER = tuple(re.compile(pattern, re.I) for pattern in (
    r"^i (?:don't|do not|can't|cannot) (?:see|find|have|access)\b.{0,180}\b(?:original|source|your message|provided text)\b",
    r"^(?:i'm|i am) sorry\b.{0,100}\b(?:can't|cannot|unable)\b.{0,80}\b(?:assist|help|rewrite|rephrase|provide)\b",
    r"^as an ai(?: language)? model\b",
    r"^please (?:provide|share|paste) (?:the|your) (?:original|source|step) (?:text|instruction|sentence|passage|content)\b",
    r"^(?:could|can|would) you (?:provide|share|paste) (?:the|your) (?:original|source) (?:text|instruction|sentence|passage|content)\b",
    r"^i (?:need|require)\b.{0,100}\b(?:original|source) (?:text|instruction|sentence|passage|content)\b",
))

_WHOLE_FENCE = re.compile(r'\A(`{3,}|~{3,})[\w+-]*[ \t]*\r?\n(.*?)\r?\n\1[ \t]*\Z', re.S)


def _match_text(value):
    # Transport wrappers are removed only for rejection matching. The approved
    # document value itself is never modified, including legitimate quotations.
    text = value.strip()
    for _ in range(3):
        fenced = _WHOLE_FENCE.fullmatch(text)
        if fenced:
            text = fenced[2].strip()
        elif len(text) >= 2 and (text[0], text[-1]) in {('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’'), ('`', '`')}:
            text = text[1:-1].strip()
        else:
            break
    return text


def sensory_non_answer_reason(value):
    if not isinstance(value, str) or not value.strip():
        return NON_ANSWER_REASON
    normalized = re.sub(r'\s+', ' ', _match_text(value)).replace('’', "'").replace('‘', "'")
    return NON_ANSWER_REASON if not normalized or any(pattern.search(normalized) for pattern in _NON_ANSWER) else None
