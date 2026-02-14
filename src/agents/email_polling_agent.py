"""
Email Polling Agent
Independent background agent for continuous email polling with thread management
"""
import threading
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import traceback

from src.config import Config
from src.database.db_connection import DatabaseConnection
from src.services.email_listener_service import EmailListenerService
from src.agents.intake_classification import IntakeClassificationAgent
from src.agents.resolution_generation import ResolutionGenerationAgent
from src.agents.smart_ticket_assignment import SmartAssignmentAgent
from src.agents.notification_agent import NotificationAgent
from src.utils.picklist_loader import get_picklist_loader
from src.services.context_processor import get_context_processor


class EmailPollingAgent:
    """
    Independent background agent that continuously polls for new emails,
    manages email threads, and creates/updates tickets accordingly.
    """
    
    def __init__(self):
        """Initialize the email polling agent"""
        self.running = False
        self.poll_interval = Config.EMAIL_CHECK_INTERVAL
        self.thread = None
        self.db_connection = None
        self.email_listener = None
        
        # Stats
        self.stats = {
            'started_at': None,
            'last_poll_at': None,
            'total_polls': 0,
            'emails_processed': 0,
            'tickets_created': 0,
            'tickets_updated': 0,
            'duplicates_skipped': 0,
            'errors': 0
        }
        
        # Agents (lazy loaded)
        self._intake_agent = None
        self._resolution_agent = None
        self._assignment_agent = None
        self._notification_agent = None
    
    def _ensure_db_connection(self):
        """Ensure database connection is active"""
        if self.db_connection is None:
            self.db_connection = DatabaseConnection()
        return self.db_connection
    
    def _ensure_tables(self):
        """Ensure the email_checkpoints table exists"""
        db = self._ensure_db_connection()
        
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS email_checkpoints (
            id SERIAL PRIMARY KEY,
            message_id VARCHAR(500) UNIQUE NOT NULL,
            thread_id VARCHAR(500),
            sender_email VARCHAR(255) NOT NULL,
            subject VARCHAR(500),
            ticket_number VARCHAR(100),
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            email_type VARCHAR(20) DEFAULT 'new',
            references_ids TEXT,
            in_reply_to VARCHAR(500),
            action_taken VARCHAR(50) DEFAULT 'ticket_created'
        );
        
        CREATE INDEX IF NOT EXISTS idx_email_checkpoint_message_id ON email_checkpoints(message_id);
        CREATE INDEX IF NOT EXISTS idx_email_checkpoint_thread_id ON email_checkpoints(thread_id);
        CREATE INDEX IF NOT EXISTS idx_email_checkpoint_ticket ON email_checkpoints(ticket_number);
        """
        
        try:
            db.execute_query(create_table_sql, fetch=False)
            print("✅ Email checkpoints table ready")
        except Exception as e:
            print(f"⚠️ Error ensuring email_checkpoints table: {e}")
    
    def _get_intake_agent(self):
        """Lazy load intake agent"""
        if self._intake_agent is None:
            self._intake_agent = IntakeClassificationAgent(self._ensure_db_connection())
        return self._intake_agent
    
    def _get_resolution_agent(self):
        """Lazy load resolution agent"""
        if self._resolution_agent is None:
            self._resolution_agent = ResolutionGenerationAgent(self._ensure_db_connection())
        return self._resolution_agent
    
    def _get_assignment_agent(self):
        """Lazy load assignment agent"""
        if self._assignment_agent is None:
            self._assignment_agent = SmartAssignmentAgent(self._ensure_db_connection())
        return self._assignment_agent
    
    def _get_notification_agent(self):
        """Lazy load notification agent"""
        if self._notification_agent is None:
            self._notification_agent = NotificationAgent()
        return self._notification_agent
    
    def is_duplicate(self, message_id: str) -> bool:
        """
        Check if an email was already processed
        
        Args:
            message_id: The Message-ID header of the email
            
        Returns:
            True if already processed, False otherwise
        """
        if not message_id:
            return False
        
        db = self._ensure_db_connection()
        
        try:
            query = "SELECT id FROM email_checkpoints WHERE message_id = %s"
            result = db.execute_query(query, (message_id,))
            return len(result) > 0 if result else False
        except Exception as e:
            print(f"⚠️ Error checking duplicate: {e}")
            return False
    
    def get_thread_ticket(self, thread_id: str) -> Optional[str]:
        """
        Get the ticket number associated with an email thread
        
        Args:
            thread_id: The thread ID (first Message-ID in the thread)
            
        Returns:
            Ticket number if found, None otherwise
        """
        if not thread_id:
            return None
        
        db = self._ensure_db_connection()
        
        try:
            query = """
                SELECT ticket_number FROM email_checkpoints 
                WHERE thread_id = %s AND ticket_number IS NOT NULL
                ORDER BY processed_at ASC
                LIMIT 1
            """
            result = db.execute_query(query, (thread_id,))
            if result and result[0].get('ticket_number'):
                return result[0]['ticket_number']
            return None
        except Exception as e:
            print(f"⚠️ Error getting thread ticket: {e}")
            return None
    
    def create_checkpoint(
        self, 
        email_data: Dict[str, Any], 
        ticket_number: Optional[str],
        action_taken: str = 'ticket_created'
    ):
        """
        Record a processed email in the checkpoint table
        
        Args:
            email_data: Parsed email data
            ticket_number: Associated ticket number (if any)
            action_taken: What was done with this email
        """
        db = self._ensure_db_connection()
        
        try:
            # Convert references list to comma-separated string
            references_str = ','.join(email_data.get('references', []))
            
            query = """
                INSERT INTO email_checkpoints 
                (message_id, thread_id, sender_email, subject, ticket_number, 
                 email_type, references_ids, in_reply_to, action_taken)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
            """
            
            email_type = 'reply' if email_data.get('is_reply') else 'new'
            
            db.execute_query(query, (
                email_data.get('message_id', ''),
                email_data.get('thread_id', ''),
                email_data.get('sender_email', ''),
                email_data.get('subject', '')[:500] if email_data.get('subject') else '',
                ticket_number,
                email_type,
                references_str[:5000] if references_str else None,
                email_data.get('in_reply_to', '')[:500] if email_data.get('in_reply_to') else None,
                action_taken
            ), fetch=False)
            
        except Exception as e:
            print(f"⚠️ Error creating checkpoint: {e}")
    
    def add_email_to_ticket(self, email_data: Dict[str, Any], ticket_number: str) -> bool:
        """
        Add an email reply as a communication to an existing ticket
        
        Args:
            email_data: Parsed email data
            ticket_number: The ticket to add the communication to
            
        Returns:
            True if successful, False otherwise
        """
        db = self._ensure_db_connection()
        
        try:
            # Get user data
            user_data = email_data.get('user_data', {})
            sender_id = user_data.get('user_id', email_data.get('sender_email', 'unknown'))
            
            # Add as ticket communication
            query = """
                INSERT INTO ticket_communications 
                (ticket_number, sender_type, sender_id, message_text, message_type)
                VALUES (%s, %s, %s, %s, %s)
            """
            
            message_text = f"[Email Reply]\nSubject: {email_data.get('subject', 'No Subject')}\n\n{email_data.get('description', '')}"
            
            db.execute_query(query, (
                ticket_number,
                'user',
                sender_id,
                message_text,
                'text'
            ), fetch=False)
            
            # Update ticket last activity
            update_query = """
                UPDATE new_tickets 
                SET lastactivitydate = CURRENT_TIMESTAMP 
                WHERE ticketnumber = %s
            """
            db.execute_query(update_query, (ticket_number,), fetch=False)
            
            print(f"   ✓ Added email reply to ticket {ticket_number}")
            return True
            
        except Exception as e:
            print(f"   ❌ Error adding email to ticket: {e}")
            return False
    
    def create_ticket_from_email(self, email_data: Dict[str, Any]) -> Optional[str]:
        """
        Create a new ticket from email data
        
        Args:
            email_data: Parsed email data with user info
            
        Returns:
            Ticket number if created, None otherwise
        """
        user_data = email_data.get('user_data', {})
        db = self._ensure_db_connection()
        
        print(f"\n   📧 Creating ticket from email:")
        print(f"      From: {email_data['sender_email']}")
        print(f"      Subject: {email_data['subject']}")
        
        # Generate ticket number
        ticket_number = f"T{datetime.now().strftime('%Y%m%d')}.{datetime.now().strftime('%H%M%S%f')[:9]}"
        
        # Prepare ticket data
        ticket_data = {
            'ticketnumber': ticket_number,
            'title': email_data['subject'],
            'description': email_data['description'],
            'user_id': user_data.get('user_id', 'email_user'),
            'companyid': email_data.get('companyid', '0001'),
            'createdate': datetime.now(),
            'status': 'TO DO',
            'source': 'Email'
        }
        
        try:
            # Process with AI agents
            intake_agent = self._get_intake_agent()
            resolution_agent = self._get_resolution_agent()
            assignment_agent = self._get_assignment_agent()
            picklist_loader = get_picklist_loader()
            
            # Step 1: Extract metadata
            try:
                extracted_metadata = intake_agent.extract_metadata(
                    title=ticket_data['title'],
                    description=ticket_data['description'],
                    model='llama3-8b'
                )
            except Exception as e:
                print(f"      ⚠️ Metadata extraction failed: {e}")
                extracted_metadata = {}
            
            # Step 2: Find similar tickets
            similar_tickets = db.find_similar_tickets(
                title=ticket_data['title'],
                description=ticket_data['description'],
                limit=Config.SIMILAR_TICKETS_LIMIT
            )
            
            # Step 3: Classify ticket
            try:
                classification = intake_agent.classify_ticket(
                    new_ticket_data=ticket_data,
                    extracted_metadata=extracted_metadata,
                    similar_tickets=similar_tickets,
                    model=Config.CLASSIFICATION_MODEL
                )
                
                if classification:
                    for field_key, db_field in [
                        ('ISSUETYPE', 'issuetype'),
                        ('SUBISSUETYPE', 'subissuetype'),
                        ('TICKETCATEGORY', 'ticketcategory'),
                        ('TICKETTYPE', 'tickettype'),
                        ('PRIORITY', 'priority'),
                        ('STATUS', 'status')
                    ]:
                        value = classification.get(field_key)
                        if isinstance(value, dict):
                            raw_value = value.get('Value') or value.get('value')
                        else:
                            raw_value = value
                        
                        if raw_value:
                            normalized = picklist_loader.normalize_value(db_field, str(raw_value))
                            ticket_data[db_field] = normalized if normalized else str(raw_value)
                            
            except Exception as e:
                print(f"      ⚠️ Classification failed: {e}")
                classification = {}
            
            # Step 4: Generate resolution
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
                print(f"      ⚠️ Resolution generation failed: {e}")
            
            # Step 5: Assign technician
            assigned_tech_id = None
            try:
                assigned_tech_id = assignment_agent.assign_ticket(
                    ticket_data=ticket_data,
                    classification=classification
                )
                if assigned_tech_id:
                    ticket_data['assigned_tech_id'] = assigned_tech_id
            except Exception as e:
                print(f"      ⚠️ Assignment failed: {e}")
            
            # Step 6: Insert ticket
            ticket_number = db.insert_ticket(ticket_data)
            
            if not ticket_number:
                raise Exception("Failed to insert ticket")
            
            print(f"      ✓ Ticket created: {ticket_number}")
            
            # Get ticket ID for attachments/context
            ticket_query = "SELECT id FROM new_tickets WHERE ticketnumber = %s"
            ticket_result = db.execute_query(ticket_query, (ticket_number,))
            ticket_id = ticket_result[0]['id'] if ticket_result else None
            
            # Process attachments if any
            if email_data.get('attachments') and ticket_id:
                email_listener = EmailListenerService(db)
                attachment_records = email_listener.save_email_attachments(
                    email_data['attachments'],
                    ticket_number
                )
                for attachment in attachment_records:
                    try:
                        attachment['id'] = ticket_id
                        db.insert_attachment(attachment)
                    except Exception as e:
                        print(f"      ⚠️ Error storing attachment: {e}")
            
            # Generate context
            if ticket_id:
                try:
                    context_processor = get_context_processor(db)
                    ticket_context = context_processor.generate_ticket_context(
                        ticket_data=ticket_data,
                        attachments_data=[]
                    )
                    ticket_context['id'] = ticket_id
                    ticket_context['ticket_number'] = ticket_number
                    db.insert_ticket_context(ticket_context)
                except Exception as e:
                    print(f"      ⚠️ Context generation failed: {e}")
            
            # Send notifications
            try:
                notification_agent = self._get_notification_agent()
                
                tech_data = None
                if assigned_tech_id:
                    tech_query = "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id = %s"
                    tech_results = db.execute_query(tech_query, (assigned_tech_id,))
                    if tech_results:
                        tech_data = tech_results[0]
                        notification_agent.notify_technician(ticket_data, tech_data)
                
                if user_data.get('user_mail'):
                    notification_agent.notify_user(ticket_data, user_data, tech_data)
                    
            except Exception as e:
                print(f"      ⚠️ Notification failed: {e}")
            
            return ticket_number
            
        except Exception as e:
            print(f"      ❌ Error creating ticket: {e}")
            traceback.print_exc()
            return None
    
    def process_single_email(self, email_data: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """
        Process a single email with thread detection and duplicate prevention
        
        Args:
            email_data: Parsed email data
            
        Returns:
            Tuple of (action_taken, ticket_number)
            action_taken: 'skipped', 'ticket_created', 'ticket_updated', 'invalid'
        """
        message_id = email_data.get('message_id', '')
        thread_id = email_data.get('thread_id', '')
        is_reply = email_data.get('is_reply', False)
        
        # Check for duplicate
        if self.is_duplicate(message_id):
            print(f"   ⏭️ Skipping duplicate: {message_id[:50]}...")
            self.stats['duplicates_skipped'] += 1
            return ('skipped', None)
        
        # Validate sender
        db = self._ensure_db_connection()
        email_listener = EmailListenerService(db)
        
        user_data = email_listener.validate_sender(email_data['sender_email'])
        if not user_data:
            print(f"   ⚠️ Sender not registered: {email_data['sender_email']}")
            self.create_checkpoint(email_data, None, 'invalid_sender')
            return ('invalid', None)
        
        email_data['user_data'] = user_data
        
        # Get organization
        companyid = email_listener.get_user_organization(user_data['user_id'])
        if not companyid:
            print(f"   ⚠️ No organization for user: {user_data['user_id']}")
            self.create_checkpoint(email_data, None, 'no_organization')
            return ('invalid', None)
        
        email_data['companyid'] = companyid
        
        # Check if this is a reply to an existing thread
        if is_reply:
            existing_ticket = self.get_thread_ticket(thread_id)
            
            if existing_ticket:
                # Add to existing ticket
                success = self.add_email_to_ticket(email_data, existing_ticket)
                if success:
                    self.create_checkpoint(email_data, existing_ticket, 'ticket_updated')
                    self.stats['tickets_updated'] += 1
                    return ('ticket_updated', existing_ticket)
                else:
                    self.stats['errors'] += 1
                    return ('error', None)
        
        # Create new ticket
        ticket_number = self.create_ticket_from_email(email_data)
        
        if ticket_number:
            self.create_checkpoint(email_data, ticket_number, 'ticket_created')
            self.stats['tickets_created'] += 1
            return ('ticket_created', ticket_number)
        else:
            self.create_checkpoint(email_data, None, 'creation_failed')
            self.stats['errors'] += 1
            return ('error', None)
    
    def poll_once(self) -> Dict[str, Any]:
        """
        Perform a single poll cycle
        
        Returns:
            Dictionary with poll results
        """
        result = {
            'timestamp': datetime.now().isoformat(),
            'emails_found': 0,
            'processed': [],
            'errors': []
        }
        
        try:
            db = self._ensure_db_connection()
            email_listener = EmailListenerService(db)
            
            # Connect and fetch emails
            if not email_listener.connect():
                result['errors'].append("Failed to connect to IMAP")
                return result
            
            emails = email_listener.fetch_unread_emails()
            result['emails_found'] = len(emails)
            
            print(f"\n{'='*60}")
            print(f"📧 POLL CYCLE: Found {len(emails)} unread email(s)")
            print(f"{'='*60}")
            
            for email_data in emails:
                try:
                    action, ticket = self.process_single_email(email_data)
                    result['processed'].append({
                        'message_id': email_data.get('message_id', '')[:50],
                        'subject': email_data.get('subject', '')[:50],
                        'action': action,
                        'ticket': ticket
                    })
                    
                    # Mark as processed in IMAP
                    if action in ['ticket_created', 'ticket_updated']:
                        email_listener.connect()
                        email_listener.mark_as_processed(email_data['email_id'])
                        
                    self.stats['emails_processed'] += 1
                    
                except Exception as e:
                    print(f"   ❌ Error processing email: {e}")
                    result['errors'].append(str(e))
                    self.stats['errors'] += 1
            
            email_listener.disconnect()
            
        except Exception as e:
            result['errors'].append(str(e))
            print(f"❌ Poll error: {e}")
            traceback.print_exc()
        
        self.stats['last_poll_at'] = datetime.now().isoformat()
        self.stats['total_polls'] += 1
        
        return result
    
    def _polling_loop(self):
        """Background polling loop"""
        print(f"\n{'='*60}")
        print(f"🚀 EMAIL POLLING AGENT STARTED")
        print(f"   Poll interval: {self.poll_interval} seconds")
        print(f"{'='*60}\n")
        
        self._ensure_tables()
        
        while self.running:
            try:
                self.poll_once()
            except Exception as e:
                print(f"❌ Error in polling loop: {e}")
                traceback.print_exc()
            
            # Wait for next poll interval
            for _ in range(self.poll_interval):
                if not self.running:
                    break
                time.sleep(1)
        
        print(f"\n{'='*60}")
        print(f"🛑 EMAIL POLLING AGENT STOPPED")
        print(f"{'='*60}\n")
    
    def start(self) -> bool:
        """
        Start the background polling thread
        
        Returns:
            True if started, False if already running
        """
        if self.running:
            return False
        
        self.running = True
        self.stats['started_at'] = datetime.now().isoformat()
        
        self.thread = threading.Thread(target=self._polling_loop, daemon=True)
        self.thread.start()
        
        return True
    
    def stop(self) -> bool:
        """
        Stop the background polling
        
        Returns:
            True if stopped, False if not running
        """
        if not self.running:
            return False
        
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
        
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get agent status and statistics"""
        return {
            'running': self.running,
            'poll_interval_seconds': self.poll_interval,
            **self.stats
        }
    
    def get_threads(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get list of email threads with their ticket associations
        
        Args:
            limit: Maximum number of threads to return
            
        Returns:
            List of thread information
        """
        db = self._ensure_db_connection()
        
        try:
            query = """
                SELECT 
                    thread_id,
                    MIN(processed_at) as first_email_at,
                    MAX(processed_at) as last_email_at,
                    COUNT(*) as email_count,
                    MAX(ticket_number) as ticket_number,
                    MIN(subject) as subject
                FROM email_checkpoints
                WHERE thread_id IS NOT NULL
                GROUP BY thread_id
                ORDER BY MAX(processed_at) DESC
                LIMIT %s
            """
            result = db.execute_query(query, (limit,))
            return [dict(row) for row in result] if result else []
        except Exception as e:
            print(f"⚠️ Error getting threads: {e}")
            return []


# Singleton instance
_email_polling_agent = None

def get_email_polling_agent() -> EmailPollingAgent:
    """Get or create the email polling agent singleton"""
    global _email_polling_agent
    if _email_polling_agent is None:
        _email_polling_agent = EmailPollingAgent()
    return _email_polling_agent
