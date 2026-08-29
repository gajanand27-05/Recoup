"""HMAC verification for Razorpay webhooks.

Razorpay signs the RAW request body with HMAC-SHA256 using the webhook secret
and sends the hex digest in the `X-Razorpay-Signature` header.

Source: https://razorpay.com/docs/webhooks/validate-test/ (retrieved 2026-08-28)
The docs are explicit: "Do not parse or cast the webhook request body."
"""

import hashlib
import hmac


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Return True iff `signature` is a valid Razorpay HMAC for `raw_body`.

    Uses a constant-time comparison. Never raises — malformed input is False.
    """
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
