import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
import asyncpg
import uuid

# ------------------------------
# Database configuration
# ------------------------------
DB_HOST = "localhost"
DB_PORT = 5433
DB_USER = "Sanket"
DB_PASSWORD = "Sanket"
DB_NAME = "tickets_db"

# ------------------------------
# Enums & Pydantic Models
# ------------------------------
from enum import Enum

class PriorityEnum(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

class TicketInput(BaseModel):
    title: str = Field(..., min_length=5, max_length=500)
    description: str = Field(..., min_length=10)
    duedatetime: datetime
    priority: PriorityEnum
    companyid: str

class ExtractedMetadata(BaseModel):
    main_issue: str
    affected_system: str
    urgency_level: str
    error_messages: Optional[str] = None
    technical_keywords: List[str]
    user_actions: str
    resolution_indicators: str
    status: str = "Open"

class ClassifiedTicket(BaseModel):
    id: Optional[int] = None
    ticketnumber: str
    title: str
    description: str
    issuetype: str
    subissuetype: str
    ticketcategory: str
    tickettype: str
    status: str = "Open"
    priority: str
    createdate: datetime
    duedatetime: datetime
    estimatedhours: float
    companyid: str
    queueid: Optional[str] = None
    resolution: Optional[str] = None
    extracted_metadata: Optional[ExtractedMetadata] = None
    similar_tickets: Optional[List[str]] = None

# ------------------------------
# Async DB Connection
# ------------------------------
class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            host=DB_HOST, port=DB_PORT, user=DB_USER, 
            password=DB_PASSWORD, database=DB_NAME
        )

    async def disconnect(self):
        await self.pool.close()

    async def insert_new_ticket(self, ticket: ClassifiedTicket) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.fetchval('''
                INSERT INTO new_tickets (
                    ticketnumber, title, description, issuetype,
                    subissuetype, ticketcategory, tickettype, status,
                    priority, createdate, duedatetime, estimatedhours,
                    companyid, queueid
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                RETURNING id
            ''',
            ticket.ticketnumber, ticket.title, ticket.description,
            ticket.issuetype, ticket.subissuetype, ticket.ticketcategory,
            ticket.tickettype, ticket.status, ticket.priority,
            ticket.createdate, ticket.duedatetime, ticket.estimatedhours,
            ticket.companyid, ticket.queueid
            )
            return result

db = Database()

# ------------------------------
# Simple Metadata Extractor (Mock LLM)
# ------------------------------
async def extract_metadata(ticket: TicketInput) -> ExtractedMetadata:
    # Mocked extraction logic for testing
    return ExtractedMetadata(
        main_issue="Sample issue",
        affected_system="Sample system",
        urgency_level=ticket.priority.value,
        error_messages=None,
        technical_keywords=["error", "failure"],
        user_actions="User tried to login",
        resolution_indicators="Restart system"
    )

# ------------------------------
# Similar Ticket Search (Mock)
# ------------------------------
async def find_similar_tickets(ticket: TicketInput, metadata: ExtractedMetadata) -> List[str]:
    # Placeholder: Return empty or mock list
    return ["TKT-12345678", "TKT-87654321"]

# ------------------------------
# Ticket Classification (Mock)
# ------------------------------
async def classify_ticket(ticket: TicketInput, metadata: ExtractedMetadata, similar_tickets: List[str]) -> ClassifiedTicket:
    ticket_number = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    return ClassifiedTicket(
        ticketnumber=ticket_number,
        title=ticket.title,
        description=ticket.description,
        issuetype="Software",
        subissuetype="Bug",
        ticketcategory="Incident",
        tickettype="Technical",
        status="Open",
        priority=ticket.priority.value,
        createdate=datetime.now(),
        duedatetime=ticket.duedatetime,
        estimatedhours=2.0,
        companyid=ticket.companyid,
        queueid="L1-Support",
        extracted_metadata=metadata,
        similar_tickets=similar_tickets
    )

# ------------------------------
# FastAPI App
# ------------------------------
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()

app = FastAPI(title="Intake Agent", lifespan=lifespan)

@app.post("/tickets", response_model=ClassifiedTicket)
async def create_ticket(ticket_input: TicketInput):
    try:
        metadata = await extract_metadata(ticket_input)
        similar_tickets = await find_similar_tickets(ticket_input, metadata)
        classified_ticket = await classify_ticket(ticket_input, metadata, similar_tickets)
        ticket_id = await db.insert_new_ticket(classified_ticket)
        classified_ticket.id = ticket_id
        return classified_ticket
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}