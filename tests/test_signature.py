import hashlib
import hmac

from recoup.ingest.signature import verify_signature

SECRET = "whsec_test_123"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_accepts_a_valid_signature():
    body = b'{"event":"subscription.halted","payload":{}}'
    assert verify_signature(body, _sign(body), SECRET) is True


def test_rejects_a_tampered_body():
    body = b'{"event":"subscription.halted","payload":{}}'
    sig = _sign(body)
    assert verify_signature(b'{"event":"subscription.charged"}', sig, SECRET) is False


def test_rejects_a_wrong_secret():
    body = b'{"event":"subscription.halted"}'
    assert verify_signature(body, _sign(body, "wrong"), SECRET) is False


def test_key_order_matters_which_is_why_we_use_raw_bytes():
    # Same JSON object, different serialisation. Signatures must differ.
    a = b'{"a":1,"b":2}'
    b = b'{"b":2,"a":1}'
    assert _sign(a) != _sign(b)
    assert verify_signature(b, _sign(a), SECRET) is False


def test_rejects_malformed_signature_without_raising():
    body = b"{}"
    assert verify_signature(body, "not-hex", SECRET) is False
    assert verify_signature(body, "", SECRET) is False
