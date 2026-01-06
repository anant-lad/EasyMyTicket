"""
Ticket creation and intake classification routes
"""
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any, Optional, List
from src.database.db_connection import DatabaseConnection
from src.agents.intake_classification import IntakeClassificationAgent
from src.agents.resolution_generation import ResolutionGenerationAgent
from src.agents.smart_ticket_assignment import SmartAssignmentAgent
from src.agents.notification_agent import NotificationAgent
from src.config import Config
from src.utils.picklist_loader import get_picklist_loader

router = APIRouter()

# Lazy loading for database connection and agents
_db_conn = None
_intake_agent = None
_resolution_agent = None
_assignment_agent = None
_notification_agent = None

def get_db_connection():
    """Get or create database connection (lazy loading)"""
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn

def get_intake_agent():
    """Get or create intake agent (lazy loading)"""
    global _intake_agent
    if _intake_agent is None:
        _intake_agent = IntakeClassificationAgent(get_db_connection())
    return _intake_agent

def get_resolution_agent():
    """Get or create resolution generation agent (lazy loading)"""
    global _resolution_agent
    if _resolution_agent is None:
        _resolution_agent = ResolutionGenerationAgent(get_db_connection())
    return _resolution_agent

def get_assignment_agent():
    """Get or create smart assignment agent (lazy loading)"""
    global _assignment_agent
    if _assignment_agent is None:
        _assignment_agent = SmartAssignmentAgent(get_db_connection())
    return _assignment_agent

def get_notification_agent():
    """Get or create notification agent (lazy loading)"""
    global _notification_agent
    if _notification_agent is None:
        _notification_agent = NotificationAgent()
    return _notification_agent



