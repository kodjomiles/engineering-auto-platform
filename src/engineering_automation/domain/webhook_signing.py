"""HMAC signing policy for outbound webhooks."""

from __future__ import annotations

import hashlib
import hmac


def signature_payload(timestamp: int, body: bytes) -> bytes:
    """Build the exact bytes covered by a webhook signature."""

    return str(timestamp).encode("ascii") + b"." + body


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    """Return a conventional SHA-256 signature header value."""

    digest = hmac.new(secret, signature_payload(timestamp, body), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(secret: bytes, timestamp: int, body: bytes, signature: str) -> bool:
    """Compare a supplied signature without leaking timing information."""

    return hmac.compare_digest(sign(secret, timestamp, body), signature)
