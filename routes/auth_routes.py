from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status, Depends
from pydantic import BaseModel

from src.auth.password import verify_password, hash_password
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
    agent_api_key: str = ""
    org_id: str = ""


class RegisterRequest(BaseModel):
    user_id: str
    name: str
    email: str
    password: str


@router.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def login(req: LoginRequest):
    db = DatabaseConnection()

    # Try technician first
    tech_rows = db.execute_query(
        "SELECT tech_id, tech_name, tech_mail, tech_password, is_admin, tech_role, agent_api_key, org_id FROM technician_data WHERE tech_mail = %s LIMIT 1",
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
            agent_api_key=tech.get("agent_api_key") or "",
            org_id=tech.get("org_id") or "",
        )

    # Try user
    user_rows = db.execute_query(
        "SELECT user_id, user_name, user_mail, user_password, agent_api_key, org_id FROM user_data WHERE user_mail = %s LIMIT 1",
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
            agent_api_key=user.get("agent_api_key") or "",
            org_id=user.get("org_id") or "",
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")


@router.post("/api/auth/register", tags=["auth"])
def register(req: RegisterRequest):
    db = DatabaseConnection()

    # Check if email already exists
    existing = db.execute_query(
        "SELECT user_id FROM user_data WHERE user_mail = %s LIMIT 1",
        (req.email,),
    )
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    hashed_pw = hash_password(req.password)
    agent_api_key = "emt_" + uuid4().hex

    db.execute_query(
        "INSERT INTO user_data (user_id, user_name, user_mail, user_password, agent_api_key, no_tickets_raised, available)"
        " VALUES (%s, %s, %s, %s, %s, 0, TRUE)",
        (req.user_id, req.name, req.email, hashed_pw, agent_api_key),
        fetch=False,
    )

    return {
        "user_id": req.user_id,
        "name": req.name,
        "email": req.email,
        "agent_api_key": agent_api_key,
    }


@router.get("/api/auth/agent-key", tags=["auth"])
def get_agent_key(
    regenerate: bool = Query(False),
    payload: dict = Depends(get_current_user),
):
    subject_id = payload["sub"]
    db = DatabaseConnection()

    # Check user_data first
    user_rows = db.execute_query(
        "SELECT user_id, agent_api_key FROM user_data WHERE user_id = %s LIMIT 1",
        (subject_id,),
    )
    if user_rows:
        row = user_rows[0]
        current_key = row.get("agent_api_key") or ""
        if regenerate or not current_key:
            new_key = "emt_" + uuid4().hex
            db.execute_query(
                "UPDATE user_data SET agent_api_key = %s WHERE user_id = %s",
                (new_key, subject_id),
                fetch=False,
            )
            return {"agent_api_key": new_key}
        return {"agent_api_key": current_key}

    # Check technician_data
    tech_rows = db.execute_query(
        "SELECT tech_id, agent_api_key FROM technician_data WHERE tech_id = %s LIMIT 1",
        (subject_id,),
    )
    if tech_rows:
        row = tech_rows[0]
        current_key = row.get("agent_api_key") or ""
        if regenerate or not current_key:
            new_key = "emt_" + uuid4().hex
            db.execute_query(
                "UPDATE technician_data SET agent_api_key = %s WHERE tech_id = %s",
                (new_key, subject_id),
                fetch=False,
            )
            return {"agent_api_key": new_key}
        return {"agent_api_key": current_key}

    raise HTTPException(status_code=404, detail="User not found")


@router.get("/api/auth/me", tags=["auth"])
def me(payload: dict = Depends(get_current_user)):
    db = DatabaseConnection()
    subject_id = payload["sub"]
    role = payload.get("role", "user")
    org_id = ""
    if role in ("tech", "tech_lead", "admin"):
        rows = db.execute_query("SELECT org_id FROM technician_data WHERE tech_id=%s LIMIT 1", (subject_id,))
    else:
        rows = db.execute_query("SELECT org_id FROM user_data WHERE user_id=%s LIMIT 1", (subject_id,))
    if rows:
        org_id = rows[0].get("org_id") or ""
    return {
        "id":     subject_id,
        "email":  payload["email"],
        "role":   role,
        "name":   payload["name"],
        "org_id": org_id,
    }
