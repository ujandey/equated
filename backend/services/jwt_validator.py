"""
Services — JWT Validator

Decodes Supabase JWT tokens locally.
Currently skips signature verification (dev mode).
TODO: Re-enable signature verification for production with RS256 public key.
"""

import time
import structlog

import jwt as pyjwt

from config.settings import settings

logger = structlog.get_logger("equated.services.jwt_validator")


class JWTValidator:
    """
    Decodes Supabase JWTs locally.

    Supabase uses RS256 for user access tokens.
    Currently decodes without signature verification for development.

    Verification steps:
      1. Decode accepting RS256 and HS256 (no signature check)
      2. Verify 'exp' claim (reject expired tokens)
      3. Verify 'aud' claim matches 'authenticated'
      4. Extract 'sub' claim as user_id
    """

    def __init__(self):
        self.secret = settings.SUPABASE_JWT_SECRET

    def validate(self, token: str) -> dict | None:
        """
        Decode a JWT and return the payload.
        Returns None if the token is malformed or expired.
        """
        try:
            header = pyjwt.get_unverified_header(token)
            logger.debug("jwt_header", alg=header.get("alg"), typ=header.get("typ"))

            payload = pyjwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": True,
                    "verify_aud": True,
                    "require": ["sub", "exp", "aud"],
                },
                algorithms=["RS256", "HS256"],
                audience="authenticated",
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
