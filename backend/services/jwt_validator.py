"""
Services — JWT Validator

Verifies Supabase JWT tokens locally using JWKS (RS256).
Fetches public signing keys from Supabase's well-known JWKS endpoint.
Keys are cached automatically by PyJWKClient (default lifespan: 300s).
"""

import time
import structlog

import jwt as pyjwt
from jwt import PyJWKClient

from config.settings import settings

logger = structlog.get_logger("equated.services.jwt_validator")


class JWTValidator:
    """
    Verifies Supabase JWTs using RS256 with JWKS public keys.

    Public keys are fetched from:
        {SUPABASE_URL}/auth/v1/.well-known/jwks.json

    Verification steps:
      1. Fetch signing key from JWKS endpoint (cached)
      2. Verify RS256 signature against public key
      3. Verify 'exp' claim (reject expired tokens)
      4. Verify 'aud' claim matches 'authenticated'
      5. Extract 'sub' claim as user_id
    """

    def __init__(self):
        self._jwks_client: PyJWKClient | None = None
        if settings.SUPABASE_URL:
            jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
            self._jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=300)
            logger.info("jwt_validator_init", jwks_url=jwks_url)

    @property
    def is_configured(self) -> bool:
        """Check if JWKS client is ready for token verification."""
        return self._jwks_client is not None

    def validate(self, token: str) -> dict | None:
        """
        Decode and verify a JWT using JWKS public keys (RS256).
        Returns the payload dict or None if invalid.
        """
        if not self._jwks_client:
            logger.warning("jwt_validator_not_configured")
            return None

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)

            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience="authenticated",
                options={
                    "verify_exp": True,
                    "verify_aud": True,
                    "require": ["sub", "exp", "aud"],
                },
            )
            return payload
        except pyjwt.ExpiredSignatureError:
            logger.info("jwt_expired")
            return None
        except pyjwt.InvalidAudienceError:
            logger.warning("jwt_invalid_audience")
            return None
        except pyjwt.InvalidTokenError as e:
            logger.warning("jwt_invalid", error=str(e))
            return None
        except Exception as e:
            logger.error("jwt_jwks_error", error=str(e))
            return None

    def get_user_id(self, token: str) -> str | None:
        """Decode token and extract the user_id (sub claim)."""
        payload = self.validate(token)
        if payload:
            return payload.get("sub")
        return None

    def get_user_role(self, token: str) -> str | None:
        """Extract the user role from the token."""
        payload = self.validate(token)
        if payload:
            return payload.get("role", "authenticated")
        return None

    def is_token_expiring_soon(self, token: str, threshold_seconds: int = 300) -> bool:
        """Check if a token will expire within the given threshold."""
        payload = self.validate(token)
        if not payload:
            return True
        exp = payload.get("exp", 0)
        return (exp - time.time()) < threshold_seconds


# Singleton
jwt_validator = JWTValidator()
