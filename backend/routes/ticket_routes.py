"""
Ticket creation and intake classification routes
"""
from fastapi import APIRouter, HTTPException, Path, Query, File, UploadFile, Form
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
from src.services.storage_service import get_storage_service
from src.services.file_processor import get_file_processor
from src.services.context_processor import get_context_processor

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
    companyid: str = Field(..., description="Organization company ID (must exist in organizations table)", min_length=1)
    priority: Optional[str] = Field(None, description="Initial priority assessment (High, Medium, Low)")
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
                "companyid": "0001",
                "priority": "High",
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


class AttachmentInfo(BaseModel):
    """Model for attachment information"""
    attachment_id: int
    filename: str
    file_type: str
    file_size: int
    file_path: str
    processing_status: str
    extracted_content: Optional[str] = None
    uploaded_at: datetime


class TicketContextInfo(BaseModel):
    """Model for ticket context information"""
    context_id: int
    extracted_text: Optional[str] = None
    image_analysis: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    entities: Optional[Dict[str, Any]] = None
    context_summary: Optional[str] = None
    created_at: datetime


class EnhancedTicketDetailResponse(BaseModel):
    """Enhanced response with attachments and context"""
    success: bool
    ticket: Dict[str, Any]
    ticket_with_labels: Optional[Dict[str, Any]] = None
    attachments: List[AttachmentInfo] = []
    context: Optional[TicketContextInfo] = None


