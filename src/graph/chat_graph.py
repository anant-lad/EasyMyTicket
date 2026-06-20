"""
EasyMyTicket — IT Support Q&A Chatbot (E4)
============================================
Uses LangGraph to manage a stateful multi-turn conversation.
The LLM has access to the ticket's full context, resolution history,
and can query related tickets for richer answers.

Entry point:
    from src.graph.chat_graph import chat_reply
    response = await chat_reply(session_id, user_message, user_id, ticket_number)
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from src.database.db_connection import DatabaseConnection
from src.llm.provider import get_callbacks, get_llm

log = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class ChatState(TypedDict):
    session_id:    str
    user_id:       str
    ticket_number: Optional[str]
    messages:      List[Any]
    context:       str
    response:      str


# ── Helpers ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are the EasyMyTicket virtual IT support assistant.
Your job is to answer questions about tickets, explain technical issues in plain English,
and provide actionable advice. You have access to the ticket context below.

Rules:
- Stay strictly on IT support topics. Politely decline off-topic questions.
- If you don't know something, say so rather than guessing.
- Reference specific ticket numbers, statuses, and steps when available.
- Keep answers concise (3-5 sentences unless a step-by-step guide is needed).
- Never suggest users share passwords, tokens, or sensitive credentials.

{context}
"""


def _build_context(db: DatabaseConnection, ticket_number: Optional[str],
                   user_id: str) -> str:
    """Fetch ticket + recent history to give the LLM rich context."""
    lines = [f"User: {user_id}"]

    if ticket_number:
        rows = db.execute_query(
            """SELECT ticketnumber, title, description, status, priority,
                      issuetype, resolution, assigned_tech_id, createdate
               FROM new_tickets WHERE ticketnumber = %s""",
            (ticket_number,),
        )
        if rows:
            t = rows[0]
            lines.append(
                f"\nTicket {t['ticketnumber']}: {t.get('title', '')}\n"
                f"Status: {t.get('status', '?')} | Priority: {t.get('priority', '?')} "
                f"| Category: {t.get('issuetype', '?')}\n"
                f"Description: {(t.get('description') or '')[:500]}\n"
                f"Resolution: {(t.get('resolution') or 'Not yet resolved')[:500]}"
            )
        # Include last agentic session if any
        sessions = db.execute_query(
            """SELECT session_id, status, step_count, resolution, escalation_reason
               FROM agent_sessions WHERE ticket_number=%s ORDER BY created_at DESC LIMIT 1""",
            (ticket_number,),
        )
        if sessions:
            s = sessions[0]
            lines.append(
                f"\nLast agentic session: {s['status']} ({s.get('step_count',0)} steps)\n"
                f"Session resolution: {(s.get('resolution') or '')[:300]}"
            )
    else:
        # No ticket — give recent user tickets for context
        recent = db.execute_query(
            "SELECT ticketnumber, title, status FROM new_tickets "
            "WHERE user_id=%s ORDER BY createdate DESC LIMIT 5",
            (user_id,),
        )
        if recent:
            lines.append("\nRecent tickets:")
            for r in recent:
                lines.append(f"  • {r['ticketnumber']}: {r.get('title','')} [{r.get('status','')}]")

    return "\n".join(lines)


def _load_history(db: DatabaseConnection, session_id: str) -> List[Any]:
    rows = db.execute_query(
        "SELECT role, content FROM chat_messages WHERE session_id=%s ORDER BY created_at",
        (session_id,),
    )
    mapping = {"user": HumanMessage, "assistant": AIMessage}
    return [mapping.get(r["role"], HumanMessage)(content=r["content"]) for r in (rows or [])]


def _save_messages(db: DatabaseConnection, session_id: str,
                   user_msg: str, assistant_msg: str):
    for role, content in [("user", user_msg), ("assistant", assistant_msg)]:
        db.execute_query(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, role, content), fetch=False,
        )
    db.execute_query(
        "UPDATE chat_sessions SET last_message=NOW() WHERE session_id=%s",
        (session_id,), fetch=False,
    )


# ── LangGraph nodes ───────────────────────────────────────────────────────────

def load_context_node(state: ChatState) -> ChatState:
    db = DatabaseConnection()
    context = _build_context(db, state.get("ticket_number"), state["user_id"])
    current_messages = state["messages"]          # [HumanMessage(user_message)] — must be preserved
    history = _load_history(db, state["session_id"])
    return {**state, "context": context, "messages": history + current_messages}


def llm_reply_node(state: ChatState) -> ChatState:
    system = _SYSTEM_PROMPT.format(context=state["context"])
    user_message = state["messages"][-1].content if state["messages"] else ""

    # E6: try guarded generation first
    guarded_reply = None
    try:
        from src.guardrails.guardrails import guarded_generate, check_output_safety
        import asyncio
        loop = asyncio.new_event_loop()
        guarded_reply = loop.run_until_complete(
            guarded_generate(user_message=user_message, context=system)
        )
        loop.close()
        if guarded_reply and not check_output_safety(guarded_reply):
            guarded_reply = "I'm sorry, I can't provide that information. Please contact your IT administrator."
    except Exception:
        guarded_reply = None

    if guarded_reply:
        return {**state, "response": guarded_reply}

    # Fallback: unguarded LLM call
    messages_to_send = [SystemMessage(content=system)] + state["messages"]
    llm = get_llm(get_callbacks())
    response = llm.invoke(messages_to_send)
    return {**state, "response": response.content}


def persist_node(state: ChatState) -> ChatState:
    db = DatabaseConnection()
    user_msg = state["messages"][-1].content if state["messages"] else ""
    _save_messages(db, state["session_id"], user_msg, state["response"])
    return state


# ── Graph assembly ────────────────────────────────────────────────────────────

def _build_graph() -> Any:
    g = StateGraph(ChatState)
    g.add_node("load_context", load_context_node)
    g.add_node("llm_reply",    llm_reply_node)
    g.add_node("persist",      persist_node)
    g.set_entry_point("load_context")
    g.add_edge("load_context", "llm_reply")
    g.add_edge("llm_reply",    "persist")
    g.add_edge("persist",      END)
    return g.compile()


_graph = _build_graph()


# ── Public API ────────────────────────────────────────────────────────────────

async def chat_reply(
    session_id:    str,
    user_message:  str,
    user_id:       str,
    ticket_number: Optional[str] = None,
) -> str:
    """Process one user message and return the assistant reply."""
    state: ChatState = {
        "session_id":    session_id,
        "user_id":       user_id,
        "ticket_number": ticket_number,
        "messages":      [HumanMessage(content=user_message)],
        "context":       "",
        "response":      "",
    }
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _graph.invoke(state)
    )
    return result["response"]


def get_or_create_session(user_id: str, ticket_number: Optional[str] = None) -> str:
    """Return existing open session or create a new one."""
    db = DatabaseConnection()
    rows = db.execute_query(
        """SELECT session_id FROM chat_sessions
           WHERE user_id=%s AND ticket_number IS NOT DISTINCT FROM %s
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, ticket_number),
    )
    if rows:
        return rows[0]["session_id"]
    session_id = str(uuid.uuid4())
    db.execute_query(
        "INSERT INTO chat_sessions (session_id, user_id, ticket_number) VALUES (%s,%s,%s)",
        (session_id, user_id, ticket_number), fetch=False,
    )
    return session_id
