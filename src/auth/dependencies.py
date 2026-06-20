from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.jwt_handler import decode_token

_bearer = HTTPBearer(auto_error=False)


def _get_token(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[dict]:
    if not creds:
        return None
    return decode_token(creds.credentials)


def get_current_user(payload: Optional[dict] = Depends(_get_token)) -> dict:
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return payload


def require_tech(payload: dict = Depends(get_current_user)) -> dict:
    if payload.get("role") not in ("tech", "tech_lead", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Technician access required")
    return payload


def require_tech_lead(payload: dict = Depends(get_current_user)) -> dict:
    if payload.get("role") not in ("tech_lead", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tech Lead access required")
    return payload


def require_admin(payload: dict = Depends(get_current_user)) -> dict:
    if payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return payload


def optional_user(payload: Optional[dict] = Depends(_get_token)) -> Optional[dict]:
    return payload