@router.post("/tickets/create", response_model=TicketResponse, status_code=201)
async def create_ticket(
    title: str = Form(..., description="Ticket title"),
    description: str = Form(..., description="Ticket description"),
    user_id: str = Form(..., description="User ID who created the ticket"),
    companyid: str = Form(..., description="Organization company ID"),
    priority: Optional[str] = Form(None, description="Initial priority (High, Medium, Low)"),
    due_date_time: Optional[str] = Form(None, description="Due date time (YYYY-MM-DD HH:MM:SS)"),
    files: List[UploadFile] = File(default=[], description="Attached files (PDF, DOCX, images, CSV, etc.)")
):
    """
    Create a new ticket with file upload support and process through agentic workflow
    
    This endpoint:
    1. Validates companyid exists in organizations table
    2. Processes uploaded files (PDF, DOCX, images, CSV, etc.)
    3. Extracts text and data from files
    4. Generates enriched ticket context
    5. Extracts metadata from the ticket using LLM
    6. Finds similar historical tickets/contexts
    7. Classifies the ticket based on content and similar tickets
    8. Evaluates user-provided priority and may adjust it
    9. Generates resolution steps based on similar tickets
    10. Stores the ticket, attachments, and context in the database
    
    Returns:
        TicketResponse with ticket details, metadata, classification, and resolution
    """
    try:
        # Get database connection
        db_conn = get_db_connection()
        
        # Validate companyid exists in organizations table
        organization = db_conn.get_organization_by_companyid(companyid)
        if not organization:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid companyid: {companyid}. Organization does not exist. Please create the organization first.'
            )
        
        # Generate ticket number immediately
        ticket_number = f"T{datetime.now().strftime('%Y%m%d')}.{datetime.now().strftime('%H%M%S')}"
        
        # Prepare ticket data
        ticket_data: Dict[str, Any] = {
            'ticketnumber': ticket_number,
            'title': title,
            'description': description,
            'user_id': user_id,
            'companyid': companyid,
            'createdate': datetime.now(),  # Auto-detect create datetime
            'status': 'TO DO'  # Initial status
        }
        
        # Store user-provided priority separately (not a database column)
        user_provided_priority = priority if priority else None
        
        # Add due_date_time if provided
        if due_date_time:
            try:
                ticket_data['duedatetime'] = datetime.strptime(
                    due_date_time, 
                    '%Y-%m-%d %H:%M:%S'
                )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail='Invalid due_date_time format. Use: YYYY-MM-DD HH:MM:SS'
                )
        
        # Get agents and services (lazy loading)
        intake_agent = get_intake_agent()
        storage_service = get_storage_service()
        file_processor = get_file_processor()
        context_processor = get_context_processor(db_conn)
        
        # Print ticket creation header
        print("\n" + "="*80)
        print("🎫 TICKET CREATION REQUEST RECEIVED (WITH FILE UPLOAD SUPPORT)")
        print("="*80)
        print(f"📝 Title: {ticket_data['title']}")
        print(f"👤 User ID: {ticket_data['user_id']}")
        print(f"📅 Created: {ticket_data['createdate']}")
        if ticket_data.get('duedatetime'):
            print(f"⏰ Due: {ticket_data['duedatetime']}")
        if files:
            print(f"📎 Attachments: {len(files)} file(s)")
            for file in files:
                print(f"   - {file.filename} ({file.content_type})")
        print("="*80)
        
        # Step 1: Process uploaded files
        processed_files = []
        attachment_records = []
        
        if files and len(files) > 0:
            print(f"\n📁 Step 1: Processing {len(files)} uploaded file(s)...")
            
            for idx, file in enumerate(files, 1):
                try:
                    print(f"\n   Processing file {idx}/{len(files)}: {file.filename}")
                    
                    # Save file to storage
                    file_path, file_size = storage_service.save_file(file, ticket_number)
                    file_type = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
                    
                    print(f"   ✓ File saved: {file_path}")
                    
                    # Process file to extract content
                    print(f"   🔍 Extracting content from {file_type.upper()} file...")
                    extracted = file_processor.process_file(file_path, file_type)
                    
                    if extracted['processing_status'] == 'completed':
                        print(f"   ✓ Content extracted successfully")
                        if extracted.get('extracted_text'):
                            text_preview = extracted['extracted_text'][:100]
                            print(f"   📄 Text preview: {text_preview}...")
                    else:
                        print(f"   ⚠️  Processing status: {extracted['processing_status']}")
                        if extracted.get('error'):
                            print(f"   Error: {extracted['error']}")
                    
                    processed_files.append(extracted)
                    
                    # Prepare attachment record for database
                    attachment_records.append({
                        'ticket_number': ticket_number,
                        'file_name': file.filename,
                        'file_type': file.content_type or f'application/{file_type}',
                        'file_size': file_size,
                        'file_path': file_path,
                        'processing_status': extracted['processing_status'],
                        'extracted_content': extracted,
                        'processing_error': extracted.get('error')
                    })
                    
                except Exception as e:
                    print(f"   ❌ Error processing file {file.filename}: {e}")
                    import traceback
                    traceback.print_exc()
                    # Continue with other files
        else:
            print("\n📁 Step 1: No files uploaded, skipping file processing")
        
        # Step 2: Extract metadata using intake agent
        print("\n🧠 Step 2: Extracting metadata from ticket...")
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
        
        # Step 3: Find similar tickets
        print("\n🔍 Step 3: Finding similar tickets...")
        similar_tickets = db_conn.find_similar_tickets(
            title=ticket_data['title'],
            description=ticket_data['description'],
            limit=Config.SIMILAR_TICKETS_LIMIT
        )
        
        # Add user-provided priority to ticket_data for classification
        if user_provided_priority:
            ticket_data['priority'] = user_provided_priority
        
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
        
        # Get the ticket ID from database
        ticket_query = "SELECT id FROM new_tickets WHERE ticketnumber = %s"
        ticket_result = db_conn.execute_query(ticket_query, (ticket_number,))
        ticket_id = ticket_result[0]['id'] if ticket_result else None
        
        if not ticket_id:
            print("⚠️  Warning: Could not retrieve ticket ID")
        
        # Step 7.5: Store attachments in database
        if attachment_records and ticket_id:
            print(f"\n📎 Step 7.5: Storing {len(attachment_records)} attachment record(s)...")
            
            for attachment in attachment_records:
                try:
                    attachment['id'] = ticket_id  # Add ticket ID
                    attachment_id = db_conn.insert_attachment(attachment)
                    print(f"   ✓ Attachment stored: {attachment['file_name']} (ID: {attachment_id})")
                except Exception as e:
                    print(f"   ⚠️  Error storing attachment {attachment['file_name']}: {e}")
        
        # Step 7.6: Generate and store ticket context
        if ticket_id:
            print(f"\n🧠 Step 7.6: Generating enriched ticket context...")
            
            try:
                # Generate context from ticket data and processed files
                ticket_context = context_processor.generate_ticket_context(
                    ticket_data=ticket_data,
                    attachments_data=attachment_records
                )
                
                # Add ticket ID and number
                ticket_context['id'] = ticket_id
                ticket_context['ticket_number'] = ticket_number
                
                # Store context in database
                context_id = db_conn.insert_ticket_context(ticket_context)
                
                if context_id:
                    print(f"   ✓ Ticket context generated and stored (Context ID: {context_id})")
                    print(f"   📊 Context summary: {ticket_context.get('context_summary', 'N/A')[:100]}...")
                    
                    # Show extracted entities
                    if ticket_context.get('entities'):
                        entities = ticket_context['entities']
                        if entities.get('products'):
                            print(f"   🏷️  Products: {', '.join(entities['products'][:3])}")
                        if entities.get('error_codes'):
                            print(f"   ⚠️  Error codes: {', '.join(entities['error_codes'][:3])}")
                else:
                    print(f"   ⚠️  Context generated but not stored in database")
                    
            except Exception as e:
                print(f"   ⚠️  Error generating/storing context: {e}")
                import traceback
                traceback.print_exc()
                # Continue even if context generation fails
        
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
        
        # Query ticket by ticket number across all tables
        ticket = None
        source_table = None
        for table in ["new_tickets", "resolved_tickets", "closed_tickets"]:
            query = f"SELECT * FROM {table} WHERE ticketnumber = %s"
            result = db_conn.execute_query(query, (ticket_number,))
            if result:
                ticket = result[0]
                source_table = table
                break
        
        if not ticket:
            raise HTTPException(
                status_code=404,
                detail=f"Ticket {ticket_number} not found"
            )
        
        # Convert datetime objects to strings for JSON serialization
        ticket_dict = dict(ticket)
        ticket_with_labels = ticket_dict.copy()
        
        # Convert datetime objects to strings
        for key, value in ticket_dict.items():
            if isinstance(value, datetime):
                ticket_dict[key] = value.isoformat()
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
            if field in ticket_dict and ticket_dict[field]:
                value = str(ticket_dict[field])
                label = picklist_loader.get_label(picklist_field, value)
                if label:
                    ticket_with_labels[f'{field}_label'] = label
        
        return TicketDetailResponse(
            success=True,
            ticket=ticket_dict,
            ticket_with_labels=ticket_with_labels
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching ticket: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tickets/by-id/{ticket_id}", response_model=EnhancedTicketDetailResponse)
async def get_ticket_by_id(
    ticket_id: int = Path(..., description="The ticket ID (primary key from source table)", gt=0)
):
    """
    Get complete ticket details by ticket ID including attachments and context.
    Searches across new_tickets, resolved_tickets, and closed_tickets.
    """
    try:
        db_conn = get_db_connection()
        
        # 1. Search for ticket across all tables
        ticket = None
        for table in ["new_tickets", "resolved_tickets", "closed_tickets"]:
            query = f"SELECT * FROM {table} WHERE id = %s"
            result = db_conn.execute_query(query, (ticket_id,))
            if result:
                ticket = result[0]
                break
        
        if not ticket:
            raise HTTPException(
                status_code=404,
                detail=f"Ticket with ID {ticket_id} not found in any table"
            )
        
        ticket_dict = dict(ticket)
        ticket_number = ticket_dict.get("ticketnumber")
        
        # 2. Fetch attachments (mapped by ticket_number for global consistency)
        attachments = db_conn.get_attachments(ticket_number)
        attachment_list = []
        for att in attachments:
            try:
                import json
                extracted_content = att.get("extracted_content")
                if isinstance(extracted_content, (dict, list)):
                    extracted_content = json.dumps(extracted_content)
                elif extracted_content is None:
                    extracted_content = None
                else:
                    extracted_content = str(extracted_content)
                
                attachment_list.append(
                    AttachmentInfo(
                        attachment_id=att.get("attachment_id"),
                        filename=att.get("file_name") or att.get("filename"),
                        file_type=att.get("file_type"),
                        file_size=att.get("file_size"),
                        file_path=att.get("file_path"),
                        processing_status=att.get("processing_status"),
                        extracted_content=extracted_content,
                        uploaded_at=att.get("uploaded_at")
                    )
                )
            except Exception as e:
                print(f"Error processing attachment {att.get('attachment_id')}: {e}")
                continue
                
        # 3. Fetch ticket context
        context_data = db_conn.get_ticket_context(ticket_number)
        context_info = None
        if context_data:
            # Handle potential JSON/Dict fields
            def ensure_dict(val):
                if isinstance(val, str):
                    try:
                        import json
                        return json.loads(val)
                    except:
                        return None
                return val

            context_info = TicketContextInfo(
                context_id=context_data.get("context_id"),
                extracted_text=context_data.get("extracted_text"),
                image_analysis=ensure_dict(context_data.get("image_analysis")),
                table_data=ensure_dict(context_data.get("table_data_parsed")),
                entities=ensure_dict(context_data.get("entities")),
                context_summary=context_data.get("context_summary"),
                created_at=context_data.get("created_at")
            )
        
        # 4. Format labels
        ticket_with_labels = ticket_dict.copy()
        
        # Convert datetime objects to strings
        for key, value in ticket_dict.items():
            if isinstance(value, datetime):
                ticket_dict[key] = value.isoformat()
                ticket_with_labels[key] = value.isoformat()
                
        # Add labels using picklist
        picklist_loader = get_picklist_loader()
        label_fields = {
            'issuetype': 'issuetype',
            'subissuetype': 'subissuetype',
            'ticketcategory': 'ticketcategory',
            'tickettype': 'tickettype',
            'priority': 'priority',
            'status': 'status'
        }
        for field, picklist_field in label_fields.items():
            if field in ticket_dict and ticket_dict[field]:
                label = picklist_loader.get_label(picklist_field, str(ticket_dict[field]))
                if label:
                    ticket_with_labels[f'{field}_label'] = label
        
        return EnhancedTicketDetailResponse(
            success=True,
            ticket=ticket_dict,
            ticket_with_labels=ticket_with_labels,
            attachments=attachment_list,
            context=context_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching ticket by ID: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tickets/{ticket_number}/resolution", response_model=ResolutionResponse)
async def get_ticket_resolution(ticket_number: str = Path(..., description="The ticket number to get resolution for")):
    """
    Get resolution steps for a specific ticket. Searches across all ticket tables.
    """
    try:
        db_conn = get_db_connection()
        
        # Search across all tables
        ticket = None
        for table in ["new_tickets", "resolved_tickets", "closed_tickets"]:
            query = f"SELECT ticketnumber, title, resolution FROM {table} WHERE ticketnumber = %s"
            result = db_conn.execute_query(query, (ticket_number,))
            if result:
                ticket = result[0]
                break
        
        if not ticket:
            raise HTTPException(
                status_code=404,
                detail=f"Ticket {ticket_number} not found"
            )
        
        return ResolutionResponse(
            success=True,
            ticket_number=ticket.get("ticketnumber"),
            resolution=ticket.get("resolution"),
            ticket_title=ticket.get("title")
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


# ========== Technician Ticket Management Routes ==========

class TicketStatusUpdateRequest(BaseModel):
    """Request model for updating ticket status"""
    status: str = Field(..., description="New status (TO DO, In Progress, Resolution Planned, Closed)")
    tech_id: Optional[str] = Field(None, description="Technician ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "In Progress",
                "tech_id": "tech001"
            }
        }


class TicketPriorityUpdateRequest(BaseModel):
    """Request model for updating ticket priority"""
    priority: str = Field(..., description="New priority (High, Medium, Low)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "priority": "High"
            }
        }


class TicketEstimatedHoursUpdateRequest(BaseModel):
    """Request model for updating estimated hours"""
    estimated_hours: float = Field(..., description="Estimated hours to solve the ticket", ge=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "estimated_hours": 4.5
            }
        }


