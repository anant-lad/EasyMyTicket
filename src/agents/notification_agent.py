"""
Notification Agent
Handles notifying technicians and users about ticket updates
"""
from typing import Dict, Optional
from src.utils.email_sender import EmailSender
from src.utils.picklist_loader import get_picklist_loader

class NotificationAgent:
    """Agent for sending ticket notifications"""
    
    def __init__(self):
        self.email_sender = EmailSender()
        
    def notify_technician(self, ticket_data: Dict, tech_data: Dict):
        """
        Notify technician about a newly assigned ticket
        """
        tech_email = tech_data.get('tech_mail')
        if not tech_email:
            print("⚠️ Technician email missing. Cannot send notification.")
            return False
            
        picklist = get_picklist_loader()
        priority_label = picklist.get_label('priority', str(ticket_data.get('priority'))) or ticket_data.get('priority', 'N/A')
        
        subject = f"New Ticket Assigned: {ticket_data.get('ticketnumber')} - {ticket_data.get('title')}"
        
        body = f"""
Hello {tech_data.get('tech_name', 'Technician')},

The following ticket has been assigned to you:

Ticket Number: {ticket_data.get('ticketnumber')}
Title: {ticket_data.get('title')}
Description: {ticket_data.get('description')}
Priority: {priority_label}
Due Date: {ticket_data.get('duedatetime') or 'N/A'}

Note: This ticket has been assigned to you. Please solve it before the due date.

Best regards,
EasyMyTicket Support System
"""
        return self.email_sender.send_email(tech_email, subject, body.strip())

    def notify_user(self, ticket_data: Dict, user_data: Dict, tech_data: Optional[Dict] = None):
        """
        Notify user about their ticket creation and assigned technician
        """
        user_email = user_data.get('user_mail')
        if not user_email:
            print("⚠️ User email missing. Cannot send notification.")
            return False
            
        picklist = get_picklist_loader()
        priority_label = picklist.get_label('priority', str(ticket_data.get('priority'))) or ticket_data.get('priority', 'N/A')
        category_label = picklist.get_label('ticketcategory', str(ticket_data.get('ticketcategory'))) or ticket_data.get('ticketcategory', 'N/A')
        issue_label = picklist.get_label('issuetype', str(ticket_data.get('issuetype'))) or ticket_data.get('issuetype', 'N/A')
        
        subject = f"Ticket Created Successfully: {ticket_data.get('ticketnumber')}"
        
        tech_info = ""
        if tech_data:
            tech_info = f"\nAssigned Technician: {tech_data.get('tech_name', 'N/A')}\nTechnician Email: {tech_data.get('tech_mail', 'N/A')}"
        
        body = f"""
Hello {user_data.get('user_name', 'User')},

Your ticket has been created successfully.

--- Ticket Details ---
Ticket Number: {ticket_data.get('ticketnumber')}
Title: {ticket_data.get('title')}
Description: {ticket_data.get('description')}
Category: {category_label}
Issue Type: {issue_label}
Priority: {priority_label}
{tech_info}

We will update you once your ticket is resolved.

Best regards,
EasyMyTicket Support System
"""
        return self.email_sender.send_email(user_email, subject, body.strip())
