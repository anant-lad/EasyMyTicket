"""
Feedback Collection Routes for RLHF
Allows technicians to provide feedback on ticket classifications, assignments, and resolutions
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from src.database.db_connection import DatabaseConnection
from src.services.feedback_service import get_feedback_service

router = APIRouter()

# Lazy loading for database connection
_db_conn = None

def get_db_connection():
    """Get or create database connection (lazy loading)"""
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn


# Pydantic models for request/response
class ClassificationFeedbackRequest(BaseModel):
    """Request model for classification feedback"""
    ticket_number: str = Field(..., description="Ticket number")
    is_correct: bool = Field(..., description="Whether the classification was correct")
    correction_data: Optional[Dict[str, Any]] = Field(None, description="Correct classification data")
    technician_id: Optional[str] = Field(None, description="Technician ID providing feedback")
    comments: Optional[str] = Field(None, description="Additional comments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ticket_number": "T20260114.123456",
                "is_correct": False,
                "correction_data": {
                    "issuetype": "Hardware",
                    "priority": "High"
                },
                "technician_id": "tech001",
                "comments": "Should be hardware issue, not software"
            }
        }


class AssignmentFeedbackRequest(BaseModel):
    """Request model for assignment feedback"""
    ticket_number: str = Field(..., description="Ticket number")
    is_correct: bool = Field(..., description="Whether the assignment was correct")
    correct_tech_id: Optional[str] = Field(None, description="Who should have been assigned")
    technician_id: Optional[str] = Field(None, description="Technician ID providing feedback")
    comments: Optional[str] = Field(None, description="Additional comments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ticket_number": "T20260114.123456",
                "is_correct": True,
                "technician_id": "tech001"
            }
        }


class ResolutionFeedbackRequest(BaseModel):
    """Request model for resolution feedback"""
    ticket_number: str = Field(..., description="Ticket number")
    rating: int = Field(..., ge=1, le=5, description="Quality rating (1-5)")
    technician_id: Optional[str] = Field(None, description="Technician ID providing feedback")
    comments: Optional[str] = Field(None, description="Additional comments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ticket_number": "T20260114.123456",
                "rating": 4,
                "technician_id": "tech001",
                "comments": "Good resolution but could be more detailed"
            }
        }


class FeedbackResponse(BaseModel):
    """Response model for feedback submission"""
    success: bool
    feedback_id: Optional[int] = None
    message: str


class FeedbackStatsResponse(BaseModel):
    """Response model for feedback statistics"""
    success: bool
    stats: Dict[str, Any]


@router.post("/feedback/classification", response_model=FeedbackResponse)
async def submit_classification_feedback(feedback: ClassificationFeedbackRequest):
    """
    Submit feedback on ticket classification
    
    Args:
        feedback: Classification feedback data
        
    Returns:
        FeedbackResponse with success status and feedback ID
    """
    try:
        db_conn = get_db_connection()
        feedback_service = get_feedback_service(db_conn)
        
        feedback_id = feedback_service.record_classification_feedback(
            ticket_number=feedback.ticket_number,
            is_correct=feedback.is_correct,
            correction_data=feedback.correction_data,
            technician_id=feedback.technician_id,
            comments=feedback.comments
        )
        
        if feedback_id:
            return FeedbackResponse(
                success=True,
                feedback_id=feedback_id,
                message="Classification feedback recorded successfully"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to record feedback"
            )
    
    except Exception as e:
        print(f"Error recording classification feedback: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error recording feedback: {str(e)}"
        )


@router.post("/feedback/assignment", response_model=FeedbackResponse)
async def submit_assignment_feedback(feedback: AssignmentFeedbackRequest):
    """
    Submit feedback on ticket assignment
    
    Args:
        feedback: Assignment feedback data
        
    Returns:
        FeedbackResponse with success status and feedback ID
    """
    try:
        db_conn = get_db_connection()
        feedback_service = get_feedback_service(db_conn)
        
        feedback_id = feedback_service.record_assignment_feedback(
            ticket_number=feedback.ticket_number,
            is_correct=feedback.is_correct,
            correct_tech_id=feedback.correct_tech_id,
            technician_id=feedback.technician_id,
            comments=feedback.comments
        )
        
        if feedback_id:
            return FeedbackResponse(
                success=True,
                feedback_id=feedback_id,
                message="Assignment feedback recorded successfully"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to record feedback"
            )
    
    except Exception as e:
        print(f"Error recording assignment feedback: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error recording feedback: {str(e)}"
        )


@router.post("/feedback/resolution", response_model=FeedbackResponse)
async def submit_resolution_feedback(feedback: ResolutionFeedbackRequest):
    """
    Submit feedback on resolution quality
    
    Args:
        feedback: Resolution feedback data
        
    Returns:
        FeedbackResponse with success status and feedback ID
    """
    try:
        db_conn = get_db_connection()
        feedback_service = get_feedback_service(db_conn)
        
        feedback_id = feedback_service.record_resolution_feedback(
            ticket_number=feedback.ticket_number,
            rating=feedback.rating,
            technician_id=feedback.technician_id,
            comments=feedback.comments
        )
        
        if feedback_id:
            return FeedbackResponse(
                success=True,
                feedback_id=feedback_id,
                message="Resolution feedback recorded successfully"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to record feedback"
            )
    
    except Exception as e:
        print(f"Error recording resolution feedback: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error recording feedback: {str(e)}"
        )


@router.get("/feedback/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats():
    """
    Get feedback statistics
    
    Returns:
        FeedbackStatsResponse with statistics on collected feedback
    """
    try:
        db_conn = get_db_connection()
        feedback_service = get_feedback_service(db_conn)
        
        stats = feedback_service.get_feedback_stats()
        
        return FeedbackStatsResponse(
            success=True,
            stats=stats
        )
    
    except Exception as e:
        print(f"Error getting feedback stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error getting feedback stats: {str(e)}"
        )


@router.get("/training/export")
async def export_training_data(limit: int = 1000):
    """
    Export training data from feedback (admin only)
    
    Args:
        limit: Maximum number of records to export
        
    Returns:
        List of training data records
    """
    try:
        db_conn = get_db_connection()
        feedback_service = get_feedback_service(db_conn)
        
        training_data = feedback_service.export_training_data(limit=limit)
        
        return {
            "success": True,
            "count": len(training_data),
            "data": training_data
        }
    
    except Exception as e:
        print(f"Error exporting training data: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error exporting training data: {str(e)}"
        )
