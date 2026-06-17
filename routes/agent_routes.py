"""
Desktop agent WebSocket endpoint + agentic session management.

WebSocket message types (server → agent):
  task        — legacy one-shot command (backward compat)
  tool_call   — agentic session step; agent must reply with tool_result

WebSocket message types (agent → server):
  register    — device comes online
  task_result — result of a legacy task
  tool_result — result of an agentic tool_call
  pong        — keepalive response
  queue_stats — queued task stats
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.database.db_connection import DatabaseConnection

router = APIRouter()
log    = logging.getLogger(__name__)

# ── In-memory registries ──────────────────────────────────────────────────────

# {device_id: WebSocket}
_connected_agents: Dict[str, WebSocket] = {}

# {call_id: asyncio.Future}  — pending agentic tool calls awaiting device reply
_pending_tool_calls: Dict[str, asyncio.Future] = {}


# ── Pydantic models ───────────────────────────────────────────────────────────

class AgentTaskRequest(BaseModel):
    device_id:       str
    command_type:    str
    command_payload: dict = {}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/agent/{device_id}")
async def agent_websocket(device_id: str, ws: WebSocket):
    await ws.accept()
    _connected_agents[device_id] = ws
    log.info("Agent connected: %s (total=%d)", device_id, len(_connected_agents))

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "register":
                log.info("Agent registered: device_id=%s os=%s hostname=%s",
                         device_id,
                         msg.get("device", {}).get("os", "?"),
                         msg.get("device", {}).get("hostname", "?"))
                _update_device_last_seen(device_id, msg.get("device", {}))

            elif msg_type == "task_result":
                # Legacy one-shot result
                task_id   = msg.get("task_id")
                exit_code = msg.get("exit_code", -1)
                output    = msg.get("result_output", "")
                status    = msg.get("status", "completed")
                if task_id:
                    _save_task_result(task_id, status, output, exit_code)

            elif msg_type == "tool_result":
                # Agentic session step result — resolve the waiting Future
                call_id = msg.get("call_id")
                if call_id and call_id in _pending_tool_calls:
                    future = _pending_tool_calls.pop(call_id)
                    if not future.done():
                        future.set_result(msg)
                    log.debug("tool_result resolved: call_id=%s session=%s exit=%s",
                              call_id, msg.get("session_id", "?"), msg.get("exit_code"))
                else:
                    log.warning("tool_result for unknown call_id=%s", call_id)

            elif msg_type == "pong":
                pass

            elif msg_type == "queue_stats":
                # Agent is reporting its offline queue stats — just log for now
                log.debug("Agent queue stats: %s", msg)

            else:
                log.debug("Unknown message type from agent: %s", msg_type)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("Agent WebSocket error (device=%s): %s", device_id, e)
    finally:
        _connected_agents.pop(device_id, None)
        log.info("Agent disconnected: %s (remaining=%d)", device_id, len(_connected_agents))


# ─────────────────────────────────────────────────────────────────────────────
#  Agentic session — tool call dispatch (called by remediation_graph.py)
# ─────────────────────────────────────────────────────────────────────────────

async def dispatch_tool_call(
    device_id:   str,
    session_id:  str,
    command:     str,
    args:        dict,
    allow_tier2: bool = True,
    script:      str  = None,
    script_type: str  = "auto",
    timeout:     int  = 120,
) -> dict:
    """
    Send a tool_call to the connected agent and await its tool_result.

    Returns the tool_result dict, or raises TimeoutError / RuntimeError.
    """
    ws = _connected_agents.get(device_id)
    if not ws:
        raise RuntimeError(f"Device {device_id!r} is not connected")

    call_id = str(uuid.uuid4())
    loop    = asyncio.get_event_loop()
    future  = loop.create_future()
    _pending_tool_calls[call_id] = future

    msg = {
        "type":        "tool_call",
        "session_id":  session_id,
        "call_id":     call_id,
        "command":     command,
        "args":        args,
        "allow_tier2": allow_tier2,
    }
    if script is not None:
        msg["script"]      = script
        msg["script_type"] = script_type

    try:
        await ws.send_text(json.dumps(msg))
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending_tool_calls.pop(call_id, None)
        raise TimeoutError(f"tool_call '{command}' timed out after {timeout}s")
    except Exception:
        _pending_tool_calls.pop(call_id, None)
        raise


def is_agent_connected(device_id: str) -> bool:
    return device_id in _connected_agents


# ── REST: legacy one-shot task dispatch ──────────────────────────────────────

@router.post("/api/tickets/{ticket_number}/agent-task", tags=["agent"])
async def create_agent_task(ticket_number: str, req: AgentTaskRequest):
    ws = _connected_agents.get(req.device_id)
    if not ws:
        raise HTTPException(
            status_code=409,
            detail=f"Device {req.device_id!r} is not connected",
        )

    task_id = str(uuid.uuid4())
    db      = DatabaseConnection()
    _create_task_record(db, task_id, ticket_number, req.device_id,
                        req.command_type, req.command_payload)

    task_msg = {
        "type":            "task",
        "task_id":         task_id,
        "ticket_number":   ticket_number,
        "command_type":    req.command_type,
        "command_payload": req.command_payload,
    }
    try:
        await ws.send_text(json.dumps(task_msg))
        _mark_task_sent(db, task_id)
        return {"task_id": task_id, "status": "sent", "device_id": req.device_id}
    except Exception as e:
        log.error("Failed to send task to agent: %s", e)
        raise HTTPException(status_code=500, detail="Failed to deliver task to agent")


@router.get("/api/tickets/{ticket_number}/agent-tasks", tags=["agent"])
def list_agent_tasks(ticket_number: str):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT * FROM agent_tasks WHERE ticket_number = %s ORDER BY created_at DESC",
        (ticket_number,),
    )
    return {"tasks": rows or []}


@router.get("/api/agents/connected", tags=["agent"])
def list_connected_agents():
    return {"connected": list(_connected_agents.keys()), "count": len(_connected_agents)}


# ── Session status endpoints ──────────────────────────────────────────────────

@router.get("/api/sessions/{session_id}", tags=["agent"])
def get_session(session_id: str):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT * FROM agent_sessions WHERE session_id = %s", (session_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")
    return rows[0]


@router.get("/api/sessions/{session_id}/steps", tags=["agent"])
def get_session_steps(session_id: str):
    db = DatabaseConnection()
    rows = db.execute_query(
        "SELECT * FROM session_steps WHERE session_id = %s ORDER BY step_number",
        (session_id,),
    )
    return {"steps": rows or []}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _create_task_record(db, task_id, ticket_number, device_id, command_type, payload):
    db.execute_query(
        """INSERT INTO agent_tasks
           (task_id, ticket_number, device_id, command_type, command_payload, status)
           VALUES (%s, %s, %s, %s, %s::jsonb, 'pending')""",
        (task_id, ticket_number, device_id, command_type, json.dumps(payload)),
        fetch=False,
    )


def _mark_task_sent(db, task_id):
    db.execute_query(
        "UPDATE agent_tasks SET status='sent', sent_at=NOW() WHERE task_id=%s",
        (task_id,), fetch=False,
    )


def _save_task_result(task_id, status, output, exit_code):
    try:
        db = DatabaseConnection()
        db.execute_query(
            """UPDATE agent_tasks SET
               status=%s, result_output=%s, result_exit_code=%s, completed_at=NOW()
               WHERE task_id=%s""",
            (status, output, exit_code, task_id), fetch=False,
        )
    except Exception as e:
        log.error("Failed to save task result for %s: %s", task_id, e)


def _update_device_last_seen(device_id: str, device_info: dict):
    """Best-effort: log device info (no separate devices table yet)."""
    log.info("Device %s last seen: os=%s hostname=%s",
             device_id,
             device_info.get("os", "?"),
             device_info.get("hostname", "?"))