# Pydantic models for request/response
class TicketCreateRequest(BaseModel):
    """Request model for ticket creation"""
    title: str = Field(..., description="Ticket title", min_length=1)
    description: str = Field(..., description="Ticket description", min_length=1)
    user_id: str = Field(..., description="User ID who created the ticket", min_length=1)
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
async def create_ticket(ticket_request: TicketCreateRequest):
    """
    Create a new ticket and process through agentic workflow
    
    This endpoint:
    1. Extracts metadata from the ticket using LLM
    2. Finds similar historical tickets
    3. Classifies the ticket based on content and similar tickets
    4. Generates resolution steps based on similar tickets
    5. Stores the ticket in the database
    
    Returns:
        TicketResponse with ticket details, metadata, classification, and resolution
    """
    try:
        # Generate ticket number immediately
        ticket_number = f"T{datetime.now().strftime('%Y%m%d')}.{datetime.now().strftime('%H%M%S')}"
        
        # Prepare ticket data
        ticket_data: Dict[str, Any] = {
            'ticketnumber': ticket_number,
            'title': ticket_request.title,
            'description': ticket_request.description,
            'user_id': ticket_request.user_id,
            'createdate': datetime.now(),  # Auto-detect create datetime
            'status': 'Open'
        }
        
        # Add due_date_time if provided
        if ticket_request.due_date_time:
            try:
                ticket_data['duedatetime'] = datetime.strptime(
                    ticket_request.due_date_time, 
                    '%Y-%m-%d %H:%M:%S'
                )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail='Invalid due_date_time format. Use: YYYY-MM-DD HH:MM:SS'
                )
        
        # Get database connection and agent (lazy loading)
        db_conn = get_db_connection()
        intake_agent = get_intake_agent()
        
        # Step 1: Extract metadata using intake agent
        print("\n" + "="*80)
        print("🎫 TICKET CREATION REQUEST RECEIVED")
        print("="*80)
        print(f"📝 Title: {ticket_data['title']}")
        print(f"👤 User ID: {ticket_data['user_id']}")
        print(f"📅 Created: {ticket_data['createdate']}")
        if ticket_data.get('duedatetime'):
            print(f"⏰ Due: {ticket_data['duedatetime']}")
        print("="*80)
        print("\nStep 1: Extracting metadata...")
        try:
            extracted_metadata = intake_agent.extract_metadata(
                title=ticket_data['title'],
                description=ticket_data['description'],
                model='llama3-8b'
            )
            
            if not extracted_metadata:
                print("ERROR: extract_metadata returned None")
                raise HTTPException(
                    status_code=500,
                    detail='Failed to extract metadata from ticket. The LLM may have returned an invalid response or the API call failed. Check server logs for details.'
                )
        except HTTPException:
            raise
        except Exception as e:
            print(f"ERROR in extract_metadata: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f'Error extracting metadata: {str(e)}'
            )
        
        # Step 2: Find similar tickets
        print("\nStep 2: Finding similar tickets...")
        similar_tickets = db_conn.find_similar_tickets(
            title=ticket_data['title'],
            description=ticket_data['description'],
            limit=Config.SIMILAR_TICKETS_LIMIT
        )
        
        # Step 3: Classify ticket
        print("\nStep 3: Classifying ticket...")
        classification = intake_agent.classify_ticket(
            new_ticket_data=ticket_data,
            extracted_metadata=extracted_metadata,
            similar_tickets=similar_tickets,
            model=Config.CLASSIFICATION_MODEL
        )
        
        if not classification:
            raise HTTPException(
                status_code=500,
                detail='Failed to classify ticket'
            )
        
        # Step 4: Merge classification data into ticket_data with normalization
        # Extract values from classification and normalize using picklist
        picklist_loader = get_picklist_loader()
        
        # Helper function to normalize and extract value
        def normalize_field(field_key: str, db_field: str, default_value: str = None):
            value = classification.get(field_key)
            if isinstance(value, dict):
                raw_value = value.get('Value') or value.get('value')
            else:
                raw_value = value
            
            if raw_value:
                # Normalize the value using picklist
                normalized = picklist_loader.normalize_value(db_field, str(raw_value))
                if normalized:
                    ticket_data[db_field] = normalized
                else:
                    # If normalization fails, use raw value as fallback
                    ticket_data[db_field] = str(raw_value)
            elif default_value:
                ticket_data[db_field] = default_value
        
        # Normalize and set each field
        normalize_field('ISSUETYPE', 'issuetype')
        normalize_field('SUBISSUETYPE', 'subissuetype')
        normalize_field('TICKETCATEGORY', 'ticketcategory')
        normalize_field('TICKETTYPE', 'tickettype')
        normalize_field('PRIORITY', 'priority')
        normalize_field('STATUS', 'status', '1')  # Default to "New" status (value 1)
        

        # If status wasn't set, use default
        if 'status' not in ticket_data or not ticket_data['status']:
            status_value = picklist_loader.get_value('status', 'New')
            ticket_data['status'] = status_value or '1'

        # Step 5: Generate resolution steps
        print("\nStep 5: Generating resolution steps...")
        resolution_agent = get_resolution_agent()
        generated_resolution = None

        try:
            generated_resolution = resolution_agent.generate_resolution(
                ticket_data=ticket_data,
                extracted_metadata=extracted_metadata,
                similar_tickets=similar_tickets,
                model=Config.CLASSIFICATION_MODEL  # Use same model for consistency
            )

            if generated_resolution:
                ticket_data['resolution'] = generated_resolution
                print(f"✅ Resolution generated and added to ticket data")
            else:
                print("⚠️  Resolution generation returned None, continuing without resolution")
        except Exception as e:
            print(f"⚠️  Error generating resolution: {str(e)}")
            import traceback
            traceback.print_exc()
            # Continue without resolution - don't fail the ticket creation

        # Step 6: Smart Ticket Assignment
        print("\nStep 6: Assigning technician...")
        assignment_agent = get_assignment_agent()
        assigned_tech_id = None

        try:
            assigned_tech_id = assignment_agent.assign_ticket(
                ticket_data=ticket_data,
                classification=classification
            )

            if assigned_tech_id:
                ticket_data['assigned_tech_id'] = assigned_tech_id
                print(f"✅ Ticket assigned to: {assigned_tech_id}")
            else:
                print("⚠️  No suitable technician found for assignment")
        except Exception as e:
            print(f"⚠️  Error in assignment agent: {str(e)}")
            # Continue even if assignment fails

        # Step 7: Insert ticket into database
        print("\n" + "="*80)
        print("💾 Step 7: Inserting ticket into database...")
        print("="*80)
        print(f"📊 Ticket data to insert:")
        print(f"   - Title: {ticket_data['title']}")
        print(f"   - User ID: {ticket_data['user_id']}")
        print(f"   - Status: {ticket_data.get('status', 'N/A')}")
        print(f"   - Issue Type: {ticket_data.get('issuetype', 'N/A')}")
        print(f"   - Category: {ticket_data.get('ticketcategory', 'N/A')}")
        print(f"   - Priority: {ticket_data.get('priority', 'N/A')}")
        
        ticket_number = db_conn.insert_ticket(ticket_data)
        
        if not ticket_number:
            print("❌ Failed to insert ticket into database")
            raise HTTPException(
                status_code=500,
                detail='Failed to insert ticket into database'
            )
        
        print(f"✅ Ticket inserted successfully!")
        print(f"🎫 Ticket Number: {ticket_number}")
        print("="*80)
        print("✅ TICKET CREATION COMPLETED SUCCESSFULLY")
        print("="*80 + "\n")
        
        # Step 8: Send Notifications
        try:
            notification_agent = get_notification_agent()
            
            # Fetch User Details
            user_query = "SELECT user_name, user_mail FROM user_data WHERE user_id = %s"
            user_results = db_conn.execute_query(user_query, (ticket_data['user_id'],))
            user_data = user_results[0] if user_results else {'user_name': 'User', 'user_mail': None}
            
            # Fetch Technician Details (if assigned)
            tech_data = None
            if assigned_tech_id:
                tech_query = "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id = %s"
                tech_results = db_conn.execute_query(tech_query, (assigned_tech_id,))
                if tech_results:
                    tech_data = tech_results[0]
                    # Notify Technician
                    notification_agent.notify_technician(ticket_data, tech_data)
            
            # Notify User
            if user_data.get('user_mail'):
                notification_agent.notify_user(ticket_data, user_data, tech_data)
                
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
            # Don't fail the whole request if notifications fail
        
        # Prepare response
        response = TicketResponse(
            success=True,
            ticket_number=ticket_number,
            ticket_data={
                'title': ticket_data['title'],
                'description': ticket_data['description'],
                'user_id': ticket_data['user_id'],
                'createdate': ticket_data['createdate'].isoformat() if isinstance(ticket_data['createdate'], datetime) else str(ticket_data['createdate']),
                'duedatetime': ticket_data.get('duedatetime').isoformat() if ticket_data.get('duedatetime') and isinstance(ticket_data['duedatetime'], datetime) else None
            },
            extracted_metadata=extracted_metadata,
            classification=classification,
            similar_tickets_found=len(similar_tickets),
            resolution=generated_resolution,
            assigned_tech_id=assigned_tech_id
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating ticket: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


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
            assignment_agent = get_assignment_agent()
            assignment_agent.decrement_workload(tech_id)
            
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
