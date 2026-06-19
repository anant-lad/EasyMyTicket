from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt

from src.config import Config

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_access_token(subject: str, email: str, role: str, name: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": subject,
        "email": email,
        "role": role,
        "name": name,
        "exp": expire,
    }
    return jwt.encode(payload, Config.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return None
