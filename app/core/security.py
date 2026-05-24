from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import Settings


def _prepare_password(password: str) -> bytes:
    return sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(_prepare_password(plain_password), hashed_password.encode("utf-8"))


def create_access_token(subject: UUID, settings: Settings) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        if subject is None:
            raise ValueError("Missing token subject")
        return UUID(subject)
    except (JWTError, ValueError) as exc:
        raise InvalidTokenError from exc


class InvalidTokenError(Exception):
    """Raised when an access token cannot be decoded or validated."""
