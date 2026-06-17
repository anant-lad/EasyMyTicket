"""
LangGraph state schema for the EasyMyTicket ticket-processing pipeline.

The graph is a pure function: it takes a TicketState dict, runs every node in
sequence (with conditional branching), and returns the final TicketState.
Each node only adds/overwrites fields it owns — it never clears unrelated ones.
"""
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class TicketState(TypedDict, total=False):
    # ── Inputs (provided by the caller) ───────────────────────────────────────
    title: str
    description: str
    user_id: str
    source: str                      # "portal" | "email" | "agent" | "api"
    device_id: Optional[str]         # set when ticket originates from a desktop agent
    due_date_time: Optional[str]

    # ── After create_ticket_node ──────────────────────────────────────────────
    ticket_number: str

    # ── After classify_node ───────────────────────────────────────────────────
    extracted_metadata: Dict[str, Any]   # raw LLM extraction output
    classification: Dict[str, Any]       # final picklist-normalised labels
    category: str                        # from ISSUETYPE_CATEGORY mapping
    priority: str                        # low / medium / high / critical
    similar_tickets: List[Dict]          # top-K from semantic search

    # ── After auto_route_decision ─────────────────────────────────────────────
    can_auto_resolve: bool
    auto_command_type: Optional[str]     # e.g. "flush_dns", "clear_temp"
    auto_command_payload: Optional[Dict]

    # ── After agent_task_node (auto-resolve path) ─────────────────────────────
    agent_task_id: Optional[str]
    agent_connected: bool

    # ── After assign_technician_node (human path) ─────────────────────────────
    assigned_tech_id: Optional[str]

    # ── After resolution_node ─────────────────────────────────────────────────
    resolution: str

    # ── After notify_node ────────────────────────────────────────────────────
    notifications_sent: List[str]        # list of recipient addresses

    # ── Error accumulator (any node can append) ───────────────────────────────
    errors: List[str]
