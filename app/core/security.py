#!/usr/bin/env python
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict
import bcrypt
from jwt import encode as jwt_encode, decode as jwt_decode
from jwt.exceptions import PyJWTError as JWTError
from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its bcrypt hash (tanpa passlib)."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generate bcrypt hash for a plain password (tanpa passlib)."""
    pw_bytes = password.encode("utf-8")[:72]  # batas 72 byte bcrypt
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt_encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a signed JWT token."""
    try:
        payload = jwt_decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None