"""
Chat routes — E4 IT Support Q&A Chatbot.
POST /api/chat/message        — send a message (creates session if needed)
GET  /api/chat/{session_id}/history — full conversation history
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.database.db_connection import DatabaseConnection
from src.graph.chat_graph import chat_reply, get_or_create_session

router = APIRouter()
log    = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    user_id:       str
    message:       str
    ticket_number: Optional[str] = None
    session_id:    Optional[str] = None   # pass to continue existing session


class ChatResponse(BaseModel):
    session_id: str
    reply:      str


@router.post("/api/chat/message", response_model=ChatResponse, tags=["chat"])
async def send_message(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    session_id = req.session_id or get_or_create_session(req.user_id, req.ticket_number)

    try:
        reply = await chat_reply(
            session_id=session_id,
            user_message=req.message,
            user_id=req.user_id,
            ticket_number=req.ticket_number,
        )
    except Exception as e:
        log.error("Chat reply failed session=%s: %s", session_id, e)
        raise HTTPException(status_code=500, detail="Failed to generate reply")

    return ChatResponse(session_id=session_id, reply=reply)


@router.get("/api/chat/{session_id}/history", tags=["chat"])
def get_history(session_id: str):
    db   = DatabaseConnection()
    rows = db.execute_query(
        "SELECT role, content, created_at FROM chat_messages "
        "WHERE session_id=%s ORDER BY created_at",
        (session_id,),
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": rows}


@router.get("/api/chat/sessions/{user_id}", tags=["chat"])
def list_sessions(user_id: str):
    db   = DatabaseConnection()
    rows = db.execute_query(
        """SELECT cs.session_id, cs.ticket_number, cs.created_at, cs.last_message,
                  t.title AS ticket_title,
                  (SELECT COUNT(*) FROM chat_messages WHERE session_id = cs.session_id) AS message_count
           FROM chat_sessions cs
           LEFT JOIN new_tickets t ON t.ticketnumber = cs.ticket_number
           WHERE cs.user_id=%s ORDER BY cs.last_message DESC NULLS LAST LIMIT 50""",
        (user_id,),
    )
    return {"sessions": rows or []}
