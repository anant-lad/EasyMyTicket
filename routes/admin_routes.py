import re
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import Optional, List

from src.auth.dependencies import require_admin
from src.auth.password import hash_password
from src.database.db_connection import DatabaseConnection

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ── Pydantic models ────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    user_id: str
    user_name: str
    user_mail: str
    password: str

class UpdateUserRequest(BaseModel):
    user_name: Optional[str] = None
    user_mail: Optional[str] = None
    password: Optional[str] = None

class CreateTechRequest(BaseModel):
    tech_id: str
    tech_name: str
    tech_mail: str
    password: str
    skills: Optional[str] = ""
    is_admin: Optional[bool] = False
    tech_role: Optional[str] = "tech"
    org_id: Optional[str] = None

class UpdateTechRequest(BaseModel):
    tech_name: Optional[str] = None
    tech_mail: Optional[str] = None
    password: Optional[str] = None
    skills: Optional[str] = None
    status: Optional[str] = None
    is_admin: Optional[bool] = None
    tech_role: Optional[str] = None
    org_id: Optional[str] = None

class CreateOrgRequest(BaseModel):
    org_id: str
    org_name: str

class AddMemberRequest(BaseModel):
    member_id: str
    member_type: str  # 'user' or 'tech'

# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(_: dict = Depends(require_admin)):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT user_id, user_name, user_mail, no_tickets_raised, available, org_id FROM user_data ORDER BY user_id"
    )
    return {"users": rows or []}


