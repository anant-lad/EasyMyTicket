import os
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import asyncpg
import uuid
from enum import Enum
from contextlib import asynccontextmanager
import json
import pandas as pd

# NLP
from sentence_transformers import SentenceTransformer, util
import numpy as np
import openai

# ------------------------------
# OpenAI Setup
# ------------------------------
openai.api_key = os.getenv("sk-") # Replace with your OpenAI API key
# ------------------------------
# Database configuration
# ------------------------------
DB_HOST = "localhost"
DB_PORT = 5433
DB_USER = "Sanket"
DB_PASSWORD = "Sanket"
DB_NAME = "tickets_db"

# ------------------------------
# Enums & Models
# ------------------------------
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
    technical_keywords: List[str]
    user_actions: str
    resolution_indicators: str
    error_messages: Optional[str] = None
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
# Database class
# ------------------------------
class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_PASSWORD, database=DB_NAME
        )
        print("Connected to DB!")

    async def disconnect(self):
        await self.pool.close()
        print("Disconnected from DB.")

    async def insert_new_ticket(self, ticket: ClassifiedTicket) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.fetchval('''
                INSERT INTO new_tickets (
                    ticketnumber, title, description, issuetype,
                    subissuetype, ticketcategory, tickettype, status,
                    priority, createdate, duedatetime, estimatedhours,
                    companyid, queueid, extracted_metadata, similar_tickets
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                RETURNING id
            ''',
            ticket.ticketnumber,
            ticket.title,
            ticket.description,
            ticket.issuetype,
            ticket.subissuetype,
            ticket.ticketcategory,
            ticket.tickettype,
            ticket.status,
            ticket.priority,
            ticket.createdate,
            ticket.duedatetime,
            ticket.estimatedhours,
            ticket.companyid,
            ticket.queueid,
            json.dumps(ticket.extracted_metadata.model_dump()) if ticket.extracted_metadata else None,
            json.dumps(ticket.similar_tickets) if ticket.similar_tickets else None
            )
            return result

    async def fetch_ticket_by_number(self, ticketnumber: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM new_tickets WHERE ticketnumber=$1", ticketnumber
            )

    async def fetch_all_tickets(self, limit: int = 50):
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM new_tickets ORDER BY createdate DESC LIMIT $1", limit
            )

db = Database()

# ------------------------------
# Load Closed Tickets
# ------------------------------
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
closed_ticket_embeddings = []
closed_ticket_numbers = []

closed_tickets_file = r"C:\Users\sanke\OneDrive\Desktop\ATS practice\closed_tickets.xlsx"

def load_closed_tickets():
    global closed_ticket_embeddings, closed_ticket_numbers

    if not os.path.exists(closed_tickets_file):
        print(f"[WARNING] Closed tickets file not found at {closed_tickets_file}")
        return

    # Read Excel or CSV automatically
    if closed_tickets_file.endswith(".xlsx"):
        df = pd.read_excel(closed_tickets_file)
    else:
        df = pd.read_csv(closed_tickets_file)

    # Normalize column names to lowercase
    df.columns = [col.lower() for col in df.columns]

    closed_ticket_embeddings = []
    closed_ticket_numbers = []

    for _, row in df.iterrows():
        text = f"{row['title']} {row['description']}"
        emb = embedding_model.encode(text, convert_to_tensor=True)
        closed_ticket_embeddings.append(emb)
        closed_ticket_numbers.append(row['ticketnumber'])

    print(f"Loaded {len(closed_ticket_numbers)} closed tickets for similarity search.")

# ------------------------------
# Metadata Extraction
# ------------------------------
async def extract_metadata(ticket: TicketInput) -> ExtractedMetadata:
    # GPT-based extraction can be implemented here
    return ExtractedMetadata(
        main_issue=ticket.title,
        affected_system="Software/Portal",
        urgency_level=ticket.priority.value,
        technical_keywords=["error", "issue", "software", "login"],
        user_actions="Tried multiple options",
        resolution_indicators="Requires technical investigation"
    )

