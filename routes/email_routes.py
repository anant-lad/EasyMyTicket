"""
Email Routes for Email-to-Ticket Creation
Handles processing incoming emails to create support tickets
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.database.db_connection import DatabaseConnection
from src.services.email_listener_service import get_email_listener_service
from src.agents.intake_classification import IntakeClassificationAgent
from src.agents.resolution_generation import ResolutionGenerationAgent
from src.agents.smart_ticket_assignment import SmartAssignmentAgent
from src.agents.notification_agent import NotificationAgent
from src.config import Config
from src.utils.picklist_loader import get_picklist_loader
from src.services.context_processor import get_context_processor

router = APIRouter()

# Lazy loading
_db_conn = None
_intake_agent = None
_resolution_agent = None
_assignment_agent = None
_notification_agent = None


def get_db_connection():
    """Get or create database connection"""
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn


def get_intake_agent():
    """Get or create intake agent"""
    global _intake_agent
    if _intake_agent is None:
        _intake_agent = IntakeClassificationAgent(get_db_connection())
    return _intake_agent


def get_resolution_agent():
    """Get or create resolution generation agent"""
    global _resolution_agent
    if _resolution_agent is None:
        _resolution_agent = ResolutionGenerationAgent(get_db_connection())
    return _resolution_agent


def get_assignment_agent():
    """Get or create smart assignment agent"""
    global _assignment_agent
    if _assignment_agent is None:
        _assignment_agent = SmartAssignmentAgent(get_db_connection())
    return _assignment_agent


def get_notification_agent():
    """Get or create notification agent"""
    global _notification_agent
    if _notification_agent is None:
        _notification_agent = NotificationAgent()
    return _notification_agent


# Response Models
class EmailTicketCreated(BaseModel):
    """Info about a ticket created from email"""
    ticket_number: str
    title: str
    sender_email: str
    user_id: str
    attachments_count: int


class InvalidEmail(BaseModel):
    """Info about an email that couldn't be processed"""
    sender_email: str
    subject: str
    reason: str


class EmailProcessResponse(BaseModel):
    """Response model for email processing endpoint"""
    success: bool
    message: str
    emails_fetched: int
    tickets_created: List[EmailTicketCreated]
    invalid_emails: List[InvalidEmail]
    errors: List[str]


class EmailStatusResponse(BaseModel):
    """Response model for email status endpoint"""
    success: bool
    imap_server: str
    support_email: str
    imap_configured: bool
    last_check: Optional[str] = None


@router.post("/email/process", response_model=EmailProcessResponse)
async def process_emails():
    """
    Process incoming emails and create tickets
    
    This endpoint:
    1. Connects to the support email inbox via IMAP
    2. Fetches all unread emails
    3. Validates sender email against registered users
    4. Creates tickets for valid emails using the standard ticket creation flow
    5. Marks processed emails as read
    
    Returns:
        EmailProcessResponse with list of created tickets and any errors
    """
    print("\n" + "="*80)
    print("📧 EMAIL-TO-TICKET PROCESSING STARTED")
    print("="*80)
    
    response = EmailProcessResponse(
        success=True,
        message="Email processing completed",
        emails_fetched=0,
        tickets_created=[],
        invalid_emails=[],
        errors=[]
    )
    
    try:
        db_conn = get_db_connection()
        email_listener = get_email_listener_service(db_conn)
        
        # Process emails
        result = email_listener.process_emails()
        response.emails_fetched = result['emails_fetched']
        
        if result['errors']:
            response.errors.extend(result['errors'])
        
        # Handle invalid emails
        for invalid in result['invalid_emails']:
            response.invalid_emails.append(InvalidEmail(
                sender_email=invalid['sender_email'],
                subject=invalid.get('subject', 'No Subject'),
                reason=invalid.get('rejection_reason', 'Unknown reason')
            ))
            print(f"⚠️ Invalid email from {invalid['sender_email']}: {invalid.get('rejection_reason')}")
        
        # Create tickets for valid emails
        for email_data in result['valid_emails']:
            try:
                ticket_info = await create_ticket_from_email(email_data, db_conn, email_listener)
                if ticket_info:
                    response.tickets_created.append(ticket_info)
                    
                    # Mark email as processed
                    email_listener.connect()
                    email_listener.mark_as_processed(email_data['email_id'])
                    email_listener.disconnect()
                    
            except Exception as e:
                error_msg = f"Error creating ticket from email {email_data['sender_email']}: {str(e)}"
                print(f"❌ {error_msg}")
                response.errors.append(error_msg)
        
        response.message = f"Processed {response.emails_fetched} emails, created {len(response.tickets_created)} tickets"
        
        print("="*80)
        print(f"✅ EMAIL PROCESSING COMPLETED")
        print(f"   Emails fetched: {response.emails_fetched}")
        print(f"   Tickets created: {len(response.tickets_created)}")
        print(f"   Invalid emails: {len(response.invalid_emails)}")
        print(f"   Errors: {len(response.errors)}")
        print("="*80 + "\n")
        
    except Exception as e:
        response.success = False
        response.message = f"Email processing failed: {str(e)}"
        response.errors.append(str(e))
        print(f"❌ Email processing failed: {e}")
        import traceback
        traceback.print_exc()
    
    return response