@router.post("/users", status_code=201)
def create_user(req: CreateUserRequest, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    existing = db.execute_query("SELECT user_id FROM user_data WHERE user_id=%s OR user_mail=%s LIMIT 1",
                                (req.user_id, req.user_mail))
    if existing:
        raise HTTPException(status_code=409, detail="User ID or email already exists")
    db.execute_query(
        "INSERT INTO user_data (user_id, user_name, user_mail, user_password, no_tickets_raised, available) "
        "VALUES (%s,%s,%s,%s,0,TRUE)",
        (req.user_id, req.user_name, req.user_mail, hash_password(req.password)),
        fetch=False,
    )
    return {"message": "User created", "user_id": req.user_id}


@router.put("/users/{user_id}")
def update_user(user_id: str, req: UpdateUserRequest, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    sets, vals = [], []
    if req.user_name is not None:
        sets.append("user_name=%s"); vals.append(req.user_name)
    if req.user_mail is not None:
        sets.append("user_mail=%s"); vals.append(req.user_mail)
    if req.password is not None:
        sets.append("user_password=%s"); vals.append(hash_password(req.password))
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    vals.append(user_id)
    db.execute_query(f"UPDATE user_data SET {', '.join(sets)} WHERE user_id=%s", vals, fetch=False)
    return {"message": "User updated"}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    db.execute_query("DELETE FROM user_data WHERE user_id=%s", (user_id,), fetch=False)


# ── Technicians ────────────────────────────────────────────────────────────────

@router.get("/technicians")
def list_technicians(_: dict = Depends(require_admin)):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT tech_id, tech_name, tech_mail, skills, status, is_admin, "
        "no_tickets_assigned, solved_tickets, current_workload, org_id, tech_role FROM technician_data ORDER BY tech_id"
    )
    return {"technicians": rows or []}


@router.post("/technicians", status_code=201)
def create_technician(req: CreateTechRequest, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    existing = db.execute_query("SELECT tech_id FROM technician_data WHERE tech_id=%s OR tech_mail=%s LIMIT 1",
                                (req.tech_id, req.tech_mail))
    if existing:
        raise HTTPException(status_code=409, detail="Tech ID or email already exists")
    db.execute_query(
        "INSERT INTO technician_data (tech_id, tech_name, tech_mail, tech_password, skills, status, is_admin, tech_role, org_id,"
        "no_tickets_assigned, solved_tickets, current_workload) VALUES (%s,%s,%s,%s,%s,'available',%s,%s,%s,0,0,0)",
        (req.tech_id, req.tech_name, req.tech_mail, hash_password(req.password),
         req.skills, req.is_admin, req.tech_role or "tech", req.org_id),
        fetch=False,
    )
    return {"message": "Technician created", "tech_id": req.tech_id}


@router.put("/technicians/{tech_id}")
def update_technician(tech_id: str, req: UpdateTechRequest, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    sets, vals = [], []
    if req.tech_name is not None:
        sets.append("tech_name=%s"); vals.append(req.tech_name)
    if req.tech_mail is not None:
        sets.append("tech_mail=%s"); vals.append(req.tech_mail)
    if req.password is not None:
        sets.append("tech_password=%s"); vals.append(hash_password(req.password))
    if req.skills is not None:
        sets.append("skills=%s"); vals.append(req.skills)
    if req.status is not None:
        sets.append("status=%s"); vals.append(req.status)
    if req.is_admin is not None:
        sets.append("is_admin=%s"); vals.append(req.is_admin)
    if req.tech_role is not None:
        sets.append("tech_role=%s"); vals.append(req.tech_role)
    if req.org_id is not None:
        sets.append("org_id=%s"); vals.append(req.org_id)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    vals.append(tech_id)
    db.execute_query(f"UPDATE technician_data SET {', '.join(sets)} WHERE tech_id=%s", vals, fetch=False)
    return {"message": "Technician updated"}


@router.delete("/technicians/{tech_id}", status_code=204)
def delete_technician(tech_id: str, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    db.execute_query("DELETE FROM technician_data WHERE tech_id=%s", (tech_id,), fetch=False)


# ── Organizations ──────────────────────────────────────────────────────────────

@router.get("/organizations")
def list_organizations(_: dict = Depends(require_admin)):
    db = DatabaseConnection()
    orgs = db.execute_query("SELECT * FROM organizations ORDER BY org_name") or []
    result = []
    for o in orgs:
        od = dict(o)
        users = db.execute_query(
            "SELECT user_id, user_name, user_mail FROM user_data WHERE org_id=%s", (od["org_id"],)
        ) or []
        techs = db.execute_query(
            "SELECT tech_id, tech_name, tech_mail, tech_role FROM technician_data WHERE org_id=%s", (od["org_id"],)
        ) or []
        od["users"] = [dict(u) for u in users]
        od["technicians"] = [dict(t) for t in techs]
        result.append(od)
    return {"organizations": result}


@router.post("/organizations", status_code=201)
def create_organization(req: CreateOrgRequest, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    existing = db.execute_query("SELECT org_id FROM organizations WHERE org_id=%s LIMIT 1", (req.org_id,))
    if existing:
        raise HTTPException(status_code=409, detail="Organization ID already exists")
    db.execute_query(
        "INSERT INTO organizations (org_id, org_name) VALUES (%s,%s)",
        (req.org_id, req.org_name), fetch=False,
    )
    return {"message": "Organization created", "org_id": req.org_id}


@router.post("/organizations/{org_id}/members", status_code=200)
def add_member_to_org(org_id: str, req: AddMemberRequest, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    org = db.execute_query("SELECT org_id FROM organizations WHERE org_id=%s LIMIT 1", (org_id,))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if req.member_type == "user":
        db.execute_query("UPDATE user_data SET org_id=%s WHERE user_id=%s", (org_id, req.member_id), fetch=False)
    elif req.member_type == "tech":
        db.execute_query("UPDATE technician_data SET org_id=%s WHERE tech_id=%s", (org_id, req.member_id), fetch=False)
    else:
        raise HTTPException(status_code=400, detail="member_type must be 'user' or 'tech'")

    return {"message": f"{req.member_type} {req.member_id} added to organization {org_id}"}


@router.delete("/organizations/{org_id}/members/{member_type}/{member_id}", status_code=200)
def remove_member_from_org(org_id: str, member_type: str, member_id: str, _: dict = Depends(require_admin)):
    """Remove a user or technician from an organization (sets their org_id to NULL)."""
    db = DatabaseConnection()
    if member_type == "user":
        db.execute_query(
            "UPDATE user_data SET org_id=NULL WHERE user_id=%s AND org_id=%s",
            (member_id, org_id), fetch=False,
        )
    elif member_type == "tech":
        db.execute_query(
            "UPDATE technician_data SET org_id=NULL WHERE tech_id=%s AND org_id=%s",
            (member_id, org_id), fetch=False,
        )
    else:
        raise HTTPException(status_code=400, detail="member_type must be 'user' or 'tech'")
    return {"message": f"{member_type} {member_id} removed from organization {org_id}"}


@router.delete("/organizations/{org_id}", status_code=200)
def delete_organization(org_id: str, _: dict = Depends(require_admin)):
    """Delete an organization and unset org_id for all its members."""
    db = DatabaseConnection()
    org = db.execute_query("SELECT org_id FROM organizations WHERE org_id=%s LIMIT 1", (org_id,))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    # Unlink all members first
    db.execute_query("UPDATE user_data SET org_id=NULL WHERE org_id=%s", (org_id,), fetch=False)
    db.execute_query("UPDATE technician_data SET org_id=NULL WHERE org_id=%s", (org_id,), fetch=False)
    db.execute_query("DELETE FROM organizations WHERE org_id=%s", (org_id,), fetch=False)
    return {"message": f"Organization {org_id} deleted"}
