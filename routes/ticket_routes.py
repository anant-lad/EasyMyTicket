"""
Ticket creation and intake classification routes
"""
from fastapi import APIRouter, HTTPException, Path, Query, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any, Optional, List
import uuid, logging
import threading as _threading

_PIPELINE_SEM = _threading.Semaphore(4)  # max 4 concurrent LangGraph pipelines
from src.database.db_connection import DatabaseConnection
from src.config import Config
from src.utils.picklist_loader import get_picklist_loader
from src.auth.dependencies import get_current_user, require_tech, require_tech_lead, optional_user

log = logging.getLogger(__name__)

router = APIRouter()

# Lazy database connection (used by non-creation routes)
_db_conn = None

def get_db_connection():
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn



# Pydantic models for request/response
class TicketCreateRequest(BaseModel):
    """Request model for ticket creation"""
    title: str = Field(..., description="Ticket title", min_length=1)
    description: str = Field(..., description="Ticket description", min_length=1)
    user_id: str = Field(..., description="User ID who created the ticket", min_length=1)
    device_id: Optional[str] = Field(None, description="Desktop agent device ID (enables agentic auto-resolve)")
    source: Optional[str] = Field("portal", description="Ticket source (portal, email, api)")
    due_date_time: Optional[str] = Field(
        None,
        description="Due date and time in format: YYYY-MM-DD HH:MM:SS",
        json_schema_extra={"example": "2024-12-10 10:00:00"},
    )
    priority: Optional[str] = Field(None, description="User-provided priority hint (AI may override): Critical, High, Medium, Low, Planning")
    issuetype: Optional[int] = Field(None, description="User-provided issue type hint (AI may override): 4=Hardware, 5=Software, 6=Network, 10=General IT, 26=Other")

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Email not working",
                "description": "I cannot send emails through Outlook. Getting error message 'Connection timeout'",
                "user_id": "user123",
                "device_id": "a1b2c3d4-...",
                "due_date_time": "2024-12-10 10:00:00",
                "priority": "High",
                "issuetype": 5,
            }
        }
    }


class TicketResponse(BaseModel):
    """Response model for ticket creation"""
    success: bool
    ticket_number: str
    ticket_data: Dict[str, Any]
    extracted_metadata: Dict[str, Any]
    classification: Dict[str, Any]
    similar_tickets_found: int
    resolution: Optional[str] = None
    assigned_tech_id: Optional[str] = None


class TicketDetailResponse(BaseModel):
    """Response model for ticket details"""
    success: bool
    ticket: Dict[str, Any]
    ticket_with_labels: Optional[Dict[str, Any]] = None  # Ticket with human-readable labels


class ResolutionResponse(BaseModel):
    """Response model for ticket resolution"""
    success: bool
    ticket_number: str
    resolution: Optional[str] = None
    ticket_title: Optional[str] = None


class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str
    database: Optional[str] = None
    service: Optional[str] = None
    error: Optional[str] = None


class TicketsListResponse(BaseModel):
    """Response model for tickets list"""
    success: bool
    tickets: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool


class GenericResponse(BaseModel):
    """Generic success/failure response"""
    success: bool
    message: str


def _run_pipeline_background(
    ticket_number: str,
    title: str,
    description: str,
    user_id: str,
    source: str,
    device_id: Optional[str],
    due_date_time: Optional[str],
):
    """Run the full LangGraph pipeline in background after ticket is created.

    A module-level semaphore (_PIPELINE_SEM) caps concurrent pipeline runs at 4
    so that burst ticket creation (20+ tickets) does not cause OOM / worker timeout.
    """
    with _PIPELINE_SEM:
        try:
            from src.graph.ticket_graph import process_ticket
            process_ticket(
                title=title,
                description=description,
                user_id=user_id,
                source=source,
                device_id=device_id,
                due_date_time=due_date_time,
                existing_ticket_number=ticket_number,
            )
            log.info("Background pipeline complete for %s", ticket_number)
        except Exception as e:
            log.exception("Background pipeline failed for %s: %s", ticket_number, e)