async def create_ticket_from_email(
    email_data: Dict[str, Any], 
    db_conn: DatabaseConnection,
    email_listener
) -> Optional[EmailTicketCreated]:
    """
    Create a ticket from parsed email data using the standard ticket creation workflow
    
    Args:
        email_data: Parsed email data with user info and companyid
        db_conn: Database connection
        email_listener: Email listener service for attachment handling
        
    Returns:
        EmailTicketCreated info or None if failed
    """
    user_data = email_data['user_data']
    
    print(f"\n📧 Creating ticket from email:")
    print(f"   From: {email_data['sender_email']} ({user_data['user_name']})")
    print(f"   Subject: {email_data['subject']}")
    print(f"   Attachments: {len(email_data.get('attachments', []))}")
    
    # Generate ticket number
    ticket_number = f"T{datetime.now().strftime('%Y%m%d')}.{datetime.now().strftime('%H%M%S')}"
    
    # Prepare ticket data
    ticket_data = {
        'ticketnumber': ticket_number,
        'title': email_data['subject'],
        'description': email_data['description'],
        'user_id': user_data['user_id'],
        'companyid': email_data['companyid'],
        'createdate': datetime.now(),
        'status': 'TO DO',
        'source': 'Email'  # Mark source as email
    }
    
    # Get agents and processors
    intake_agent = get_intake_agent()
    resolution_agent = get_resolution_agent()
    assignment_agent = get_assignment_agent()
    context_processor = get_context_processor(db_conn)
    picklist_loader = get_picklist_loader()
    
    # Process attachments if any
    attachment_records = []
    if email_data.get('attachments'):
        print(f"   📎 Processing {len(email_data['attachments'])} attachments...")
        attachment_records = email_listener.save_email_attachments(
            email_data['attachments'],
            ticket_number
        )
    
    # Step 1: Extract metadata
    print("   🧠 Extracting metadata...")
    try:
        extracted_metadata = intake_agent.extract_metadata(
            title=ticket_data['title'],
            description=ticket_data['description'],
            model='llama3-8b'
        )
    except Exception as e:
        print(f"   ⚠️ Metadata extraction failed: {e}")
        extracted_metadata = {}
    
    # Step 2: Find similar tickets
    print("   🔍 Finding similar tickets...")
    similar_tickets = db_conn.find_similar_tickets(
        title=ticket_data['title'],
        description=ticket_data['description'],
        limit=Config.SIMILAR_TICKETS_LIMIT
    )
    
    # Step 3: Classify ticket
    print("   📋 Classifying ticket...")
    try:
        classification = intake_agent.classify_ticket(
            new_ticket_data=ticket_data,
            extracted_metadata=extracted_metadata,
            similar_tickets=similar_tickets,
            model=Config.CLASSIFICATION_MODEL
        )
        
        # Normalize classification fields
        if classification:
            normalize_fields = ['ISSUETYPE', 'SUBISSUETYPE', 'TICKETCATEGORY', 'TICKETTYPE', 'PRIORITY', 'STATUS']
            db_fields = ['issuetype', 'subissuetype', 'ticketcategory', 'tickettype', 'priority', 'status']
            
            for field_key, db_field in zip(normalize_fields, db_fields):
                value = classification.get(field_key)
                if isinstance(value, dict):
                    raw_value = value.get('Value') or value.get('value')
                else:
                    raw_value = value
                
                if raw_value:
                    normalized = picklist_loader.normalize_value(db_field, str(raw_value))
                    if normalized:
                        ticket_data[db_field] = normalized
                    else:
                        ticket_data[db_field] = str(raw_value)
                        
    except Exception as e:
        print(f"   ⚠️ Classification failed: {e}")
        classification = {}
    
    # Step 4: Generate resolution
    print("   💡 Generating resolution...")
    try:
        generated_resolution = resolution_agent.generate_resolution(
            ticket_data=ticket_data,
            extracted_metadata=extracted_metadata,
            similar_tickets=similar_tickets,
            model=Config.CLASSIFICATION_MODEL
        )
        if generated_resolution:
            ticket_data['resolution'] = generated_resolution
    except Exception as e:
        print(f"   ⚠️ Resolution generation failed: {e}")
    
    # Step 5: Assign technician
    print("   👤 Assigning technician...")
    assigned_tech_id = None
    try:
        assigned_tech_id = assignment_agent.assign_ticket(
            ticket_data=ticket_data,
            classification=classification
        )
        if assigned_tech_id:
            ticket_data['assigned_tech_id'] = assigned_tech_id
            print(f"   ✓ Assigned to: {assigned_tech_id}")
    except Exception as e:
        print(f"   ⚠️ Assignment failed: {e}")
    
    # Step 6: Insert ticket into database
    print("   💾 Inserting ticket into database...")
    ticket_number = db_conn.insert_ticket(ticket_data)
    
    if not ticket_number:
        raise Exception("Failed to insert ticket into database")
    
    print(f"   ✓ Ticket created: {ticket_number}")
    
    # Get ticket ID
    ticket_query = "SELECT id FROM new_tickets WHERE ticketnumber = %s"
    ticket_result = db_conn.execute_query(ticket_query, (ticket_number,))
    ticket_id = ticket_result[0]['id'] if ticket_result else None
    
    # Store attachments
    if attachment_records and ticket_id:
        print(f"   📎 Storing {len(attachment_records)} attachment records...")
        for attachment in attachment_records:
            try:
                attachment['id'] = ticket_id
                db_conn.insert_attachment(attachment)
            except Exception as e:
                print(f"   ⚠️ Error storing attachment: {e}")
    
    # Generate and store context
    if ticket_id:
        try:
            ticket_context = context_processor.generate_ticket_context(
                ticket_data=ticket_data,
                attachments_data=attachment_records
            )
            ticket_context['id'] = ticket_id
            ticket_context['ticket_number'] = ticket_number
            db_conn.insert_ticket_context(ticket_context)
        except Exception as e:
            print(f"   ⚠️ Context generation failed: {e}")
    
    # Send notifications
    try:
        notification_agent = get_notification_agent()
        
        # Get technician data if assigned
        tech_data = None
        if assigned_tech_id:
            tech_query = "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id = %s"
            tech_results = db_conn.execute_query(tech_query, (assigned_tech_id,))
            if tech_results:
                tech_data = tech_results[0]
                notification_agent.notify_technician(ticket_data, tech_data)
        
        # Notify user
        if user_data.get('user_mail'):
            notification_agent.notify_user(ticket_data, user_data, tech_data)
            
    except Exception as e:
        print(f"   ⚠️ Notification failed: {e}")
    
    print(f"   ✅ Ticket {ticket_number} created successfully from email")
    
    return EmailTicketCreated(
        ticket_number=ticket_number,
        title=ticket_data['title'],
        sender_email=email_data['sender_email'],
        user_id=user_data['user_id'],
        attachments_count=len(attachment_records)
    )


