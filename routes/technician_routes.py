"""
Technician Assistance Routes
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from src.database.db_connection import DatabaseConnection
from src.agents.technician_assistant import TechnicianAssistantAgent

router = APIRouter()

# Lazy loading
_db_conn = None
_assistant_agent = None

def get_db_connection():
    global _db_conn
    if _db_conn is None:
        _db_conn = DatabaseConnection()
    return _db_conn

def get_assistant_agent():
    global _assistant_agent
    if _assistant_agent is None:
        _assistant_agent = TechnicianAssistantAgent(get_db_connection())
    return _assistant_agent

# Pydantic models
class TechnicianAssistRequest(BaseModel):
    text: str = Field(..., description="Natural language input from technician")
    session_id: Optional[str] = Field(None, description="Optional session ID for conversational context")
    
    class Config:
        json_schema_extra = {
            "example": {
                "text": "Help me with ticket T20240108.123456. I'm seeing a database connection error.",
                "session_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }

class Source(BaseModel):
    ticket_number: str
    reason: str

class TechnicianAssistResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    ticket_number: Optional[str] = None
    analysis: Optional[str] = None
    solution: Optional[str] = None
    sources: List[Source] = []
    follow_up_questions: List[str] = []
    message: Optional[str] = None
    original_query: Optional[str] = None

@router.post("/technician/assist", response_model=TechnicianAssistResponse)
async def assist_technician(request: TechnicianAssistRequest):
    """
    Provide assistance to a technician based on their natural language request
    """
    try:
        agent = get_assistant_agent()
        result = agent.assist_technician(request.text, session_id=request.session_id)
        
        if not result.get("success"):
            return TechnicianAssistResponse(
                success=False,
                message=result.get("message")
            )
            
        return TechnicianAssistResponse(
            success=True,
            session_id=result.get("session_id"),
            ticket_number=result.get("ticket_number"),
            analysis=result.get("analysis"),
            solution=result.get("solution"),
            sources=[Source(**s) for s in result.get("sources", [])],
            follow_up_questions=result.get("follow_up_questions", []),
            original_query=result.get("original_query")
        )
        
    except Exception as e:
        print(f"Error in technician assistance: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
