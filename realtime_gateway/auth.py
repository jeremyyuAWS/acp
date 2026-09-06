from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class AuthenticationError(ValueError):
    pass


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_token(token: str, secret: str, *, now: int | None = None) -> str:
    """Return the authenticated owner email from a local-only HMAC credential."""

    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(signature)):
            raise AuthenticationError("invalid token signature")
        claims = json.loads(_decode(encoded))
        owner_email = claims["owner_email"]
        expiry = int(claims["exp"])
    except AuthenticationError:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("malformed token") from exc
    if not isinstance(owner_email, str) or not owner_email.strip():
        raise AuthenticationError("missing owner")
    if expiry <= (int(time.time()) if now is None else now):
        raise AuthenticationError("expired token")
    return owner_email
