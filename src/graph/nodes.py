"""
LangGraph node implementations for the EasyMyTicket ticket pipeline.

Node contract:
  - Accepts TicketState dict
  - Returns a partial TicketState dict (only the fields it sets)
  - Appends to state["errors"] on non-fatal failures rather than raising

Graph order:
  create_ticket → classify → auto_route_decision → (agent_task | assign_tech)
                                                              ↓
                                                       generate_resolution
                                                              ↓
                                                          notify
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from src.graph.auto_resolve import check_auto_resolve
from src.graph.state import TicketState
from src.llm.provider import get_callbacks, get_llm, get_small_llm

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  Helper: safe JSON parse from LLM output
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    import re
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 1 — create_ticket
# ─────────────────────────────────────────────────────────────────────────────

def create_ticket_node(state: TicketState) -> Dict:
    """Save the raw ticket to new_tickets and return the ticket_number."""
    from src.database.db_connection import DatabaseConnection

    db = DatabaseConnection()
    ticket_number = f"TKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    query = """
        INSERT INTO new_tickets
            (ticketnumber, title, description, user_id, status, createdate, source)
        VALUES (%s, %s, %s, %s, 'Open', NOW(), %s)
        ON CONFLICT (ticketnumber) DO NOTHING
    """
    try:
        db.execute_query(
            query,
            (
                ticket_number,
                state["title"],
                state["description"],
                state["user_id"],
                state.get("source", "portal"),
            ),
        )
        log.info("Ticket %s created", ticket_number)
    except Exception as e:
        log.error("create_ticket_node failed: %s", e)
        return {"ticket_number": ticket_number, "errors": [str(e)]}

    return {"ticket_number": ticket_number, "errors": []}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 2 — classify
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an IT support metadata extractor. "
        "Reply ONLY with valid JSON matching the schema — no prose, no markdown."
    )),
    HumanMessage(content=(
        "Ticket title: {title}\n"
        "Ticket description: {description}\n\n"
        "Extract:\n"
        "{{\n"
        '  "urgency_level": "Critical|High|Medium|Low",\n'
        '  "affected_systems": ["list of affected systems"],\n'
        '  "error_messages": ["exact error text if any"],\n'
        '  "user_impact": "brief impact description",\n'
        '  "keywords": ["up to 8 key technical terms"]\n'
        "}}"
    )),
])

_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an IT support ticket classifier. "
        "Classify the ticket using ONLY the provided picklist values. "
        "Reply ONLY with valid JSON — no prose, no markdown."
    )),
    HumanMessage(content=(
        "Ticket:\nTitle: {title}\nDescription: {description}\n"
        "Extracted metadata: {metadata}\n\n"
        "Picklist values:\n{picklist}\n\n"
        "Return:\n"
        "{{\n"
        '  "issuetype": "<value from picklist>",\n'
        '  "subissuetype": "<value or null>",\n'
        '  "ticketcategory": "<value from picklist>",\n'
        '  "tickettype": "<value from picklist>",\n'
        '  "priority": "<value from picklist>",\n'
        '  "status": "Open",\n'
        '  "category_label": "<human-readable category e.g. network|hardware|software|security|account_access|email_collaboration|cloud_infrastructure|backup_recovery|billing|general_inquiry>",\n'
        '  "confidence": 0.0\n'
        "}}"
    )),
])


def classify_node(state: TicketState) -> Dict:
    """
    Two-step classification:
      1. Small model extracts raw metadata (fast, cheap).
      2. Large model classifies against picklist (accurate).
    Also runs semantic search to find similar historical tickets.
    """
    from src.database.db_connection import DatabaseConnection
    from src.utils.picklist_loader import get_picklist_loader

    title = state["title"]
    description = state["description"]
    callbacks = get_callbacks()
    errors = list(state.get("errors", []))

    # ── Step 1: metadata extraction ──────────────────────────────────────────
    extracted_metadata: Dict[str, Any] = {}
    try:
        small = get_small_llm(callbacks)
        chain = _EXTRACT_PROMPT | small
        resp = chain.invoke({"title": title, "description": description})
        extracted_metadata = _parse_json(resp.content) or {}
    except Exception as e:
        log.warning("Metadata extraction failed: %s", e)
        errors.append(f"metadata_extraction: {e}")

    # ── Step 2: classification ───────────────────────────────────────────────
    classification: Dict[str, Any] = {}
    try:
        picklist_loader = get_picklist_loader()
        picklist_text = "\n".join(
            picklist_loader.format_for_prompt(f)
            for f in ["issuetype", "subissuetype", "ticketcategory", "tickettype", "priority"]
        )
        large = get_llm(callbacks)
        chain = _CLASSIFY_PROMPT | large
        resp = chain.invoke({
            "title": title,
            "description": description,
            "metadata": json.dumps(extracted_metadata),
            "picklist": picklist_text,
        })
        classification = _parse_json(resp.content) or {}
    except Exception as e:
        log.warning("Classification failed: %s", e)
        errors.append(f"classification: {e}")

    # Derive normalised category + priority
    category = classification.get("category_label", "general_inquiry")
    priority_map = {"Critical": "critical", "High": "high", "Medium": "medium", "Low": "low"}
    urgency = extracted_metadata.get("urgency_level", "Medium")
    priority = priority_map.get(urgency, "medium")

    # ── Step 3: semantic search ───────────────────────────────────────────────
    similar_tickets: list = []
    try:
        db = DatabaseConnection()
        similar_tickets = db.find_similar_tickets(title, description) or []
    except Exception as e:
        log.warning("Semantic search failed: %s", e)
        errors.append(f"semantic_search: {e}")

    # Persist classification to DB
    try:
        db = DatabaseConnection()
        db.execute_query(
            """
            UPDATE new_tickets
            SET issuetype=%s, ticketcategory=%s, tickettype=%s, priority=%s
            WHERE ticketnumber=%s
            """,
            (
                classification.get("issuetype"),
                classification.get("ticketcategory"),
                classification.get("tickettype"),
                classification.get("priority"),
                state["ticket_number"],
            ),
        )
    except Exception as e:
        log.warning("Could not persist classification: %s", e)

    return {
        "extracted_metadata": extracted_metadata,
        "classification": classification,
        "category": category,
        "priority": priority,
        "similar_tickets": similar_tickets,
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Node 3 — auto_route_decision  (pure function — no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def auto_route_decision_node(state: TicketState) -> Dict:
    """
    Decide whether this ticket can be auto-resolved by the desktop agent.
    Sets can_auto_resolve, auto_command_type, auto_command_payload.
    """
    can_resolve, cmd_type, cmd_payload, desc = check_auto_resolve(
        category=state.get("category", "general_inquiry"),
        title=state.get("title", ""),
        description=state.get("description", ""),
    )

    if can_resolve:
        log.info("Auto-resolve eligible: %s → %s (%s)", state["ticket_number"], cmd_type, desc)

    return {
        "can_auto_resolve": can_resolve,
        "auto_command_type": cmd_type,
        "auto_command_payload": cmd_payload or {},
        "agent_connected": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Node 4a — agent_task  (auto-resolve path)
# ─────────────────────────────────────────────────────────────────────────────

def agent_task_node(state: TicketState) -> Dict:
    """
    Launch an agentic remediation session for this ticket on the user's device.

    If the device is connected: starts the multi-turn LLM remediation loop
    asynchronously (does not block the graph — the session runs in background).

    If the device is offline: marks the ticket 'Pending Agent' so the
    session starts automatically when the device reconnects.
    """
    import asyncio as _asyncio
    from routes.agent_routes import is_agent_connected
    from src.database.db_connection import DatabaseConnection

    device_id     = state.get("device_id") or ""
    ticket_number = state["ticket_number"]
    errors        = list(state.get("errors", []))
    agent_connected = bool(device_id and is_agent_connected(device_id))

    if agent_connected:
        # Fire-and-forget: agentic remediation loop runs in background
        device_os = state.get("extracted_metadata", {}).get("device_os", "Unknown")
        try:
            from src.graph.remediation_graph import run_remediation_session
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                _asyncio.ensure_future(run_remediation_session(
                    ticket_number=ticket_number,
                    device_id=device_id,
                    title=state["title"],
                    description=state["description"],
                    category=state.get("category", "general_inquiry"),
                    user_id=state.get("user_id", ""),
                    device_os=device_os,
                ))
            log.info("Agentic session launched: ticket=%s device=%s", ticket_number, device_id)
        except Exception as e:
            log.warning("Could not launch remediation session: %s", e)
            errors.append(f"session_launch: {e}")
            agent_connected = False
    else:
        log.info("Device %r offline — ticket %s queued as Pending Agent", device_id, ticket_number)
        try:
            db = DatabaseConnection()
            db.execute_query(
                "UPDATE new_tickets SET status='Pending Agent' WHERE ticketnumber=%s",
                (ticket_number,), fetch=False,
            )
        except Exception as e:
            errors.append(f"pending_status: {e}")

    # agent_task_id is now the session_id — set after session creates it
    # For now return None; the session will update the DB directly
    return {
        "agent_task_id": None,
        "agent_connected": agent_connected,
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Node 4b — assign_technician  (human path)
# ─────────────────────────────────────────────────────────────────────────────

def assign_technician_node(state: TicketState) -> Dict:
    """Skill-match and assign the ticket to the best available technician."""
    from src.agents.smart_ticket_assignment import SmartAssignmentAgent
    from src.database.db_connection import DatabaseConnection

    errors = list(state.get("errors", []))
    try:
        db = DatabaseConnection()
        agent = SmartAssignmentAgent(db)
        tech_id = agent.assign_ticket(
            ticket_data={
                "title": state["title"],
                "description": state["description"],
                "ticketnumber": state["ticket_number"],
            },
            classification=state.get("classification", {}),
        )
        if tech_id:
            db.execute_query(
                "UPDATE new_tickets SET assigned_tech_id=%s WHERE ticketnumber=%s",
                (tech_id, state["ticket_number"]),
            )
        return {"assigned_tech_id": tech_id, "errors": errors}
    except Exception as e:
        log.warning("Technician assignment failed: %s", e)
        return {"assigned_tech_id": None, "errors": errors + [f"assignment: {e}"]}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 5 — generate_resolution
# ─────────────────────────────────────────────────────────────────────────────

_RESOLUTION_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an expert IT support engineer. "
        "Write a clear, numbered, step-by-step resolution guide for the given ticket. "
        "Use simple language the technician can follow. "
        "If similar resolved tickets are provided, incorporate their solutions. "
        "Do not repeat the problem — focus only on the fix."
    )),
    HumanMessage(content=(
        "Ticket: {title}\n"
        "Description: {description}\n"
        "Category: {category}\n"
        "Priority: {priority}\n\n"
        "Similar resolved tickets:\n{similar}\n\n"
        "Provide the resolution steps:"
    )),
])


def generate_resolution_node(state: TicketState) -> Dict:
    """Generate a resolution using the large LLM, informed by similar tickets."""
    errors = list(state.get("errors", []))

    similar_text = ""
    for i, t in enumerate(state.get("similar_tickets", [])[:3], 1):
        similar_text += f"\n{i}. Problem: {t.get('title','')}\n   Resolution: {(t.get('resolution') or '(none)')[:300]}\n"
    if not similar_text:
        similar_text = "No similar tickets found."

    try:
        callbacks = get_callbacks()
        llm = get_llm(callbacks)
        chain = _RESOLUTION_PROMPT | llm
        resp = chain.invoke({
            "title": state["title"],
            "description": state["description"],
            "category": state.get("category", "general_inquiry"),
            "priority": state.get("priority", "medium"),
            "similar": similar_text,
        })
        resolution = resp.content.strip()
    except Exception as e:
        log.warning("Resolution generation failed: %s", e)
        resolution = (
            "1. Review the ticket details carefully.\n"
            "2. Reproduce the issue in a controlled environment if possible.\n"
            "3. Check system logs for errors related to the reported issue.\n"
            "4. Apply the appropriate fix based on findings.\n"
            "5. Verify the fix resolves the issue and notify the user."
        )
        errors.append(f"resolution_gen: {e}")

    # Persist resolution
    try:
        from src.database.db_connection import DatabaseConnection
        db = DatabaseConnection()
        db.execute_query(
            "UPDATE new_tickets SET resolution=%s WHERE ticketnumber=%s",
            (resolution, state["ticket_number"]),
        )
    except Exception as e:
        log.warning("Could not persist resolution: %s", e)

    return {"resolution": resolution, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 6 — notify
# ─────────────────────────────────────────────────────────────────────────────

def notify_node(state: TicketState) -> Dict:
    """Send email notifications to technician (if assigned) and ticket creator."""
    from src.agents.notification_agent import NotificationAgent

    errors = list(state.get("errors", []))
    sent: list = []

    try:
        agent = NotificationAgent()
        result = agent.send_ticket_notification(
            ticket_number=state["ticket_number"],
            title=state["title"],
            priority=state.get("priority", "medium"),
            category=state.get("category", "general_inquiry"),
            resolution=state.get("resolution", ""),
            assigned_tech_id=state.get("assigned_tech_id"),
            user_id=state.get("user_id"),
            auto_resolved=state.get("can_auto_resolve", False),
            agent_dispatched=state.get("agent_connected", False),
        )
        if result:
            sent = result if isinstance(result, list) else [str(result)]
    except Exception as e:
        log.warning("Notification failed: %s", e)
        errors.append(f"notify: {e}")

    return {"notifications_sent": sent, "errors": errors}
