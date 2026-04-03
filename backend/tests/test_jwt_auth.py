import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.auth_middleware import AuthMiddleware
from services.jwt_validator import JWTValidator


def _generate_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_validator(public_key):
    validator = JWTValidator()
    validator._jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
    )
    return validator


def _make_token(private_key, *, headers=None, payload_overrides=None):
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers or {"kid": "test-key"})


def _protected_app():
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/private")
    async def private():
        return {"ok": True}

    return app


def test_jwt_valid_token_passes():
    private_key = _generate_private_key()
    validator = _make_validator(private_key.public_key())
    token = _make_token(private_key)

    payload = validator.validate(token)

    assert payload is not None
    assert payload["sub"] == "user-123"


def test_jwt_expired_token_fails():
    private_key = _generate_private_key()
    validator = _make_validator(private_key.public_key())
    token = _make_token(private_key, payload_overrides={"exp": int(time.time()) - 60})

    assert validator.validate(token) is None


def test_jwt_invalid_signature_fails():
    trusted_private_key = _generate_private_key()
    attacker_private_key = _generate_private_key()
    validator = _make_validator(trusted_private_key.public_key())
    token = _make_token(attacker_private_key)

    assert validator.validate(token) is None


def test_jwt_missing_claims_fail():
    private_key = _generate_private_key()
    validator = _make_validator(private_key.public_key())
    token = _make_token(private_key, payload_overrides={"sub": None})
    payload = jwt.decode(
        token,
        options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
        algorithms=["RS256"],
    )
    payload.pop("sub", None)
    token_without_sub = jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key"})

    assert validator.validate(token_without_sub) is None


def test_jwt_crit_header_fails():
    private_key = _generate_private_key()
    validator = _make_validator(private_key.public_key())
    token = _make_token(
        private_key,
        headers={
            "kid": "test-key",
            "crit": ["custom-claim"],
            "custom-claim": "must-be-understood",
        },
    )

    assert validator.validate(token) is None


def test_auth_middleware_accepts_valid_token_and_rejects_tampered_token(monkeypatch):
    private_key = _generate_private_key()
    validator = _make_validator(private_key.public_key())
    valid_token = _make_token(private_key)
    header, payload, signature = valid_token.split(".")
    first_char = signature[0]
    replacement = "A" if first_char != "A" else "B"
    tampered_token = f"{header}.{payload}.{replacement}{signature[1:]}"

    async def _ensure_user_exists(*_args, **_kwargs):
        return None

    from services import auth as auth_module

    monkeypatch.setattr(auth_module.jwt_validator, "_jwks_client", validator._jwks_client)
    monkeypatch.setattr(auth_module.auth_service, "ensure_user_exists", _ensure_user_exists)

    client = TestClient(_protected_app())

    valid_response = client.get("/private", headers={"Authorization": f"Bearer {valid_token}"})
    invalid_response = client.get("/private", headers={"Authorization": f"Bearer {tampered_token}"})

    assert valid_response.status_code == 200
    assert valid_response.json() == {"ok": True}
    assert invalid_response.status_code == 401
    assert invalid_response.json()["error"] == "invalid_token"
