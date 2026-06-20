"""
EasyMyTicket — LangGraph ticket-processing pipeline.

Flow:
  create_ticket
       │
    classify
       │
  auto_route_decision
       ├── can_auto_resolve=True  → agent_task ──┐
       └── can_auto_resolve=False → assign_tech ──┤
                                                  │
                                          generate_resolution
                                                  │
                                               notify
                                                  │
                                                END

Usage:
    from src.graph.ticket_graph import process_ticket

    result = process_ticket(
        title="DNS not resolving",
        description="Cannot reach any external sites, nslookup fails",
        user_id="user42",
        source="portal",
        device_id="device-abc123",
    )
"""
import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from src.graph.nodes import (
    agent_task_node,
    assign_technician_node,
    auto_route_decision_node,
    classify_node,
    create_ticket_node,
    generate_resolution_node,
    notify_node,
)
from src.graph.state import TicketState

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Conditional edge: route after auto_route_decision
# ─────────────────────────────────────────────────────────────────────────────

def _route_after_decision(state: TicketState) -> str:
    device_id = state.get("device_id", "")
    # LLM must say it can resolve AND the device must be connected
    if state.get("can_auto_resolve") and device_id:
        from routes.agent_routes import is_agent_connected
        if is_agent_connected(device_id):
            return "agent_task"
    return "assign_tech"


# ─────────────────────────────────────────────────────────────────────────────
#  Build graph (module-level singleton, compiled once)
# ─────────────────────────────────────────────────────────────────────────────

def _build_graph() -> Any:
    g = StateGraph(TicketState)

    g.add_node("create_ticket",    create_ticket_node)
    g.add_node("classify",         classify_node)
    g.add_node("auto_route",       auto_route_decision_node)
    g.add_node("agent_task",       agent_task_node)
    g.add_node("assign_tech",      assign_technician_node)
    g.add_node("gen_resolution",   generate_resolution_node)
    g.add_node("notify",           notify_node)

    g.set_entry_point("create_ticket")

    g.add_edge("create_ticket", "classify")
    g.add_edge("classify",      "auto_route")

    g.add_conditional_edges(
        "auto_route",
        _route_after_decision,
        {"agent_task": "agent_task", "assign_tech": "assign_tech"},
    )

    g.add_edge("agent_task",  "gen_resolution")
    g.add_edge("assign_tech", "gen_resolution")
    g.add_edge("gen_resolution", "notify")
    g.add_edge("notify", END)

    return g.compile()


_graph = _build_graph()


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def process_ticket(
    title: str,
    description: str,
    user_id: str,
    source: str = "portal",
    device_id: str | None = None,
    due_date_time: str | None = None,
    existing_ticket_number: str | None = None,
) -> Dict[str, Any]:
    """
    Run the full ticket-processing pipeline and return the final state.
    If existing_ticket_number is provided the pipeline skips DB insertion (ticket already exists).
    Raises nothing — errors are captured in state["errors"] and logged.
    """
    initial_state: TicketState = {
        "title": title,
        "description": description,
        "user_id": user_id,
        "source": source,
        "device_id": device_id,
        "due_date_time": due_date_time,
        "errors": [],
    }
    if existing_ticket_number:
        initial_state["ticket_number"] = existing_ticket_number

    log.info("Starting ticket pipeline for user=%s source=%s ticket=%s",
             user_id, source, existing_ticket_number or "new")
    try:
        final_state = _graph.invoke(initial_state)
        log.info(
            "Pipeline complete — ticket=%s auto_resolve=%s tech=%s",
            final_state.get("ticket_number"),
            final_state.get("can_auto_resolve"),
            final_state.get("assigned_tech_id"),
        )
        return final_state
    except Exception as e:
        log.error("Ticket pipeline fatal error: %s", e)
        return {**initial_state, "errors": [str(e)], "ticket_number": existing_ticket_number or "FAILED"}
