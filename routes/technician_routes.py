"""
Technician Assistance Routes
"""
import io
import base64
import logging
from fastapi import APIRouter, File, Form, HTTPException, Depends, UploadFile
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from src.database.db_connection import DatabaseConnection
from src.agents.technician_assistant import TechnicianAssistantAgent

log = logging.getLogger(__name__)

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

def _extract_file_text(filename: str, data: bytes, mime_type: str) -> str:
    """Extract plain text from an uploaded file for LLM context."""
    try:
        if mime_type == "text/plain" or mime_type == "text/csv":
            return data.decode("utf-8", errors="replace")

        if mime_type == "application/pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(data))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                return f"[PDF: {filename} — pypdf not installed]"

        ext = (filename or "").rsplit(".", 1)[-1].lower()

        if ext in ("docx",) or "wordprocessingml" in mime_type:
            try:
                from docx import Document
                doc = Document(io.BytesIO(data))
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                return f"[DOCX: {filename} — python-docx not installed]"

        if ext in ("xlsx", "xls") or "spreadsheetml" in mime_type:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
                lines = []
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        lines.append("\t".join(str(c) if c is not None else "" for c in row))
                return "\n".join(lines)
            except ImportError:
                return f"[XLSX: {filename} — openpyxl not installed]"

        if mime_type.startswith("image/"):
            return f"[Image: {filename}]"

        return f"[Attachment: {filename}]"
    except Exception as e:
        log.warning("File extraction failed for %s: %s", filename, e)
        return f"[{filename} — extraction error]"


@router.post("/technician/assist", response_model=TechnicianAssistResponse)
async def assist_technician(
    text: str = Form(...),
    session_id: Optional[str] = Form(None),
    ticket_context: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    """
    Provide assistance to a technician. Accepts multipart/form-data with optional file attachments.
    """
    try:
        # Build augmented message with file content
        augmented = text
        for f in files[:3]:  # max 3 files
            data = await f.read()
            if len(data) > 10 * 1024 * 1024:
                continue  # skip oversized files silently
            extracted = _extract_file_text(f.filename or "", data, f.content_type or "")
            if extracted:
                augmented += f"\n\n[Attached: {f.filename}]\n{extracted}"

        if ticket_context:
            augmented = f"[Ticket context]\n{ticket_context}\n\n{augmented}"

        agent = get_assistant_agent()
        result = agent.assist_technician(augmented, session_id=session_id)

        if not result.get("success"):
            return TechnicianAssistResponse(success=False, message=result.get("message"))

        return TechnicianAssistResponse(
            success=True,
            session_id=result.get("session_id"),
            ticket_number=result.get("ticket_number"),
            analysis=result.get("analysis"),
            solution=result.get("solution"),
            sources=[Source(**s) for s in result.get("sources", [])],
            follow_up_questions=result.get("follow_up_questions", []),
            original_query=result.get("original_query"),
        )

    except Exception as e:
        log.error("Error in technician assistance: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
