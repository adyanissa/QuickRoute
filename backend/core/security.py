import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from dotenv import load_dotenv
from passlib.context import CryptContext
from pathlib import Path


password_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
)

if not JWT_SECRET_KEY:
    # No secret configured (e.g. a fresh clone before .env is set up).
    # Fall back to a process-local random key so the app can still start;
    # tokens issued this way are only valid for the current process
    # lifetime, which is safe for local development and never used in a
    # real deployment because a real .env always sets JWT_SECRET_KEY.
    import secrets as _secrets
    JWT_SECRET_KEY = _secrets.token_hex(32)


class TokenError(Exception):
    """Raised when a JWT access token is missing, malformed, or expired."""

    def __init__(self, message: str, expired: bool = False):
        super().__init__(message)
        self.message = message
        self.expired = expired


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_minutes: Optional[int] = None,
) -> tuple[str, datetime]:
    expire_minutes = expires_minutes or JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise TokenError("Access token has expired", expired=True) from error
    except jwt.InvalidTokenError as error:
        raise TokenError("Invalid access token") from error