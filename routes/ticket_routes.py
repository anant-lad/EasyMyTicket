"""
Ticket creation and intake classification routes
"""
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any, Optional, List
from src.database.db_connection import DatabaseConnection
from src.agents.intake_classification import IntakeClassificationAgent
from src.config import Config

router = APIRouter()

# Lazy loading for database connection and agent
_db_conn = None
_intake_agent = None

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


class TicketDetailResponse(BaseModel):
    """Response model for ticket details"""
    success: bool
    ticket: Dict[str, Any]


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


@router.post("/tickets/create", response_model=TicketResponse, status_code=201)
async def create_ticket(ticket_request: TicketCreateRequest):
    """
    Create a new ticket and process through intake classification
    
    This endpoint:
    1. Extracts metadata from the ticket using LLM
    2. Finds similar historical tickets
    3. Classifies the ticket based on content and similar tickets
    4. Stores the ticket in the database
    
    Returns:
        TicketResponse with ticket details, metadata, and classification
    """
    try:
        # Prepare ticket data
        ticket_data: Dict[str, Any] = {
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
        
        # Step 4: Merge classification data into ticket_data
        # Extract values from classification (handle both dict with Value/Label and direct values)
        if isinstance(classification.get('ISSUETYPE'), dict):
            ticket_data['issuetype'] = classification['ISSUETYPE'].get('Value')
        else:
            ticket_data['issuetype'] = classification.get('ISSUETYPE')
        
        if isinstance(classification.get('SUBISSUETYPE'), dict):
            ticket_data['subissuetype'] = classification['SUBISSUETYPE'].get('Value')
        else:
            ticket_data['subissuetype'] = classification.get('SUBISSUETYPE')
        
        if isinstance(classification.get('TICKETCATEGORY'), dict):
            ticket_data['ticketcategory'] = classification['TICKETCATEGORY'].get('Value')
        else:
            ticket_data['ticketcategory'] = classification.get('TICKETCATEGORY')
        
        if isinstance(classification.get('TICKETTYPE'), dict):
            ticket_data['tickettype'] = classification['TICKETTYPE'].get('Value')
        else:
            ticket_data['tickettype'] = classification.get('TICKETTYPE')
        
        if isinstance(classification.get('PRIORITY'), dict):
            ticket_data['priority'] = classification['PRIORITY'].get('Value')
        else:
            ticket_data['priority'] = classification.get('PRIORITY')
        
        if isinstance(classification.get('STATUS'), dict):
            ticket_data['status'] = classification['STATUS'].get('Value')
        else:
            ticket_data['status'] = classification.get('STATUS', 'Open')
        
        # Step 5: Insert ticket into database
        print("\n" + "="*80)
        print("💾 Step 4: Inserting ticket into database...")
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
            similar_tickets_found=len(similar_tickets)
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
    Get ticket details by ticket number
    
    Args:
        ticket_number: The ticket number to retrieve
    
    Returns:
        TicketDetailResponse with ticket details
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
        ticket = results[0]
        for key, value in ticket.items():
            if isinstance(value, datetime):
                ticket[key] = value.isoformat()
        
        return TicketDetailResponse(
            success=True,
            ticket=ticket
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving ticket: {e}")
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
