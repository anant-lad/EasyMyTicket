from fastapi import APIRouter, HTTPException, Depends, Query, Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from src.utils.security import get_current_user
from src.services.notification_service import NotificationService
from src.database.db_connection import DatabaseConnection

router = APIRouter()

# Models
class NotificationResponse(BaseModel):
    id: int
    recipient_id: str
    title: str
    message: str
    type: str
    is_read: bool
    related_entity_id: Optional[str] = None
    related_entity_type: Optional[str] = None
    created_at: str

class NotificationsListResponse(BaseModel):
    items: List[NotificationResponse]
    unread_count: int

# Dependency
def get_notification_service():
    return NotificationService()

@router.get("/notifications", response_model=NotificationsListResponse)
async def get_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service)
):
    """
    Get notifications for the current user
    """
    try:
        user_id = current_user['user_id']
        notifications = service.get_user_notifications(user_id, limit, offset)
        unread_count = service.get_unread_count(user_id)
        
        # Convert datetime to string for JSON
        formatted_notifications = []
        for n in notifications:
            n_dict = dict(n)
            if 'created_at' in n_dict and n_dict['created_at']:
                n_dict['created_at'] = str(n_dict['created_at'])
            formatted_notifications.append(n_dict)
            
        return {
            "items": formatted_notifications,
            "unread_count": unread_count
        }
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/notifications/{notification_id}/read")
async def mark_as_read(
    notification_id: int = Path(..., gt=0),
    current_user: Dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service)
):
    """
    Mark a specific notification as read
    """
    try:
        user_id = current_user['user_id']
        success = service.mark_as_read(notification_id, user_id)
        if not success:
             raise HTTPException(status_code=404, detail="Notification not found or not owned by user")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error marking notification as read: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/notifications/mark-all-read")
async def mark_all_read(
    current_user: Dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service)
):
    """
    Mark all notifications for the current user as read
    """
    try:
        user_id = current_user['user_id']
        service.mark_all_as_read(user_id)
        return {"success": True}
    except Exception as e:
        print(f"Error marking all as read: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/notifications/test-trigger")
async def trigger_test_notification(
    current_user: Dict = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service)
):
    """
    Trigger a test notification for the current user (For Verification)
    """
    try:
        user_id = current_user['user_id']
        service.create_notification(
            recipient_id=user_id,
            title="Test Notification",
            message=f"This is a test notification trigger by {user_id}",
            type="success",
            related_entity_id="123",
            related_entity_type="test"
        )
        return {"success": True, "message": "Notification created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