class TicketResolutionPlanUpdateRequest(BaseModel):
    """Request model for updating resolution plan datetime"""
    resolution_plan_datetime: str = Field(..., description="Resolution plan datetime in format: YYYY-MM-DD HH:MM:SS")
    
    class Config:
        json_schema_extra = {
            "example": {
                "resolution_plan_datetime": "2024-12-15 14:00:00"
            }
        }


@router.patch("/tickets/{ticket_number}/status", response_model=GenericResponse)
async def update_ticket_status(
    ticket_number: str = Path(..., description="The ticket number to update"),
    status_update: TicketStatusUpdateRequest = None
):
    """
    Update ticket status with automatic date field updates
    
    Status workflow: TO DO → In Progress → Resolution Planned → Closed
    
    Automatic date updates:
    - When status changes to "In Progress": firstresponsedatetime is set
    - When status changes to "Closed": lastactivitydate, resolveddatetime, completeddate are set
    
    Args:
        ticket_number: Ticket number to update
        status_update: New status and optional tech_id
    
    Returns:
        GenericResponse with success message
    """
    try:
        db_conn = get_db_connection()
        
        # Validate ticket exists
        query = "SELECT ticketnumber FROM new_tickets WHERE ticketnumber = %s"
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Update ticket status (this will auto-update date fields)
        db_conn.update_ticket_status(
            ticket_number=ticket_number,
            new_status=status_update.status,
            tech_id=status_update.tech_id
        )
        
        return GenericResponse(
            success=True,
            message=f"Ticket {ticket_number} status updated to '{status_update.status}' successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating ticket status: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.patch("/tickets/{ticket_number}/priority", response_model=GenericResponse)
async def update_ticket_priority(
    ticket_number: str = Path(..., description="The ticket number to update"),
    priority_update: TicketPriorityUpdateRequest = None
):
    """
    Update ticket priority
    
    Args:
        ticket_number: Ticket number to update
        priority_update: New priority value
    
    Returns:
        GenericResponse with success message
    """
    try:
        db_conn = get_db_connection()
        
        # Validate ticket exists
        query = "SELECT ticketnumber FROM new_tickets WHERE ticketnumber = %s"
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Normalize priority value using picklist
        picklist_loader = get_picklist_loader()
        priority_value = picklist_loader.normalize_value('priority', priority_update.priority)
        
        if not priority_value:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priority value: {priority_update.priority}"
            )
        
        # Update ticket priority
        db_conn.update_ticket_field(
            ticket_number=ticket_number,
            field='priority',
            value=priority_value
        )
        
        return GenericResponse(
            success=True,
            message=f"Ticket {ticket_number} priority updated to '{priority_update.priority}' successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating ticket priority: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.patch("/tickets/{ticket_number}/estimated-hours", response_model=GenericResponse)
async def update_ticket_estimated_hours(
    ticket_number: str = Path(..., description="The ticket number to update"),
    hours_update: TicketEstimatedHoursUpdateRequest = None
):
    """
    Update ticket estimated hours
    
    Args:
        ticket_number: Ticket number to update
        hours_update: Estimated hours to solve the ticket
    
    Returns:
        GenericResponse with success message
    """
    try:
        db_conn = get_db_connection()
        
        # Validate ticket exists
        query = "SELECT ticketnumber FROM new_tickets WHERE ticketnumber = %s"
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Update estimated hours
        db_conn.update_ticket_field(
            ticket_number=ticket_number,
            field='estimatedhours',
            value=hours_update.estimated_hours
        )
        
        return GenericResponse(
            success=True,
            message=f"Ticket {ticket_number} estimated hours updated to {hours_update.estimated_hours} successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating ticket estimated hours: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.patch("/tickets/{ticket_number}/resolution-plan-datetime", response_model=GenericResponse)
async def update_ticket_resolution_plan_datetime(
    ticket_number: str = Path(..., description="The ticket number to update"),
    plan_update: TicketResolutionPlanUpdateRequest = None
):
    """
    Update ticket resolution plan datetime
    
    Args:
        ticket_number: Ticket number to update
        plan_update: Resolution plan datetime
    
    Returns:
        GenericResponse with success message
    """
    try:
        db_conn = get_db_connection()
        
        # Validate ticket exists
        query = "SELECT ticketnumber FROM new_tickets WHERE ticketnumber = %s"
        results = db_conn.execute_query(query, (ticket_number,))
        
        if not results:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Parse datetime
        try:
            resolution_datetime = datetime.strptime(
                plan_update.resolution_plan_datetime,
                '%Y-%m-%d %H:%M:%S'
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail='Invalid resolution_plan_datetime format. Use: YYYY-MM-DD HH:MM:SS'
            )
        
        # Update resolution plan datetime
        db_conn.update_ticket_field(
            ticket_number=ticket_number,
            field='resolutionplandatetime',
            value=resolution_datetime
        )
        
        return GenericResponse(
            success=True,
            message=f"Ticket {ticket_number} resolution plan datetime updated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating ticket resolution plan datetime: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
