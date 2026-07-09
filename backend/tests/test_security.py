import uuid

import jwt
import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_password_produces_verifiable_but_distinct_hash():
    plain = "correct horse battery staple"
    hashed = hash_password(plain)

    assert hashed != plain
    assert verify_password(plain, hashed)


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("the-real-password")
    assert not verify_password("not-the-real-password", hashed)


def test_access_token_round_trips_user_id_and_role():
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id=user_id, role="credit_officer")

    assert expires_in > 0
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "credit_officer"


def test_decode_access_token_rejects_tampered_token():
    token, _ = create_access_token(user_id=uuid.uuid4(), role="credit_officer")
    header_b64, payload_b64, signature_b64 = token.split(".")

    # Flip a character in the middle of the *payload* segment, not the last
    # character of the signature — the final base64 character of a 32-byte
    # HMAC-SHA256 signature carries unused padding bits, so tampering there
    # is flaky (some byte values decode identically). Changing a payload
    # byte always changes what was signed, so verification reliably fails.
    mid = len(payload_b64) // 2
    flipped_char = "A" if payload_b64[mid] != "A" else "B"
    tampered_payload = payload_b64[:mid] + flipped_char + payload_b64[mid + 1 :]
    tampered = f"{header_b64}.{tampered_payload}.{signature_b64}"

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)
