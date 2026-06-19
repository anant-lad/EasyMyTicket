"""
Ticket creation and intake classification routes
"""
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any, Optional, List
from src.database.db_connection import DatabaseConnection
from src.config import Config
from src.utils.picklist_loader import get_picklist_loader

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
        example="2024-12-10 10:00:00"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Email not working",
                "description": "I cannot send emails through Outlook. Getting error message 'Connection timeout'",
                "user_id": "user123",
                "device_id": "a1b2c3d4-...",
                "due_date_time": "2024-12-10 10:00:00"
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


@router.post("/tickets/create", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket_request: TicketCreateRequest,
    device_id: Optional[str] = Query(None, description="Desktop agent device ID (query param — body field takes precedence)"),
):
    """
    Create a ticket and run the full LangGraph agentic pipeline:
      extract metadata → classify → auto-route decision →
        [agent auto-fix | technician assignment] → generate resolution → notify
    """
    import asyncio
    from src.graph.ticket_graph import process_ticket

    # Body device_id takes precedence over query param
    effective_device_id = ticket_request.device_id or device_id

    try:
        # Validate due_date_time format before entering the graph
        if ticket_request.due_date_time:
            try:
                datetime.strptime(ticket_request.due_date_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid due_date_time format. Use: YYYY-MM-DD HH:MM:SS",
                )

        # Run the LangGraph pipeline (blocking call — offload to thread pool)
        loop = asyncio.get_event_loop()
        state = await loop.run_in_executor(
            None,
            lambda: process_ticket(
                title=ticket_request.title,
                description=ticket_request.description,
                user_id=ticket_request.user_id,
                source=ticket_request.source or "portal",
                device_id=effective_device_id,
                due_date_time=ticket_request.due_date_time,
            ),
        )

        if state.get("ticket_number") == "FAILED":
            raise HTTPException(status_code=500, detail="Ticket pipeline failed — check server logs")

        return TicketResponse(
            success=True,
            ticket_number=state["ticket_number"],
            ticket_data={
                "title": ticket_request.title,
                "description": ticket_request.description,
                "user_id": ticket_request.user_id,
                "createdate": datetime.now().isoformat(),
                "duedatetime": ticket_request.due_date_time,
                "can_auto_resolve": state.get("can_auto_resolve", False),
                "agent_connected": state.get("agent_connected", False),
                "agent_task_id": state.get("agent_task_id"),
            },
            extracted_metadata=state.get("extracted_metadata", {}),
            classification=state.get("classification", {}),
            similar_tickets_found=len(state.get("similar_tickets", [])),
            resolution=state.get("resolution"),
            assigned_tech_id=state.get("assigned_tech_id"),
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
    order_direction: str = Query('DESC', regex='^(ASC|DESC)$', description="Order direction: ASC or DESC")
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
        
        # Convert datetime objects to strings for JSON serialization
        tickets = []
        for ticket in result['tickets']:
            ticket_dict = dict(ticket)
            for key, value in ticket_dict.items():
                if isinstance(value, datetime):
                    ticket_dict[key] = value.isoformat()
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
            SELECT * FROM new_tickets
            WHERE ticketnumber = %s
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


# ── E5: Feedback Loop ─────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    tech_id:               Optional[str] = None
    rating:                Optional[int] = None   # 1-5
    classification_correct: Optional[bool] = None
    resolution_helpful:    Optional[bool] = None
    actual_issue_type:     Optional[str] = None
    notes:                 Optional[str] = None


@router.post("/api/tickets/{ticket_number}/feedback", tags=["tickets"])
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


@router.get("/api/tickets/{ticket_number}/feedback", tags=["tickets"])
def get_feedback(ticket_number: str):
    db = get_db_connection()
    rows = db.execute_query(
        "SELECT * FROM ticket_feedback WHERE ticket_number=%s ORDER BY created_at DESC",
        (ticket_number,),
    )
    return {"ticket_number": ticket_number, "feedback": rows or []}
