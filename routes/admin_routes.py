import re
import uuid
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import Optional, List

from src.auth.dependencies import require_admin
from src.auth.password import hash_password
from src.database.db_connection import DatabaseConnection


def _gen_api_key() -> str:
    return "emt_" + uuid.uuid4().hex

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
    api_key = _gen_api_key()
    db.execute_query(
        "INSERT INTO user_data (user_id, user_name, user_mail, user_password, no_tickets_raised, available, agent_api_key) "
        "VALUES (%s,%s,%s,%s,0,TRUE,%s)",
        (req.user_id, req.user_name, req.user_mail, hash_password(req.password), api_key),
        fetch=False,
    )
    return {"message": "User created", "user_id": req.user_id, "agent_api_key": api_key}


@router.get("/users/{user_id}/agent-key")
def get_user_agent_key(user_id: str, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    rows = db.execute_query("SELECT agent_api_key FROM user_data WHERE user_id=%s LIMIT 1", (user_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id, "agent_api_key": rows[0]["agent_api_key"]}


@router.post("/users/{user_id}/regenerate-agent-key")
def regenerate_user_agent_key(user_id: str, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    rows = db.execute_query("SELECT user_id FROM user_data WHERE user_id=%s LIMIT 1", (user_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    new_key = _gen_api_key()
    db.execute_query("UPDATE user_data SET agent_api_key=%s WHERE user_id=%s", (new_key, user_id), fetch=False)
    return {"user_id": user_id, "agent_api_key": new_key}


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
    api_key = _gen_api_key()
    db.execute_query(
        "INSERT INTO technician_data (tech_id, tech_name, tech_mail, tech_password, skills, status, is_admin, tech_role, org_id,"
        "no_tickets_assigned, solved_tickets, current_workload, agent_api_key) VALUES (%s,%s,%s,%s,%s,'available',%s,%s,%s,0,0,0,%s)",
        (req.tech_id, req.tech_name, req.tech_mail, hash_password(req.password),
         req.skills, req.is_admin, req.tech_role or "tech", req.org_id, api_key),
        fetch=False,
    )
    return {"message": "Technician created", "tech_id": req.tech_id, "agent_api_key": api_key}


@router.get("/technicians/{tech_id}/agent-key")
def get_tech_agent_key(tech_id: str, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    rows = db.execute_query("SELECT agent_api_key FROM technician_data WHERE tech_id=%s LIMIT 1", (tech_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Technician not found")
    return {"tech_id": tech_id, "agent_api_key": rows[0]["agent_api_key"]}


@router.post("/technicians/{tech_id}/regenerate-agent-key")
def regenerate_tech_agent_key(tech_id: str, _: dict = Depends(require_admin)):
    db = DatabaseConnection()
    rows = db.execute_query("SELECT tech_id FROM technician_data WHERE tech_id=%s LIMIT 1", (tech_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Technician not found")
    new_key = _gen_api_key()
    db.execute_query("UPDATE technician_data SET agent_api_key=%s WHERE tech_id=%s", (new_key, tech_id), fetch=False)
    return {"tech_id": tech_id, "agent_api_key": new_key}


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


# ── Technician Profile (admin view) ───────────────────────────────────────────

@router.get("/technicians/{tech_id}/profile", tags=["admin"])
def get_technician_profile(tech_id: str, _: dict = Depends(require_admin)):
    """Return a technician's full profile: info, assigned tickets, attendance history, comments."""
    db = DatabaseConnection()

    tech_rows = db.execute_query(
        "SELECT tech_id, tech_name, tech_mail, skills, status, is_admin, tech_role, org_id, "
        "no_tickets_assigned, solved_tickets, current_workload FROM technician_data WHERE tech_id=%s LIMIT 1",
        (tech_id,),
    )
    if not tech_rows:
        raise HTTPException(status_code=404, detail="Technician not found")
    tech = dict(tech_rows[0])

    # Assigned tickets (last 100)
    ticket_rows = db.execute_query(
        "SELECT ticketnumber, title, status, priority, issuetype, createdate, resolveddatetime "
        "FROM new_tickets WHERE assigned_tech_id=%s ORDER BY createdate DESC LIMIT 100",
        (tech_id,),
    )
    tickets = []
    for t in (ticket_rows or []):
        td = dict(t)
        for k, v in td.items():
            if hasattr(v, "isoformat"):
                td[k] = v.isoformat()
        tickets.append(td)

    # Attendance — last 60 days
    att_rows = db.execute_query(
        "SELECT date, punch_in, punch_out, status, notes FROM technician_attendance "
        "WHERE tech_id=%s ORDER BY date DESC LIMIT 60",
        (tech_id,),
    )
    attendance = []
    STATUS_LABEL_MAP = {
        "present": "Present", "wfh": "WFH", "leave": "Leave",
        "half_day": "Half Day", "absent": "Absent",
    }
    att_summary = {"present": 0, "wfh": 0, "leave": 0, "half_day": 0, "absent": 0}
    for a in (att_rows or []):
        ad = dict(a)
        for k, v in ad.items():
            if hasattr(v, "isoformat"):
                ad[k] = v.isoformat()
        ad["status_label"] = STATUS_LABEL_MAP.get(ad.get("status", ""), ad.get("status", ""))
        attendance.append(ad)
        s = ad.get("status")
        if s in att_summary:
            att_summary[s] += 1

    # Recent comments by this technician (last 50)
    comment_rows = db.execute_query(
        "SELECT tc.id, tc.ticket_number, tc.content, tc.is_internal, tc.created_at, nt.title AS ticket_title "
        "FROM ticket_comments tc "
        "LEFT JOIN new_tickets nt ON nt.ticketnumber = tc.ticket_number "
        "WHERE tc.author_id=%s AND tc.author_type='tech' "
        "ORDER BY tc.created_at DESC LIMIT 50",
        (tech_id,),
    )
    comments = []
    for c in (comment_rows or []):
        cd = dict(c)
        for k, v in cd.items():
            if hasattr(v, "isoformat"):
                cd[k] = v.isoformat()
        comments.append(cd)

    return {
        "tech": tech,
        "tickets": tickets,
        "attendance": attendance,
        "attendance_summary": att_summary,
        "comments": comments,
    }


# ── Knowledge Base ─────────────────────────────────────────────────────────────

@router.post("/kb/update", tags=["admin"])
def update_knowledge_base(_: dict = Depends(require_admin)):
    """Seed the KB from resolved/closed tickets so future agent sessions benefit from past resolutions."""
    import logging
    log = logging.getLogger(__name__)
    try:
        db = DatabaseConnection()
        seeded = db.seed_from_resolved_tickets(limit=500)
        log.info("Admin KB update: seeded %d articles from resolved tickets", seeded)
        return {"success": True, "articles_seeded": seeded}
    except Exception as e:
        log.error("KB update failed: %s", e)
        raise HTTPException(status_code=500, detail=f"KB update failed: {e}")


@router.get("/kb/stats", tags=["admin"])
def kb_stats(_: dict = Depends(require_admin)):
    """Return row counts for the knowledge base by category."""
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT category, COUNT(*) AS cnt FROM linux_troubleshooting_kb GROUP BY category ORDER BY cnt DESC"
    )
    total_rows = db.execute_query("SELECT COUNT(*) AS total FROM linux_troubleshooting_kb")
    total = int(total_rows[0]["total"]) if total_rows else 0
    return {"total": total, "by_category": rows or []}