@router.post("/tickets/create", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket_request: TicketCreateRequest,
    background_tasks: BackgroundTasks,
    device_id: Optional[str] = Query(None, description="Desktop agent device ID (query param — body field takes precedence)"),
    payload: Optional[dict] = Depends(optional_user),
):
    """
    Create a ticket immediately and run the LangGraph pipeline asynchronously.
    Returns ticket_number within ~200ms; classification/assignment happen in background.
    """
    from datetime import timezone

    effective_device_id = ticket_request.device_id or device_id

    # Auto-attach connected agent device for authenticated users
    if not effective_device_id and payload:
        from routes.agent_routes import get_connected_device_for_user
        uid = payload.get("sub")
        if uid:
            effective_device_id = get_connected_device_for_user(uid)
            if effective_device_id:
                log.info("Auto-attached device %s for user %s", effective_device_id, uid)

    if ticket_request.due_date_time:
        try:
            datetime.strptime(ticket_request.due_date_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid due_date_time format. Use: YYYY-MM-DD HH:MM:SS")

    try:
        # ── Step 1: persist ticket immediately ──────────────────────────────
        db_conn = get_db_connection()
        ticket_number = f"TKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        extra_cols = ""
        extra_vals: list = []
        if effective_device_id:
            extra_cols += ", device_id"
            extra_vals.append(effective_device_id)
        if ticket_request.priority:
            extra_cols += ", priority"
            extra_vals.append(ticket_request.priority)
        if ticket_request.issuetype is not None:
            extra_cols += ", issuetype"
            extra_vals.append(str(ticket_request.issuetype))
        db_conn.execute_query(
            f"INSERT INTO new_tickets (ticketnumber, title, description, user_id, status, createdate, source{extra_cols})"
            f" VALUES (%s,%s,%s,%s,'Open',NOW(),%s{', %s' * len(extra_vals)}) ON CONFLICT (ticketnumber) DO NOTHING",
            (ticket_number, ticket_request.title, ticket_request.description,
             ticket_request.user_id, ticket_request.source or "portal", *extra_vals),
            fetch=False,
        )
        log.info("Ticket %s created instantly, pipeline queued", ticket_number)

        # ── Step 2: queue pipeline in background ────────────────────────────
        background_tasks.add_task(
            _run_pipeline_background,
            ticket_number,
            ticket_request.title,
            ticket_request.description,
            ticket_request.user_id,
            ticket_request.source or "portal",
            effective_device_id,
            ticket_request.due_date_time,
        )

        return TicketResponse(
            success=True,
            ticket_number=ticket_number,
            ticket_data={
                "title": ticket_request.title,
                "description": ticket_request.description,
                "user_id": ticket_request.user_id,
                "createdate": datetime.now().isoformat(),
                "duedatetime": ticket_request.due_date_time,
                "can_auto_resolve": False,
                "agent_connected": False,
                "agent_task_id": None,
                "pipeline_status": "processing",
            },
            extracted_metadata={},
            classification={},
            similar_tickets_found=0,
            resolution=None,
            assigned_tech_id=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get("/tickets", response_model=TicketsListResponse)
async def get_all_tickets(
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of tickets to return"),
    offset: int = Query(0, ge=0, description="Number of tickets to skip"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'Open', 'Closed', 'In Progress')"),
    priority: Optional[str] = Query(None, description="Filter by priority (e.g., 'High', 'Medium', 'Low')"),
    issuetype: Optional[str] = Query(None, description="Filter by issue type"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    order_by: str = Query('createdate', description="Column to order by (createdate, duedatetime, ticketnumber, title, status, priority, issuetype)"),
    order_direction: str = Query('DESC', pattern='^(ASC|DESC)$', description="Order direction: ASC or DESC")
):
    """
    Get all tickets with pagination, filtering, and sorting
    
    Query Parameters:
        - limit: Maximum number of tickets to return (1-1000, default: 50)
        - offset: Number of tickets to skip for pagination (default: 0)
        - status: Filter by ticket status (optional)
        - priority: Filter by priority level (optional)
        - issuetype: Filter by issue type (optional)
        - user_id: Filter by user ID (optional)
        - order_by: Column to sort by (default: 'createdate')
        - order_direction: Sort direction 'ASC' or 'DESC' (default: 'DESC')
    
    Returns:
        TicketsListResponse with list of tickets and pagination info
    """
    try:
        db_conn = get_db_connection()
        
        result = db_conn.get_all_tickets(
            limit=limit,
            offset=offset,
            status=status,
            priority=priority,
            issuetype=issuetype,
            user_id=user_id,
            order_by=order_by,
            order_direction=order_direction
        )
        
        # Fetch tech names for all assigned_tech_ids in one query
        tech_ids = list({t.get("assigned_tech_id") for t in (result["tickets"] or []) if t.get("assigned_tech_id")})
        tech_name_map: dict = {}
        if tech_ids:
            placeholders = ",".join(["%s"] * len(tech_ids))
            trows = db_conn.execute_query(
                f"SELECT tech_id, tech_name FROM technician_data WHERE tech_id IN ({placeholders})",
                tuple(tech_ids),
            )
            if trows:
                tech_name_map = {r["tech_id"]: r["tech_name"] for r in trows}

        pl = get_picklist_loader()
        _label_fields = ["issuetype", "subissuetype", "ticketcategory", "tickettype", "priority", "status"]

        tickets = []
        for ticket in result['tickets']:
            ticket_dict = dict(ticket)
            for key, value in ticket_dict.items():
                if isinstance(value, datetime):
                    ticket_dict[key] = value.isoformat()
            # Enrich with human-readable labels
            for field in _label_fields:
                if ticket_dict.get(field):
                    lbl = pl.get_label(field, str(ticket_dict[field]))
                    if lbl:
                        ticket_dict[f"{field}_label"] = lbl
            # Enrich with technician name
            if ticket_dict.get("assigned_tech_id"):
                ticket_dict["assigned_tech_name"] = tech_name_map.get(ticket_dict["assigned_tech_id"])
            tickets.append(ticket_dict)

        return TicketsListResponse(
            success=True,
            tickets=tickets,
            total=result['total'],
            limit=result['limit'],
            offset=result['offset'],
            has_more=result['has_more']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving tickets: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


# ── Static sub-routes must appear BEFORE {ticket_number} wildcard ─────────────
# These are defined here as stubs that call the real handlers below.
# Real implementations are at the bottom of this file; they work because FastAPI
# resolves by registration order, so these registrations win over {ticket_number}.

@router.get("/tickets/my", tags=["tickets"], include_in_schema=False)
def _my_tickets_stub(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    payload: dict = Depends(get_current_user),
):
    return _get_my_tickets_impl(status_filter, limit, payload)


@router.get("/tickets/similar", tags=["tickets"], include_in_schema=False)
def _similar_tickets_stub(
    title: str = Query(...),
    description: str = Query(""),
    limit: int = Query(5, ge=1, le=20),
    payload: dict = Depends(require_tech),
):
    return _get_similar_tickets_impl(title, description, limit, payload)


@router.get("/tickets/technicians", tags=["tickets"], include_in_schema=False)
def _technicians_stub(payload: dict = Depends(require_tech)):
    return _list_technicians_impl(payload)


@router.get("/tickets/{ticket_number}", response_model=TicketDetailResponse)
async def get_ticket(ticket_number: str = Path(..., description="The ticket number to retrieve")):
    """
    Get complete ticket details by ticket number with full information including labels
    
    Args:
        ticket_number: The ticket number to retrieve
    
    Returns:
        TicketDetailResponse with complete ticket details including human-readable labels
    """
    try:
        db_conn = get_db_connection()
        query = """
            SELECT t.*, td.tech_name AS assigned_tech_name,
                   EXISTS(SELECT 1 FROM agent_sessions WHERE ticket_number = t.ticketnumber) AS has_agent_session,
                   a.session_id AS agent_session_id,
                   a.status AS agent_session_status,
                   a.oversight_tech_id,
                   a.oversight_tech_name,
                   ot.tech_mail AS oversight_tech_mail
            FROM new_tickets t
            LEFT JOIN technician_data td ON td.tech_id = t.assigned_tech_id
            LEFT JOIN LATERAL (
                SELECT session_id, status, oversight_tech_id, oversight_tech_name
                FROM agent_sessions WHERE ticket_number = t.ticketnumber
                ORDER BY created_at DESC LIMIT 1
            ) a ON TRUE
            LEFT JOIN technician_data ot ON ot.tech_id = a.oversight_tech_id
            WHERE t.ticketnumber = %s
        """
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail='Ticket not found'
            )
        
        # Convert datetime objects to strings for JSON serialization
        ticket = dict(results[0])
        ticket_with_labels = ticket.copy()
        
        # Convert datetime objects to strings
        for key, value in ticket.items():
            if isinstance(value, datetime):
                ticket[key] = value.isoformat()
                ticket_with_labels[key] = value.isoformat()
        
        # Add human-readable labels using picklist
        picklist_loader = get_picklist_loader()
        label_fields = {
            'issuetype': 'issuetype',
            'subissuetype': 'subissuetype',
            'ticketcategory': 'ticketcategory',
            'tickettype': 'tickettype',
            'priority': 'priority',
            'status': 'status',
            'source': 'source',
            'queueid': 'queueid',
            'creatortype': 'creatortype',
            'lastactivitypersontype': 'lastactivitypersontype',
            'servicelevelagreementid': 'servicelevelagreementid'
        }
        
        for field, picklist_field in label_fields.items():
            if field in ticket and ticket[field]:
                value = str(ticket[field])
                label = picklist_loader.get_label(picklist_field, value)
                if label:
                    ticket_with_labels[f'{field}_label'] = label
        
        return TicketDetailResponse(
            success=True,
            ticket=ticket,
            ticket_with_labels=ticket_with_labels
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving ticket: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


@router.get("/tickets/{ticket_number}/resolution", response_model=ResolutionResponse)
async def get_ticket_resolution(ticket_number: str = Path(..., description="The ticket number to get resolution for")):
    """
    Get resolution steps for a specific ticket
    
    Args:
        ticket_number: The ticket number to get resolution for
    
    Returns:
        ResolutionResponse with resolution steps
    """
    try:
        db_conn = get_db_connection()
        query = """
            SELECT ticketnumber, title, resolution
            FROM new_tickets
            WHERE ticketnumber = %s
        """
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail='Ticket not found'
            )
        
        ticket = results[0]
        resolution = ticket.get('resolution')
        title = ticket.get('title')
        
        return ResolutionResponse(
            success=True,
            ticket_number=ticket_number,
            resolution=resolution,
            ticket_title=title
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving ticket resolution: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db_conn = get_db_connection()
        db_conn.get_connection()
        db_status = 'connected'
    except Exception as e:
        db_status = f'error: {str(e)}'
    
    try:
        # Test GROQ connection
        test_response = db_conn.call_cortex_llm("Say 'OK' in JSON format: {\"status\": \"ok\"}", model='llama3-8b')
        groq_status = 'connected' if test_response else 'error: no response'
    except Exception as e:
        groq_status = f'error: {str(e)}'
    
    if db_status == 'connected' and groq_status == 'connected':
        return HealthResponse(
            status='healthy',
            database='connected',
            service='ticket-intake-classification'
        )
    else:
        return HealthResponse(
            status='unhealthy',
            database=db_status,
            service=f'groq: {groq_status}'
        )


@router.patch("/tickets/{ticket_number}/resolve", response_model=GenericResponse)
async def resolve_ticket(
    ticket_number: str = Path(..., description="The ticket number to resolve")
):
    """
    Resolve a ticket and decrement technician workload
    """
    try:
        db_conn = get_db_connection()
        
        # 1. Get ticket details to find assigned technician
        query = "SELECT assigned_tech_id, status FROM new_tickets WHERE ticketnumber = %s"
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        ticket = results[0]
        tech_id = ticket.get('assigned_tech_id')
        
        # 2. Update ticket status to 'Closed' (or whatever value represents closed)
        # Using status label 'Closed' and assuming it has a value
        picklist_loader = get_picklist_loader()
        closed_status = picklist_loader.get_value('status', 'Closed') or '3' # Fallback to 3 if unknown
        
        update_query = "UPDATE new_tickets SET status = %s, resolveddatetime = NOW() WHERE ticketnumber = %s"
        db_conn.execute_query(update_query, (closed_status, ticket_number), fetch=False)
        
        # 3. Decrement workload if a technician was assigned
        if tech_id:
            from src.agents.smart_ticket_assignment import SmartAssignmentAgent
            SmartAssignmentAgent(db_conn).decrement_workload(tech_id)
            
            # Record unassignment in history
            history_query = "UPDATE ticket_assignments SET unassigned_at = NOW(), assignment_status = 'resolved' WHERE ticket_number = %s AND tech_id = %s AND assignment_status = 'assigned'"
            db_conn.execute_query(history_query, (ticket_number, tech_id), fetch=False)
            
        return GenericResponse(
            success=True,
            message=f"Ticket {ticket_number} resolved successfully. Technician workload updated."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error resolving ticket: {str(e)}"
        )


# ── Cancel Ticket (user recalls their own open ticket) ───────────────────────

@router.post("/tickets/{ticket_number}/cancel", tags=["tickets"])
def cancel_ticket(
    ticket_number: str,
    payload: dict = Depends(get_current_user),
):
    """User cancels (recalls) their own ticket if it is not yet resolved/closed."""
    db = get_db_connection()
    user_id = payload.get("sub")
    role    = payload.get("role")

    rows = db.execute_query(
        "SELECT user_id, status FROM new_tickets WHERE ticketnumber=%s", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket = rows[0]
    if role not in ("admin", "tech_lead") and ticket.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="You can only cancel your own tickets")

    if ticket.get("status") in ("Resolved", "Closed"):
        raise HTTPException(status_code=400, detail="Ticket is already resolved or closed")

    db.execute_query(
        "UPDATE new_tickets SET status='Closed', resolveddatetime=NOW() WHERE ticketnumber=%s",
        (ticket_number,), fetch=False
    )
    # Terminate any running/pending agent session so the agent stops working
    db.execute_query(
        "UPDATE agent_sessions SET status='failed',"
        " escalation_reason='Ticket cancelled by user', completed_at=NOW()"
        " WHERE ticket_number=%s AND status IN ('running', 'awaiting_approval', 'pending')",
        (ticket_number,), fetch=False
    )
    db.execute_query(
        "INSERT INTO ticket_comments (ticket_number, author_id, author_type, author_name, content, is_internal)"
        " VALUES (%s, %s, 'system', 'System', 'Ticket cancelled by user', FALSE)",
        (ticket_number, user_id), fetch=False
    )
    return {"success": True, "message": "Ticket cancelled"}


# ── Delete Ticket (owner or admin) ───────────────────────────────────────────

@router.delete("/tickets/{ticket_number}", tags=["tickets"])
def delete_ticket(
    ticket_number: str,
    payload: dict = Depends(get_current_user),
):
    """User deletes their own ticket (or admin deletes any ticket)."""
    db = get_db_connection()
    role    = payload.get("role")
    user_id = payload.get("sub")

    rows = db.execute_query(
        "SELECT user_id FROM new_tickets WHERE ticketnumber=%s", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if role not in ("admin", "tech_lead") and rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own tickets")

    # Delete in FK-safe order: session_steps → agent_sessions → other dependents → ticket
    db.execute_query(
        "DELETE FROM session_steps WHERE session_id IN "
        "(SELECT session_id FROM agent_sessions WHERE ticket_number=%s)",
        (ticket_number,), fetch=False,
    )
    for tbl, col in [
        ("ticket_comments",   "ticket_number"),
        ("ticket_attachments","ticket_number"),
        ("agent_sessions",    "ticket_number"),
        ("ticket_feedback",   "ticket_number"),
    ]:
        db.execute_query(f"DELETE FROM {tbl} WHERE {col}=%s", (ticket_number,), fetch=False)

    db.execute_query(
        "DELETE FROM new_tickets WHERE ticketnumber=%s", (ticket_number,), fetch=False
    )
    return {"success": True, "message": f"Ticket {ticket_number} deleted"}


class BulkDeleteRequest(BaseModel):
    ticket_numbers: List[str]


@router.post("/tickets/bulk-delete", tags=["tickets"])
def bulk_delete_tickets(req: BulkDeleteRequest, payload: dict = Depends(get_current_user)):
    """Bulk delete tickets. Admins/tech_leads can delete any; users can only delete their own."""
    role    = payload.get("role")
    user_id = payload.get("sub")

    if not req.ticket_numbers:
        raise HTTPException(status_code=400, detail="No tickets specified")

    db = get_db_connection()
    deleted = 0
    for tn in req.ticket_numbers:
        rows = db.execute_query("SELECT user_id FROM new_tickets WHERE ticketnumber=%s", (tn,))
        if not rows:
            continue
        if role not in ("admin", "tech_lead") and rows[0].get("user_id") != user_id:
            continue
        db.execute_query(
            "DELETE FROM session_steps WHERE session_id IN "
            "(SELECT session_id FROM agent_sessions WHERE ticket_number=%s)",
            (tn,), fetch=False,
        )
        for tbl, col in [
            ("ticket_comments",    "ticket_number"),
            ("ticket_attachments", "ticket_number"),
            ("agent_sessions",     "ticket_number"),
            ("ticket_feedback",    "ticket_number"),
        ]:
            db.execute_query(f"DELETE FROM {tbl} WHERE {col}=%s", (tn,), fetch=False)
        db.execute_query("DELETE FROM new_tickets WHERE ticketnumber=%s", (tn,), fetch=False)
        deleted += 1

    return {"success": True, "deleted": deleted, "message": f"{deleted} ticket(s) deleted"}


# ── E5: Feedback Loop ─────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    tech_id:               Optional[str] = None
    rating:                Optional[int] = None   # 1-5
    classification_correct: Optional[bool] = None
    resolution_helpful:    Optional[bool] = None
    actual_issue_type:     Optional[str] = None
    notes:                 Optional[str] = None


@router.post("/tickets/{ticket_number}/feedback", tags=["tickets"])
def submit_feedback(ticket_number: str, req: FeedbackRequest):
    """E5: Technician/user submits feedback on classification accuracy and resolution quality."""
    db = get_db_connection()

    rows = db.execute_query(
        "SELECT ticketnumber FROM new_tickets WHERE ticketnumber=%s", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if req.rating is not None and not (1 <= req.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    db.execute_query(
        """INSERT INTO ticket_feedback
           (ticket_number, tech_id, rating, classification_correct,
            resolution_helpful, actual_issue_type, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (ticket_number, req.tech_id, req.rating, req.classification_correct,
         req.resolution_helpful, req.actual_issue_type, req.notes),
        fetch=False,
    )

    # If classification was wrong, log for model improvement tracking
    if req.classification_correct is False and req.actual_issue_type:
        import logging
        logging.getLogger(__name__).info(
            "Misclassification reported: ticket=%s expected_type=%s",
            ticket_number, req.actual_issue_type
        )

    return {"success": True, "message": "Feedback recorded. Thank you!"}


@router.get("/tickets/{ticket_number}/feedback", tags=["tickets"])
def get_feedback(ticket_number: str):
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT * FROM ticket_feedback WHERE ticket_number=%s ORDER BY created_at DESC",
        (ticket_number,),
    )
    return {"ticket_number": ticket_number, "feedback": rows or []}


# ── My Tickets (filtered by current user/tech) ────────────────────────────────

def _serialize_row(r: dict) -> dict:
    """Convert non-JSON-serializable DB types to plain Python types."""
    import decimal, uuid as _uuid
    from datetime import date
    t = {}
    for k, v in r.items():
        if v is None:
            t[k] = None
        elif isinstance(v, datetime):
            t[k] = v.isoformat()
        elif isinstance(v, date):
            t[k] = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            t[k] = float(v)
        elif isinstance(v, _uuid.UUID):
            t[k] = str(v)
        elif isinstance(v, (bytes, memoryview)):
            t[k] = None
        else:
            t[k] = v
    return t


log = logging.getLogger(__name__)


def _get_my_tickets_impl(status_filter, limit, payload):
    try:
        db = get_db_connection()
        role = payload.get("role", "")
        uid = payload.get("sub", "")

        _select = (
            "SELECT t.ticketnumber, t.title, t.description, t.status, t.priority, t.issuetype, "
            "t.createdate, t.resolveddatetime, t.assigned_tech_id, t.source, t.user_id, "
            "td.tech_name AS assigned_tech_name "
            "FROM new_tickets t LEFT JOIN technician_data td ON td.tech_id=t.assigned_tech_id"
        )
        if role == "user":
            base = _select + " WHERE t.user_id=%s"
            params: list = [uid]
        elif role in ("tech_lead", "admin"):
            base = _select + " WHERE 1=1"
            params = []
        else:
            base = _select + " WHERE t.assigned_tech_id=%s"
            params = [uid]

        if status_filter:
            base += " AND t.status=%s"
            params.append(status_filter)

        base += " ORDER BY t.createdate DESC LIMIT %s"
        params.append(limit)

        rows = db.execute_query(base, tuple(params)) or []
        pl = get_picklist_loader()
        label_fields = ["issuetype", "subissuetype", "ticketcategory", "tickettype", "priority", "status"]
        tickets = []
        for r in rows:
            t = _serialize_row(dict(r))
            for field in label_fields:
                if t.get(field):
                    lbl = pl.get_label(field, str(t[field]))
                    if lbl:
                        t[f"{field}_label"] = lbl
            tickets.append(t)
        return {"success": True, "tickets": tickets, "total": len(tickets)}
    except Exception as exc:
        log.error("GET /tickets/my failed for uid=%s role=%s: %s", payload.get("sub"), payload.get("role"), exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load tickets: {exc}")


@router.get("/tickets/my", tags=["tickets"])
def get_my_tickets(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    payload: dict = Depends(get_current_user),
):
    """Return tickets for the currently logged-in user or technician."""
    return _get_my_tickets_impl(status_filter, limit, payload)


# ── Ticket Status Update ──────────────────────────────────────────────────────

class StatusUpdateRequest(BaseModel):
    status: str  # e.g. "In Progress", "Resolved", "Closed"


@router.patch("/tickets/{ticket_number}/status", tags=["tickets"])
def update_ticket_status(
    ticket_number: str,
    req: StatusUpdateRequest,
    payload: dict = Depends(require_tech),
):
    """Technician updates ticket status."""
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT ticketnumber, assigned_tech_id, status FROM new_tickets WHERE ticketnumber=%s",
        (ticket_number,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    tech_id = payload.get("sub")
    role = payload.get("role")
    ticket = rows[0]

    if role not in ("admin", "tech_lead") and ticket.get("assigned_tech_id") != tech_id:
        raise HTTPException(status_code=403, detail="You can only update tickets assigned to you")

    picklist_loader = get_picklist_loader()
    status_val = picklist_loader.get_value("status", req.status) or req.status

    extra = {}
    if req.status in ("Resolved", "Closed"):
        extra["resolveddatetime"] = datetime.now()

    set_clause = "status=%s"
    params = [status_val]
    if extra.get("resolveddatetime"):
        set_clause += ", resolveddatetime=%s"
        params.append(extra["resolveddatetime"])
    params.append(ticket_number)

    db.execute_query(f"UPDATE new_tickets SET {set_clause} WHERE ticketnumber=%s", tuple(params), fetch=False)

    # Decrement workload when ticket is resolved or closed
    if req.status in ("Resolved", "Closed") and ticket.get("assigned_tech_id"):
        db.execute_query(
            "UPDATE technician_data SET current_workload=GREATEST(0,current_workload-1),"
            " solved_tickets=solved_tickets+1 WHERE tech_id=%s",
            (ticket["assigned_tech_id"],),
            fetch=False,
        )

    # Add system comment
    db.execute_query(
        "INSERT INTO ticket_comments (ticket_number, author_id, author_type, author_name, content, is_internal)"
        " VALUES (%s, %s, 'system', 'System', %s, FALSE)",
        (ticket_number, tech_id, f"Status changed to {req.status}"),
        fetch=False,
    )

    return {"success": True, "message": f"Status updated to {req.status}"}


class ResolutionUpdateRequest(BaseModel):
    resolution: str


@router.patch("/tickets/{ticket_number}/resolution", tags=["tickets"])
def update_ticket_resolution(
    ticket_number: str,
    req: ResolutionUpdateRequest,
    payload: dict = Depends(require_tech),
):
    """Technician saves AI-generated or manually written resolution to the ticket."""
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT ticketnumber FROM new_tickets WHERE ticketnumber=%s", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    db.execute_query(
        "UPDATE new_tickets SET resolution=%s WHERE ticketnumber=%s",
        (req.resolution, ticket_number),
        fetch=False,
    )
    return {"success": True}


# ── Ticket Reassign (tech lead only) ─────────────────────────────────────────

class ReassignRequest(BaseModel):
    new_tech_id: str
    reason: Optional[str] = None


@router.post("/tickets/{ticket_number}/reassign", tags=["tickets"])
def reassign_ticket(
    ticket_number: str,
    req: ReassignRequest,
    payload: dict = Depends(require_tech_lead),
):
    """Tech lead reassigns ticket to another technician."""
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT ticketnumber, assigned_tech_id FROM new_tickets WHERE ticketnumber=%s", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Verify new tech exists
    tech_rows = db.execute_query(
        "SELECT tech_id, tech_name FROM technician_data WHERE tech_id=%s LIMIT 1", (req.new_tech_id,)
    )
    if not tech_rows:
        raise HTTPException(status_code=404, detail="Technician not found")

    old_tech_id = rows[0].get("assigned_tech_id")
    new_tech_name = tech_rows[0].get("tech_name", req.new_tech_id)

    db.execute_query(
        "UPDATE new_tickets SET assigned_tech_id=%s WHERE ticketnumber=%s",
        (req.new_tech_id, ticket_number), fetch=False,
    )

    # Adjust workloads
    if old_tech_id:
        db.execute_query(
            "UPDATE technician_data SET no_tickets_inprogress=GREATEST(0,no_tickets_inprogress-1) WHERE tech_id=%s",
            (old_tech_id,), fetch=False,
        )
    db.execute_query(
        "UPDATE technician_data SET no_tickets_inprogress=no_tickets_inprogress+1 WHERE tech_id=%s",
        (req.new_tech_id,), fetch=False,
    )

    note = req.reason or "Reassigned by tech lead"
    db.execute_query(
        "INSERT INTO ticket_comments (ticket_number, author_id, author_type, author_name, content, is_internal)"
        " VALUES (%s,%s,'system','System',%s,TRUE)",
        (ticket_number, payload.get("sub"), f"Ticket reassigned to {new_tech_name}. Reason: {note}"),
        fetch=False,
    )

    return {"success": True, "message": f"Ticket reassigned to {new_tech_name}"}


# ── Escalate Ticket (tech lead only) ─────────────────────────────────────────

class EscalateRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Reason for escalation")


@router.patch("/tickets/{ticket_number}/escalate", tags=["tickets"])
def escalate_ticket(
    ticket_number: str,
    req: EscalateRequest,
    payload: dict = Depends(require_tech_lead),
):
    """Tech lead escalates a ticket, setting its status to Escalated."""
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT ticketnumber, status, assigned_tech_id FROM new_tickets WHERE ticketnumber=%s",
        (ticket_number,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket = rows[0]
    if ticket.get("status") in ("Resolved", "Closed", "Escalated"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot escalate a ticket with status '{ticket.get('status')}'"
        )

    db.execute_query(
        "UPDATE new_tickets SET status='Escalated' WHERE ticketnumber=%s",
        (ticket_number,), fetch=False,
    )

    db.execute_query(
        "INSERT INTO ticket_comments (ticket_number, author_id, author_type, author_name, content, is_internal)"
        " VALUES (%s,%s,'system','System',%s,FALSE)",
        (ticket_number, payload.get("sub"), f"Ticket escalated. Reason: {req.reason}"),
        fetch=False,
    )

    return {"success": True, "message": "Ticket escalated", "reason": req.reason}


# ── Comments ──────────────────────────────────────────────────────────────────

class CommentRequest(BaseModel):
    content: str
    is_internal: bool = False  # tech-only note (not visible to user)


@router.get("/tickets/{ticket_number}/comments", tags=["tickets"])
def get_comments(
    ticket_number: str,
    payload: Optional[dict] = Depends(optional_user),
):
    db = get_db_connection()
    is_tech = payload and payload.get("role") in ("tech", "tech_lead", "admin")

    if is_tech:
        rows = db.execute_query(
            "SELECT * FROM ticket_comments WHERE ticket_number=%s ORDER BY created_at ASC",
            (ticket_number,),
        )
    else:
        rows = db.execute_query(
            "SELECT * FROM ticket_comments WHERE ticket_number=%s AND is_internal=FALSE ORDER BY created_at ASC",
            (ticket_number,),
        )

    comments = []
    for r in (rows or []):
        c = dict(r)
        if isinstance(c.get("created_at"), datetime):
            c["created_at"] = c["created_at"].isoformat()
        comments.append(c)
    return {"ticket_number": ticket_number, "comments": comments}


@router.post("/tickets/{ticket_number}/comments", tags=["tickets"])
def add_comment(
    ticket_number: str,
    req: CommentRequest,
    payload: dict = Depends(get_current_user),
):
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT ticketnumber FROM new_tickets WHERE ticketnumber=%s", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    role = payload.get("role", "")
    author_type = "tech" if role in ("tech", "tech_lead", "admin") else "user"
    is_internal = req.is_internal and author_type == "tech"

    db.execute_query(
        "INSERT INTO ticket_comments (ticket_number, author_id, author_type, author_name, content, is_internal)"
        " VALUES (%s,%s,%s,%s,%s,%s)",
        (ticket_number, payload["sub"], author_type, payload.get("name", ""), req.content, is_internal),
        fetch=False,
    )
    return {"success": True, "message": "Comment added"}


# ── Re-raise Ticket ───────────────────────────────────────────────────────────

class ReraiseRequest(BaseModel):
    reason: str = "Issue not resolved"


@router.post("/tickets/{ticket_number}/reraise", tags=["tickets"])
def reraise_ticket(
    ticket_number: str,
    req: ReraiseRequest,
    payload: dict = Depends(get_current_user),
):
    """User re-raises a resolved/closed ticket. Creates a new linked ticket."""
    if payload.get("role") != "user":
        raise HTTPException(status_code=403, detail="Only users can re-raise tickets")

    db = get_db_connection()
    rows = db.execute_query(
        "SELECT * FROM new_tickets WHERE ticketnumber=%s LIMIT 1", (ticket_number,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Ticket not found")

    original = rows[0]
    if original.get("status") not in ("Resolved", "Closed", "3", "4"):
        raise HTTPException(status_code=400, detail="Can only re-raise resolved or closed tickets")

    # Create new ticket linked to original
    import uuid
    from datetime import datetime as dt
    new_num = f"T{dt.now().strftime('%Y%m%d')}.{uuid.uuid4().hex[:6].upper()}"

    db.execute_query(
        "INSERT INTO new_tickets (ticketnumber, title, description, user_id, status, priority, source, parent_ticket, reraise_reason, createdate)"
        " VALUES (%s,%s,%s,%s,'Open',%s,'portal',%s,%s,NOW())",
        (
            new_num,
            f"[RE-RAISE] {original.get('title','')}"[:200],
            f"{req.reason}\n\nOriginal ticket: {ticket_number}\n\n{original.get('description','')}",
            payload["sub"],
            original.get("priority", "Medium"),
            ticket_number,
            req.reason,
        ),
        fetch=False,
    )

    return {"success": True, "new_ticket_number": new_num, "message": "Ticket re-raised successfully"}


# ── Similar Tickets (for tech AI assist) ─────────────────────────────────────

def _get_similar_tickets_impl(title, description, limit, payload):
    db = get_db_connection()
    # Extract meaningful keywords (skip common stop words)
    _STOP = {"a","an","the","is","it","in","on","for","to","of","and","or","not","with",
              "my","me","i","we","our","has","have","was","been","are","be","do","can",
              "this","that","at","by","from","into","after","when","keep","keeps"}
    words = [w.strip(".,!?") for w in title.split() if len(w) > 2 and w.lower() not in _STOP]
    if not words:
        words = title.split()[:3]
    # Build OR condition across keywords for both title and description
    kw_list = words[:8]  # cap at 8 keywords
    conditions = " OR ".join(["(title ILIKE %s OR description ILIKE %s)"] * len(kw_list))
    params = []
    for w in kw_list:
        params += [f"%{w}%", f"%{w}%"]
    params.append(limit)
    rows = db.execute_query(
        f"""SELECT ticketnumber, title, description, resolution, issuetype, priority, status
           FROM new_tickets
           WHERE resolution IS NOT NULL
             AND status IN ('Resolved','Closed','3','4')
             AND ({conditions})
           ORDER BY createdate DESC
           LIMIT %s""",
        tuple(params),
    )
    tickets = []
    for r in (rows or []):
        t = dict(r)
        for k, v in t.items():
            if isinstance(v, datetime):
                t[k] = v.isoformat()
        tickets.append(t)
    return {"success": True, "similar_tickets": tickets, "count": len(tickets)}


@router.get("/tickets/similar", tags=["tickets"])
def get_similar_tickets(
    title: str = Query(..., description="Ticket title to search for similar"),
    description: str = Query("", description="Ticket description"),
    limit: int = Query(5, ge=1, le=20),
    payload: dict = Depends(require_tech),
):
    """Return similar resolved tickets for technician AI assistance."""
    return _get_similar_tickets_impl(title, description, limit, payload)


# ── List Technicians (for reassign dropdown) ──────────────────────────────────

def _list_technicians_impl(payload):
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT tech_id, tech_name, tech_mail, tech_role FROM technician_data"
        " WHERE status='available' ORDER BY tech_name"
    ) or []
    return {"success": True, "technicians": [dict(r) for r in rows]}


@router.get("/tickets/technicians", tags=["tickets"])
def list_active_technicians(payload: dict = Depends(require_tech)):
    return _list_technicians_impl(payload)


# ── Real-time ticket chat (WebSocket) ─────────────────────────────────────────

import asyncio as _asyncio
import json as _json
from typing import Set
from fastapi import WebSocket, WebSocketDisconnect

_ticket_chat_rooms: Dict[str, Set[WebSocket]] = {}


@router.websocket("/ws/tickets/{ticket_number}/chat")
async def ticket_chat_ws(ticket_number: str, ws: WebSocket, token: str = Query(None)):
    """Real-time chat WebSocket for a specific ticket (user ↔ tech)."""
    from src.auth.jwt_handler import decode_token

    payload_ws = decode_token(token) if token else None
    author_id   = (payload_ws or {}).get("sub", "anonymous")
    author_name = (payload_ws or {}).get("name", "User")
    author_type = "tech" if (payload_ws or {}).get("role") in ("tech", "tech_lead", "admin") else "user"

    await ws.accept()
    _ticket_chat_rooms.setdefault(ticket_number, set()).add(ws)
    log.info("Chat WS connected: ticket=%s author=%s (%s)", ticket_number, author_id, author_type)

    try:
        async for raw in ws.iter_text():
            try:
                data = _json.loads(raw)
            except _json.JSONDecodeError:
                continue

            content = (data.get("content") or "").strip()
            attachment = data.get("attachment")  # {filename, url} if file was uploaded first
            if not content and not attachment:
                continue

            db = get_db_connection()
            rows = db.execute_query(
                "INSERT INTO ticket_comments (ticket_number, author_id, author_type, author_name, content)"
                " VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at",
                (ticket_number, author_id, author_type, author_name, content or (attachment or {}).get("filename", "")),
            )
            comment_id = rows[0]["id"] if rows else None
            created_at = rows[0]["created_at"].isoformat() if rows and rows[0].get("created_at") else datetime.utcnow().isoformat()

            broadcast = {
                "type":        "message",
                "comment_id":  comment_id,
                "author_id":   author_id,
                "author_type": author_type,
                "author_name": author_name,
                "content":     content,
                "attachment":  attachment,
                "created_at":  created_at,
            }
            msg_str = _json.dumps(broadcast, default=str)
            dead = set()
            for subscriber in list(_ticket_chat_rooms.get(ticket_number, set())):
                try:
                    await subscriber.send_text(msg_str)
                except Exception:
                    dead.add(subscriber)
            _ticket_chat_rooms.get(ticket_number, set()).difference_update(dead)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("Chat WS error ticket=%s: %s", ticket_number, e)
    finally:
        _ticket_chat_rooms.get(ticket_number, set()).discard(ws)
        log.info("Chat WS disconnected: ticket=%s author=%s", ticket_number, author_id)


# ── File attachments ──────────────────────────────────────────────────────────

import os as _os
import uuid as _uuid
from fastapi import UploadFile, File

_S3_BUCKET    = _os.environ.get("S3_EXPORTS_BUCKET", "ticketing-prod-exports-808812816838")
_ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
}
_MAX_BYTES = 25 * 1024 * 1024  # 25 MB


@router.post("/tickets/{ticket_number}/attachments", tags=["tickets"])
async def upload_attachment(
    ticket_number: str,
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_user),
):
    """Upload a file attachment for a ticket (stored in S3, URL returned)."""
    import boto3

    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"File type not allowed: {file.content_type}")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")

    uploader_id   = payload.get("sub", "unknown")
    uploader_type = "tech" if payload.get("role") in ("tech", "tech_lead", "admin") else "user"
    ext           = (_os.path.splitext(file.filename or "")[1] or "").lower()
    s3_key        = f"attachments/{ticket_number}/{_uuid.uuid4().hex}{ext}"

    try:
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=data,
            ContentType=file.content_type,
            ContentDisposition=f'attachment; filename="{file.filename}"',
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": _S3_BUCKET, "Key": s3_key},
            ExpiresIn=3600,
        )
    except Exception as e:
        log.error("S3 upload failed: %s", e)
        raise HTTPException(status_code=500, detail="File upload failed")

    db = get_db_connection()
    db.execute_query(
        "INSERT INTO ticket_attachments (ticket_number, uploader_id, uploader_type, filename, s3_key, file_size, mime_type)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (ticket_number, uploader_id, uploader_type, file.filename, s3_key, len(data), file.content_type),
        fetch=False,
    )

    return {
        "filename":  file.filename,
        "s3_key":    s3_key,
        "url":       url,
        "mime_type": file.content_type,
        "size":      len(data),
    }


@router.get("/tickets/{ticket_number}/attachments", tags=["tickets"])
def list_attachments(
    ticket_number: str,
    payload: dict = Depends(get_current_user),
):
    """List all attachments for a ticket with fresh presigned URLs."""
    import boto3

    db = get_db_connection()
    rows = db.execute_query(
        "SELECT id, uploader_id, uploader_type, filename, s3_key, file_size, mime_type, created_at"
        " FROM ticket_attachments WHERE ticket_number=%s ORDER BY created_at ASC",
        (ticket_number,),
    ) or []

    s3 = boto3.client("s3", region_name="ap-south-1")
    result = []
    for r in rows:
        item = dict(r)
        try:
            item["url"] = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": _S3_BUCKET, "Key": r["s3_key"]},
                ExpiresIn=3600,
            )
        except Exception:
            item["url"] = None
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat()
        result.append(item)

    return {"attachments": result, "count": len(result)}
