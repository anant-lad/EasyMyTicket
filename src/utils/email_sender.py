"""
Email Sender Utility
Handles sending emails via SMTP
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.config import Config

class EmailSender:
    """Handles SMTP email sending"""
    
    @staticmethod
    def send_email(to_email: str, subject: str, body: str, is_html: bool = False):
        """
        Send an email via SMTP
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Email body
            is_html: Whether the body is HTML (default: False)
        """
        sender_email = Config.SUPPORT_EMAIL
        app_password = Config.SUPPORT_EMAIL_APP_PASSWORD
        
        if not sender_email or not app_password:
            print("⚠️ Email configuration missing. Skipping email sending.")
            return False
            
        # Create message
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = to_email
        message["Subject"] = subject
        
        contentType = "html" if is_html else "plain"
        message.attach(MIMEText(body, contentType))
        
        try:
            # Create secure SSL context
            context = ssl.create_default_context()
            
            with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT, context=context) as server:
                server.login(sender_email, app_password)
                server.sendmail(sender_email, to_email, message.as_string())
                
            print(f"✅ Email sent successfully to {to_email}")
            return True
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
            return False
