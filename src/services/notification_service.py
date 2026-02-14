from typing import List, Optional, Dict, Any
from datetime import datetime
from src.database.db_connection import DatabaseConnection

class NotificationService:
    def __init__(self, db_conn: DatabaseConnection = None):
        self.db = db_conn or DatabaseConnection()

    def create_notification(
        self, 
        recipient_id: str, 
        title: str, 
        message: str, 
        type: str = 'info', 
        related_entity_id: Optional[str] = None, 
        related_entity_type: Optional[str] = None
    ) -> Optional[int]:
        """Create a new notification"""
        query = """
            INSERT INTO notifications 
            (recipient_id, title, message, type, is_read, related_entity_id, related_entity_type, created_at)
            VALUES (%s, %s, %s, %s, FALSE, %s, %s, NOW())
            RETURNING id
        """
        params = (recipient_id, title, message, type, related_entity_id, related_entity_type)
        try:
            result = self.db.execute_query(query, params)
            if result:
                return result[0]['id']
            return None
        except Exception as e:
            print(f"Error creating notification: {e}")
            return None

    def get_user_notifications(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get notifications for a user"""
        query = """
            SELECT * FROM notifications 
            WHERE recipient_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """
        return self.db.execute_query(query, (user_id, limit, offset)) or []

    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications"""
        query = "SELECT COUNT(*) as count FROM notifications WHERE recipient_id = %s AND is_read = FALSE"
        result = self.db.execute_query(query, (user_id,))
        return result[0]['count'] if result else 0

    def mark_as_read(self, notification_id: int, user_id: str) -> bool:
        """Mark a notification as read"""
        query = "UPDATE notifications SET is_read = TRUE WHERE id = %s AND recipient_id = %s RETURNING id"
        result = self.db.execute_query(query, (notification_id, user_id))
        return bool(result)

    def mark_all_as_read(self, user_id: str) -> bool:
        """Mark all notifications for a user as read"""
        query = "UPDATE notifications SET is_read = TRUE WHERE recipient_id = %s AND is_read = FALSE RETURNING id"
        result = self.db.execute_query(query, (user_id,))
        return True # Return true even if no rows updated