# ------------------------------
# Find Similar Tickets
# ------------------------------
async def find_similar_tickets(ticket: TicketInput, top_k: int = 5) -> List[str]:
    if not closed_ticket_embeddings:
        load_closed_tickets()
    query_emb = embedding_model.encode(f"{ticket.title} {ticket.description}", convert_to_tensor=True)
    scores = [util.cos_sim(query_emb, emb).item() for emb in closed_ticket_embeddings]
    top_indices = np.argsort(scores)[-top_k:][::-1]
    return [closed_ticket_numbers[i] for i in top_indices]

# ------------------------------
# Classify Ticket
# ------------------------------
async def classify_ticket(ticket: TicketInput, metadata: ExtractedMetadata, similar: List[str]):
    return ClassifiedTicket(
        ticketnumber=f"TKT-{uuid.uuid4().hex[:8].upper()}",
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
        similar_tickets=similar
    )

# ------------------------------
# FastAPI App
# ------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    load_closed_tickets()
    yield
    await db.disconnect()

app = FastAPI(title="Real-Time Intake Agent", lifespan=lifespan)

# Create Ticket
@app.post("/tickets", response_model=ClassifiedTicket)
async def create_ticket(ticket_input: TicketInput):
    metadata = await extract_metadata(ticket_input)
    similar = await find_similar_tickets(ticket_input)
    classified_ticket = await classify_ticket(ticket_input, metadata, similar)
    ticket_id = await db.insert_new_ticket(classified_ticket)
    classified_ticket.id = ticket_id
    return classified_ticket

# Fetch Ticket by number
@app.get("/tickets/{ticketnumber}", response_model=ClassifiedTicket)
async def get_ticket(ticketnumber: str):
    row = await db.fetch_ticket_by_number(ticketnumber)
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket_input = TicketInput(
        title=row["title"],
        description=row["description"],
        duedatetime=row["duedatetime"],
        priority=PriorityEnum(row["priority"]),
        companyid=row["companyid"]
    )
    metadata = await extract_metadata(ticket_input)
    similar = await find_similar_tickets(ticket_input)

    return ClassifiedTicket(
        id=row["id"],
        ticketnumber=row["ticketnumber"],
        title=row["title"],
        description=row["description"],
        issuetype=row["issuetype"],
        subissuetype=row["subissuetype"],
        ticketcategory=row["ticketcategory"],
        tickettype=row["tickettype"],
        status=row["status"],
        priority=row["priority"],
        createdate=row["createdate"],
        duedatetime=row["duedatetime"],
        estimatedhours=row["estimatedhours"],
        companyid=row["companyid"],
        queueid=row["queueid"],
        extracted_metadata=metadata,
        similar_tickets=similar
    )

# Fetch All Tickets
@app.get("/tickets", response_model=List[ClassifiedTicket])
async def get_all_tickets(limit: int = 50):
    rows = await db.fetch_all_tickets(limit)
    tickets = []
    for row in rows:
        ticket_input = TicketInput(
            title=row["title"],
            description=row["description"],
            duedatetime=row["duedatetime"],
            priority=PriorityEnum(row["priority"]),
            companyid=row["companyid"]
        )
        metadata = await extract_metadata(ticket_input)
        similar = await find_similar_tickets(ticket_input)

        tickets.append(ClassifiedTicket(
            id=row["id"],
            ticketnumber=row["ticketnumber"],
            title=row["title"],
            description=row["description"],
            issuetype=row["issuetype"],
            subissuetype=row["subissuetype"],
            ticketcategory=row["ticketcategory"],
            tickettype=row["tickettype"],
            status=row["status"],
            priority=row["priority"],
            createdate=row["createdate"],
            duedatetime=row["duedatetime"],
            estimatedhours=row["estimatedhours"],
            companyid=row["companyid"],
            queueid=row["queueid"],
            extracted_metadata=metadata,
            similar_tickets=similar
        ))
    return tickets

# Health Check
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