@router.get("/email/status", response_model=EmailStatusResponse)
async def get_email_status():
    """
    Get email listener configuration status
    
    Returns:
        EmailStatusResponse with configuration info
    """
    from src.agents.email_polling_agent import get_email_polling_agent
    
    agent = get_email_polling_agent()
    status = agent.get_status()
    
    return EmailStatusResponse(
        success=True,
        imap_server=Config.IMAP_SERVER,
        support_email=Config.SUPPORT_EMAIL or "Not configured",
        imap_configured=bool(Config.SUPPORT_EMAIL and Config.SUPPORT_EMAIL_APP_PASSWORD),
        last_check=status.get('last_poll_at')
    )


# ============================================================================
# Agent Control Endpoints
# ============================================================================

class AgentStatusResponse(BaseModel):
    """Response model for agent status"""
    running: bool
    poll_interval_seconds: int
    started_at: Optional[str] = None
    last_poll_at: Optional[str] = None
    total_polls: int = 0
    emails_processed: int = 0
    tickets_created: int = 0
    tickets_updated: int = 0
    duplicates_skipped: int = 0
    errors: int = 0


class AgentControlResponse(BaseModel):
    """Response model for agent control operations"""
    success: bool
    message: str
    status: AgentStatusResponse


class EmailThreadInfo(BaseModel):
    """Info about an email thread"""
    thread_id: str
    first_email_at: Optional[str] = None
    last_email_at: Optional[str] = None
    email_count: int
    ticket_number: Optional[str] = None
    subject: Optional[str] = None


