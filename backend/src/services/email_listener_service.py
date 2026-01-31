"""
Email Listener Service
Handles fetching emails from the support inbox via IMAP and creating tickets
"""
import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import os
import re
import tempfile

from src.config import Config
from src.services.storage_service import get_storage_service
from src.services.file_processor import get_file_processor


class EmailListenerService:
    """
    Service for connecting to support email inbox via IMAP,
    fetching emails, and preparing them for ticket creation.
    """
    
    def __init__(self, db_connection=None):
        """
        Initialize the email listener service
        
        Args:
            db_connection: Database connection for user validation
        """
        self.db_connection = db_connection
        self.imap_server = Config.IMAP_SERVER
        self.imap_port = Config.IMAP_PORT
        self.email_address = Config.SUPPORT_EMAIL
        self.email_password = Config.SUPPORT_EMAIL_APP_PASSWORD
        self.use_ssl = Config.IMAP_USE_SSL
        self.mail = None
        self.storage_service = get_storage_service()
        self.file_processor = get_file_processor()
        
    def connect(self) -> bool:
        """
        Connect to the IMAP server
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            if not self.email_address or not self.email_password:
                print("❌ Email configuration missing. Cannot connect to IMAP.")
                return False
            
            if self.use_ssl:
                self.mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            else:
                self.mail = imaplib.IMAP4(self.imap_server, self.imap_port)
            
            self.mail.login(self.email_address, self.email_password)
            print(f"✅ Connected to IMAP server: {self.imap_server}")
            return True
            
        except imaplib.IMAP4.error as e:
            print(f"❌ IMAP authentication failed: {e}")
            return False
        except Exception as e:
            print(f"❌ Failed to connect to IMAP server: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the IMAP server"""
        if self.mail:
            try:
                self.mail.logout()
                print("✅ Disconnected from IMAP server")
            except Exception as e:
                print(f"⚠️ Error disconnecting: {e}")
            finally:
                self.mail = None
    
    def _decode_header_value(self, value: str) -> str:
        """Decode email header value handling various encodings"""
        if not value:
            return ""
        
        decoded_parts = decode_header(value)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result.append(part.decode(encoding or 'utf-8', errors='replace'))
                except (LookupError, UnicodeDecodeError):
                    result.append(part.decode('utf-8', errors='replace'))
            else:
                result.append(part)
        return ''.join(result)
    
    def _get_email_body(self, msg) -> Tuple[str, str]:
        """
        Extract email body (plain text and HTML versions)
        
        Returns:
            Tuple of (plain_text_body, html_body)
        """
        plain_body = ""
        html_body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                # Skip attachments
                if "attachment" in content_disposition:
                    continue
                
                try:
                    body = part.get_payload(decode=True)
                    if body:
                        charset = part.get_content_charset() or 'utf-8'
                        body_text = body.decode(charset, errors='replace')
                        
                        if content_type == "text/plain":
                            plain_body = body_text
                        elif content_type == "text/html":
                            html_body = body_text
                except Exception as e:
                    print(f"⚠️ Error decoding email part: {e}")
        else:
            # Not multipart - single body
            content_type = msg.get_content_type()
            try:
                body = msg.get_payload(decode=True)
                if body:
                    charset = msg.get_content_charset() or 'utf-8'
                    body_text = body.decode(charset, errors='replace')
                    
                    if content_type == "text/plain":
                        plain_body = body_text
                    elif content_type == "text/html":
                        html_body = body_text
            except Exception as e:
                print(f"⚠️ Error decoding email body: {e}")
        
        return plain_body, html_body
    
    def _extract_attachments(self, msg) -> List[Dict[str, Any]]:
        """
        Extract attachments from email message
        
        Returns:
            List of attachment dictionaries with filename, content_type, and data
        """
        attachments = []
        
        if not msg.is_multipart():
            return attachments
        
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if "attachment" in content_disposition or part.get_filename():
                filename = part.get_filename()
                if filename:
                    filename = self._decode_header_value(filename)
                    content_type = part.get_content_type()
                    data = part.get_payload(decode=True)
                    
                    if data:
                        attachments.append({
                            'filename': filename,
                            'content_type': content_type,
                            'data': data,
                            'size': len(data)
                        })
        
        return attachments
    
    def _clean_html_to_text(self, html: str) -> str:
        """Convert HTML to plain text (basic cleaning)"""
        if not html:
            return ""
        
        # Remove style and script tags
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        
        # Replace common HTML entities
        html = html.replace('&nbsp;', ' ')
        html = html.replace('&amp;', '&')
        html = html.replace('&lt;', '<')
        html = html.replace('&gt;', '>')
        html = html.replace('&quot;', '"')
        
        # Replace br and p tags with newlines
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</p>', '\n\n', html, flags=re.IGNORECASE)
        
        # Remove all remaining HTML tags
        html = re.sub(r'<[^>]+>', '', html)
        
        # Clean up whitespace
        html = re.sub(r'\n{3,}', '\n\n', html)
        html = html.strip()
        
        return html
    
    def parse_email(self, email_data: bytes, email_id: str) -> Dict[str, Any]:
        """
        Parse email message into structured data including thread headers
        
        Args:
            email_data: Raw email data
            email_id: Email ID for reference
            
        Returns:
            Dictionary with parsed email data including thread information
        """
        msg = email.message_from_bytes(email_data)
        
        # Extract sender
        from_header = msg.get("From", "")
        sender_name, sender_email = parseaddr(from_header)
        sender_name = self._decode_header_value(sender_name)
        
        # Extract subject (becomes ticket title)
        subject = self._decode_header_value(msg.get("Subject", "No Subject"))
        
        # Extract date
        date_str = msg.get("Date", "")
        
        # Extract thread-related headers
        message_id = msg.get("Message-ID", "").strip()
        in_reply_to = msg.get("In-Reply-To", "").strip()
        references = msg.get("References", "").strip()
        
        # Clean up Message-ID (remove angle brackets if present)
        if message_id.startswith("<") and message_id.endswith(">"):
            message_id = message_id[1:-1]
        if in_reply_to.startswith("<") and in_reply_to.endswith(">"):
            in_reply_to = in_reply_to[1:-1]
        
        # Parse references into list
        references_list = []
        if references:
            # References can be space or newline separated
            refs = re.split(r'[\s\n]+', references)
            for ref in refs:
                ref = ref.strip()
                if ref.startswith("<") and ref.endswith(">"):
                    ref = ref[1:-1]
                if ref:
                    references_list.append(ref)
        
        # Determine thread ID (first reference, or message_id if new thread)
        thread_id = references_list[0] if references_list else message_id
        
        # Determine if this is a reply
        is_reply = bool(in_reply_to or references_list)
        
        # Extract body
        plain_body, html_body = self._get_email_body(msg)
        
        # Use plain text if available, otherwise convert HTML
        description = plain_body if plain_body else self._clean_html_to_text(html_body)
        
        # Extract attachments
        attachments = self._extract_attachments(msg)
        
        return {
            'email_id': email_id,
            'message_id': message_id,
            'thread_id': thread_id,
            'in_reply_to': in_reply_to,
            'references': references_list,
            'is_reply': is_reply,
            'sender_email': sender_email.lower().strip(),
            'sender_name': sender_name,
            'subject': subject,
            'description': description,
            'html_body': html_body,
            'date': date_str,
            'attachments': attachments,
            'has_attachments': len(attachments) > 0
        }
    
    def validate_sender(self, sender_email: str) -> Optional[Dict[str, Any]]:
        """
        Validate that sender email exists in user_data table
        
        Args:
            sender_email: Email address of the sender
            
        Returns:
            User data dictionary if found, None otherwise
        """
        if not self.db_connection:
            print("⚠️ No database connection available for sender validation")
            return None
        
        try:
            query = """
                SELECT user_id, user_name, user_mail 
                FROM user_data 
                WHERE LOWER(user_mail) = LOWER(%s)
            """
            result = self.db_connection.execute_query(query, (sender_email,))
            
            if result and len(result) > 0:
                return dict(result[0])
            
            return None
            
        except Exception as e:
            print(f"❌ Error validating sender: {e}")
            return None
    
    def get_user_organization(self, user_id: str) -> Optional[str]:
        """
        Get organization/companyid for a user
        Currently returns a default companyid - can be extended to look up user's organization
        
        Args:
            user_id: User ID to look up
            
        Returns:
            companyid string or None
        """
        if not self.db_connection:
            return None
        
        try:
            # Try to find organization from user's recent tickets
            query = """
                SELECT companyid 
                FROM new_tickets 
                WHERE user_id = %s AND companyid IS NOT NULL
                ORDER BY createdate DESC
                LIMIT 1
            """
            result = self.db_connection.execute_query(query, (user_id,))
            
            if result and result[0].get('companyid'):
                return result[0]['companyid']
            
            # Fallback: get first available organization
            query = "SELECT companyid FROM organizations LIMIT 1"
            result = self.db_connection.execute_query(query)
            
            if result:
                return result[0]['companyid']
            
            return None
            
        except Exception as e:
            print(f"⚠️ Error getting user organization: {e}")
            return None
    
    def save_email_attachments(self, attachments: List[Dict], ticket_number: str) -> List[Dict]:
        """
        Save email attachments to storage and process them
        
        Args:
            attachments: List of attachment data from email
            ticket_number: Ticket number for organizing files
            
        Returns:
            List of processed attachment records
        """
        processed_attachments = []
        
        for attachment in attachments:
            try:
                filename = attachment['filename']
                data = attachment['data']
                content_type = attachment['content_type']
                
                # Get file extension
                file_ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                
                # Check if file type is allowed
                if file_ext not in Config.ALLOWED_FILE_TYPES:
                    print(f"⚠️ Skipping unsupported file type: {filename}")
                    continue
                
                # Save to temp file first, then to storage
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                
                # Save to permanent storage
                file_path = self.storage_service.save_email_attachment(
                    tmp_path, 
                    ticket_number, 
                    filename
                )
                
                # Clean up temp file
                os.unlink(tmp_path)
                
                # Process file to extract content
                extracted = self.file_processor.process_file(file_path, file_ext)
                
                processed_attachments.append({
                    'ticket_number': ticket_number,
                    'file_name': filename,
                    'file_type': content_type,
                    'file_size': attachment['size'],
                    'file_path': file_path,
                    'processing_status': extracted['processing_status'],
                    'extracted_content': extracted,
                    'processing_error': extracted.get('error')
                })
                
                print(f"   ✓ Attachment saved: {filename}")
                
            except Exception as e:
                print(f"   ❌ Error processing attachment {attachment.get('filename')}: {e}")
        
        return processed_attachments
    
    def fetch_unread_emails(self) -> List[Dict[str, Any]]:
        """
        Fetch all unread emails from inbox
        
        Returns:
            List of parsed email dictionaries
        """
        if not self.mail:
            if not self.connect():
                return []
        
        emails = []
        
        try:
            # Select inbox
            self.mail.select("INBOX")
            
            # Search for unread emails
            status, messages = self.mail.search(None, "UNSEEN")
            
            if status != "OK":
                print("⚠️ No messages found or error searching")
                return []
            
            email_ids = messages[0].split()
            print(f"📧 Found {len(email_ids)} unread email(s)")
            
            for email_id in email_ids:
                try:
                    # Fetch email
                    status, msg_data = self.mail.fetch(email_id, "(RFC822)")
                    
                    if status != "OK":
                        continue
                    
                    # Parse email
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            email_data = self.parse_email(response_part[1], email_id.decode())
                            emails.append(email_data)
                            
                except Exception as e:
                    print(f"⚠️ Error fetching email {email_id}: {e}")
            
            return emails
            
        except Exception as e:
            print(f"❌ Error fetching emails: {e}")
            return []
    
    def mark_as_processed(self, email_id: str):
        """
        Mark email as read/processed
        
        Args:
            email_id: The email ID to mark
        """
        if not self.mail:
            return
        
        try:
            # Mark as read
            self.mail.store(email_id.encode(), '+FLAGS', '\\Seen')
            
            # Optionally move to processed folder
            processed_folder = Config.PROCESSED_EMAIL_FOLDER
            if processed_folder:
                try:
                    # Create folder if it doesn't exist
                    self.mail.create(processed_folder)
                except:
                    pass  # Folder might already exist
                
                # Copy to processed folder
                self.mail.copy(email_id.encode(), processed_folder)
                # Delete from inbox
                self.mail.store(email_id.encode(), '+FLAGS', '\\Deleted')
                self.mail.expunge()
                
        except Exception as e:
            print(f"⚠️ Error marking email as processed: {e}")
    
    def process_emails(self) -> Dict[str, Any]:
        """
        Main method to fetch and process all unread emails
        
        Returns:
            Dictionary with processed emails, validated users, and any errors
        """
        result = {
            'emails_fetched': 0,
            'valid_emails': [],
            'invalid_emails': [],
            'errors': []
        }
        
        try:
            # Connect if not connected
            if not self.mail:
                if not self.connect():
                    result['errors'].append("Failed to connect to IMAP server")
                    return result
            
            # Fetch unread emails
            emails = self.fetch_unread_emails()
            result['emails_fetched'] = len(emails)
            
            for email_data in emails:
                sender_email = email_data['sender_email']
                
                # Validate sender
                user_data = self.validate_sender(sender_email)
                
                if user_data:
                    # Get user's organization
                    companyid = self.get_user_organization(user_data['user_id'])
                    
                    if companyid:
                        email_data['user_data'] = user_data
                        email_data['companyid'] = companyid
                        result['valid_emails'].append(email_data)
                    else:
                        email_data['rejection_reason'] = 'No organization found for user'
                        result['invalid_emails'].append(email_data)
                else:
                    email_data['rejection_reason'] = 'Sender email not registered'
                    result['invalid_emails'].append(email_data)
            
            return result
            
        except Exception as e:
            result['errors'].append(str(e))
            return result
        finally:
            self.disconnect()


# Singleton instance
_email_listener_service = None

def get_email_listener_service(db_connection=None) -> EmailListenerService:
    """Get or create email listener service instance"""
    global _email_listener_service
    if _email_listener_service is None:
        _email_listener_service = EmailListenerService(db_connection)
    elif db_connection is not None:
        _email_listener_service.db_connection = db_connection
    return _email_listener_service
