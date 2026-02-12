import hashlib
import hmac

from webhook_receiver.app import verify_signature


def test_verify_signature_success() -> None:
    body = b'{"hello":"world"}'
    secret = b"topsecret"
    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    assert verify_signature(body, signature, secret) is True


def test_verify_signature_failure() -> None:
    body = b'{"hello":"world"}'
    secret = b"topsecret"
    bad_signature = "sha256=deadbeef"

    assert verify_signature(body, bad_signature, secret) is False
