from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr

from src.auth.password import verify_password
from src.auth.jwt_handler import create_access_token
from src.auth.dependencies import get_current_user
from src.database.db_connection import DatabaseConnection

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    id: str
    name: str
    email: str


@router.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def login(req: LoginRequest):
    db = DatabaseConnection()

    # Try technician first
    tech_rows = db.execute_query(
        "SELECT tech_id, tech_name, tech_mail, tech_password, is_admin, tech_role FROM technician_data WHERE tech_mail = %s LIMIT 1",
        (req.email,),
    )
    if tech_rows:
        tech = tech_rows[0]
        if not tech.get("tech_password"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Password not set for this account")
        if not verify_password(req.password, tech["tech_password"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        if tech.get("is_admin"):
            role = "admin"
        elif tech.get("tech_role") == "tech_lead":
            role = "tech_lead"
        else:
            role = "tech"
        token = create_access_token(tech["tech_id"], tech["tech_mail"], role, tech["tech_name"])
        return LoginResponse(
            access_token=token, role=role,
            id=tech["tech_id"], name=tech["tech_name"], email=tech["tech_mail"],
        )

    # Try user
    user_rows = db.execute_query(
        "SELECT user_id, user_name, user_mail, user_password FROM user_data WHERE user_mail = %s LIMIT 1",
        (req.email,),
    )
    if user_rows:
        user = user_rows[0]
        if not user.get("user_password"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Password not set for this account")
        if not verify_password(req.password, user["user_password"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        token = create_access_token(user["user_id"], user["user_mail"], "user", user["user_name"])
        return LoginResponse(
            access_token=token, role="user",
            id=user["user_id"], name=user["user_name"], email=user["user_mail"],
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")


@router.get("/api/auth/me", tags=["auth"])
def me(payload: dict = Depends(get_current_user)):
    return {
        "id":    payload["sub"],
        "email": payload["email"],
        "role":  payload["role"],
        "name":  payload["name"],
    }