class ThreadListResponse(BaseModel):
    """Response model for thread listing"""
    success: bool
    count: int
    threads: List[EmailThreadInfo]


@router.post("/email/agent/start", response_model=AgentControlResponse)
async def start_email_agent():
    """
    Start the background email polling agent
    
    The agent will continuously poll for new emails at the configured interval
    and automatically create/update tickets based on email threads.
    """
    from src.agents.email_polling_agent import get_email_polling_agent
    
    agent = get_email_polling_agent()
    
    if agent.running:
        status = agent.get_status()
        return AgentControlResponse(
            success=False,
            message="Agent is already running",
            status=AgentStatusResponse(**status)
        )
    
    started = agent.start()
    status = agent.get_status()
    
    return AgentControlResponse(
        success=started,
        message="Email polling agent started successfully" if started else "Failed to start agent",
        status=AgentStatusResponse(**status)
    )


@router.post("/email/agent/stop", response_model=AgentControlResponse)
async def stop_email_agent():
    """
    Stop the background email polling agent
    
    Gracefully stops the polling loop. Currently processing emails will complete.
    """
    from src.agents.email_polling_agent import get_email_polling_agent
    
    agent = get_email_polling_agent()
    
    if not agent.running:
        status = agent.get_status()
        return AgentControlResponse(
            success=False,
            message="Agent is not currently running",
            status=AgentStatusResponse(**status)
        )
    
    stopped = agent.stop()
    status = agent.get_status()
    
    return AgentControlResponse(
        success=stopped,
        message="Email polling agent stopped successfully" if stopped else "Failed to stop agent",
        status=AgentStatusResponse(**status)
    )


@router.get("/email/agent/status", response_model=AgentControlResponse)
async def get_agent_status():
    """
    Get the current status of the email polling agent
    
    Returns running state and statistics about processed emails.
    """
    from src.agents.email_polling_agent import get_email_polling_agent
    
    agent = get_email_polling_agent()
    status = agent.get_status()
    
    return AgentControlResponse(
        success=True,
        message="Running" if status['running'] else "Stopped",
        status=AgentStatusResponse(**status)
    )


@router.post("/email/agent/poll")
async def trigger_single_poll():
    """
    Trigger a single poll cycle (useful for testing)
    
    Runs one poll cycle immediately without starting the background agent.
    """
    from src.agents.email_polling_agent import get_email_polling_agent
    
    agent = get_email_polling_agent()
    result = agent.poll_once()
    
    return {
        "success": len(result.get('errors', [])) == 0,
        "message": f"Polled {result['emails_found']} emails",
        **result
    }


@router.get("/email/threads", response_model=ThreadListResponse)
async def list_email_threads(limit: int = 50):
    """
    List email threads with their ticket associations
    
    Shows email threads that have been processed, including:
    - Thread ID and subject
    - Number of emails in thread
    - Associated ticket number
    - First and last email timestamps
    """
    from src.agents.email_polling_agent import get_email_polling_agent
    
    agent = get_email_polling_agent()
    threads = agent.get_threads(limit=limit)
    
    thread_list = []
    for t in threads:
        thread_list.append(EmailThreadInfo(
            thread_id=t.get('thread_id', ''),
            first_email_at=str(t.get('first_email_at')) if t.get('first_email_at') else None,
            last_email_at=str(t.get('last_email_at')) if t.get('last_email_at') else None,
            email_count=t.get('email_count', 0),
            ticket_number=t.get('ticket_number'),
            subject=t.get('subject')
        ))
    
    return ThreadListResponse(
        success=True,
        count=len(thread_list),
        threads=thread_list
    )
